import QtQuick
import Quickshell.Io
import Quickshell.Services.Mpris
import qs.Commons
import "lib/Design.js" as Design
import "lib/Roond.js" as Roond

// Headless singleton for the Roon plugin.
//
// Two sources, chosen for what each is good at:
//
//   1. MPRIS, bound to `org.mpris.MediaPlayer2.omarchy_roon` SPECIFICALLY.
//      Push-based over D-Bus, so track, art and play state cost nothing and
//      arrive instantly. Binding to a named player rather than "whatever is
//      active" is the whole reason this widget exists: Omarchy's own Media
//      widget cycles between every player on the bus, so with mopidy and
//      playerctld also present it will happily show something that is not Roon.
//
//   2. The daemon's HTTP API, polled slowly, for the things MPRIS cannot say.
//      MPRIS has one player and no vocabulary for rooms, so which zone this is,
//      what other zones exist, and switching between them all come from here.
//
// Quickshell ships no WebSocket module and qt6-websockets is not installed, so
// the daemon's /ws is not reachable from QML. Slow polling is enough because
// everything time-sensitive already arrives over MPRIS.
Item {
  id: root

  // Injected by the shell host.
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""

  readonly property string pluginId: "quickshell.roon"

  // PluginRegistry stamps the resolved plugin directory onto the manifest, which
  // is how the visualiser locates its cava wrapper without a hardcoded path.
  readonly property string pluginDir:
    manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""
  readonly property string cavaPath:
    pluginDir !== "" ? pluginDir + "/bin/omarchy-roon-cava" : ""

  // Saving any file under ~/.config/omarchy/plugins/ hot-reloads plugin code,
  // which destroys this object while HTTP callbacks may still be in flight. A
  // callback that then writes a property is a use-after-free, and Quickshell
  // turns that into a fatal abort -- taking the whole shell down with it.
  // Everything async below bails out once this flips.
  property bool alive: true

  Component.onDestruction: {
    // A surface that is destroyed rather than closed -- a hot reload with the
    // overlay open -- never gets to un-suppress, and the daemon would go on
    // swallowing track notifications until something toggled it. The call
    // carries no callbacks, so nothing reaches back into an object that is on
    // its way out.
    if (root.openSurfaces > 0) root.suppressNotifications(false)
    root.alive = false
    stateTimer.running = false
    queueTimer.running = false
    setupTimer.running = false
    positionTimer.running = false
    resyncTimer.running = false
    resyncSoon.running = false
  }

  // ---- MPRIS ---------------------------------------------------------------

  readonly property var players: Mpris.players ? Mpris.players.values : []

  readonly property var player: {
    for (var i = 0; i < players.length; i++) {
      var p = players[i]
      if (!p) continue
      if (String(p.dbusName || "").indexOf("omarchy_roon") !== -1) return p
    }
    return null
  }

  readonly property bool connected: player !== null
  readonly property bool playing: player ? !!player.isPlaying : false
  readonly property string title: player ? (player.trackTitle || "") : ""
  readonly property string artist: player ? (player.trackArtist || "") : ""
  readonly property string album: player ? (player.trackAlbum || "") : ""
  readonly property string artUrl: player ? (player.trackArtUrl || "") : ""
  readonly property bool hasTrack: title !== "" || artist !== ""
  readonly property real length: player ? (player.length || 0) : 0
  readonly property real volume: player && player.volumeSupported ? player.volume : 0
  readonly property bool volumeSupported: player ? !!player.volumeSupported : false

  // The bar button lives in a widget instance, one per monitor, while this
  // service is a singleton -- so IPC lands here and the panels listen.
  signal toggleRequested()

  // ---- the timeline --------------------------------------------------------
  //
  // MPRIS only emits a position change on an explicit seek -- it never ticks --
  // and reading player.position costs a D-Bus round trip. So the timeline runs
  // off a wall-clock anchor rather than an accumulating counter:
  //
  //   position = anchorPos + (now - anchorAt)
  //
  // Incrementing a counter on a timer drifts, because timers fire late under
  // load and the error accumulates for the whole track. Deriving from Date.now()
  // cannot drift; the timer only decides how often the bar repaints.

  property real position: 0
  property real anchorPos: 0
  property real anchorAt: 0

  function anchorPosition(seconds) {
    root.anchorPos = Math.max(0, seconds)
    root.anchorAt = Date.now()
    root.position = root.anchorPos
  }

  function syncPosition() {
    if (player && player.positionSupported) root.anchorPosition(player.position)
  }

  onPlayingChanged: root.syncPosition()
  onTitleChanged: root.anchorPosition(0)

  Timer {
    id: positionTimer
    running: root.playing && root.hasTrack
    interval: 200
    repeat: true
    onTriggered: {
      if (!root.alive) return
      var next = root.anchorPos + (Date.now() - root.anchorAt) / 1000
      root.position = root.length > 0 ? Math.min(next, root.length) : next
    }
  }

  // Re-anchor against the player periodically so a seek from a phone, a pause,
  // or buffering cannot leave the bar telling a different story than the audio.
  Timer {
    id: resyncTimer
    running: root.connected
    interval: 5000
    repeat: true
    onTriggered: if (root.alive) root.syncPosition()
  }

  function seekTo(seconds) {
    if (!player) {
      if (zoneId) Roond.request("POST", "/seek",
                                { zone_id: zoneId, seconds: seconds }, null, null)
      return
    }
    if (player.canSeek) player.position = seconds
    root.anchorPosition(seconds)
  }

  // Scrubbing moves the local clock on every mouse move and tells Roon once, on
  // release. A seek per move floods the Core and makes the audio stutter under
  // the cursor -- so the playhead follows the pointer immediately and the Core
  // hears about it at the end.
  function previewSeek(seconds) { root.anchorPosition(seconds) }

  function commitSeek(seconds) {
    root.anchorPosition(seconds)
    root.seekTo(seconds)
    // Re-anchor once the transport has had a moment: a seek Roon clamps or
    // refuses corrects itself rather than leaving the playhead lying.
    resyncSoon.restart()
  }

  Timer {
    id: resyncSoon
    interval: 700
    onTriggered: if (root.alive) root.syncPosition()
  }

  readonly property bool canSeek: {
    if (player) return !!player.canSeek
    var z = root.pinnedZone
    return z && z.can ? !!z.can.seek : false
  }

  // ---- album art palette ---------------------------------------------------
  //
  // Two problems share one answer: a spectrum analyser drawn in the theme's
  // accent ignores the record it sits beside, and text over a bright sleeve is
  // unreadable. The daemon measures both from the artwork; this asks once per
  // track and remembers the answer.
  //
  // Driven off artUrl rather than the polled state because MPRIS pushes it the
  // instant the track changes, where the poll is four seconds behind.

  property color artAccent: "transparent"
  // A separate boolean because a QML `color` cannot be usefully compared to a
  // string: `artAccent !== "transparent"` is a type mismatch that is always
  // true, so every consumer silently painted with a fully transparent colour
  // whenever a sleeve reported no colour at all.
  property bool hasArtAccent: false
  property bool artIsLight: false
  // 0..1. How light the sleeve is, which decides how much wash the text over it
  // needs: a white cover lifts a blurred backdrop until muted metadata vanishes
  // into it, and that is a measurement rather than a guess.
  property real artLuma: 0
  property string paletteKey: ""

  // The sleeve's colour, lifted until it reads against the surface every one of
  // this plugin's panels is drawn on.
  //
  // A colour taken from artwork often lands within a couple of percent of that
  // panel, and WCAG asks 3:1 of anything carrying meaning. Falling back to the
  // theme's accent there throws the record away for the sake of a little
  // luminance; lifting the same HUE until it passes keeps the sleeve's identity
  // and the legibility both. Only when no lightness of that hue would do does
  // the theme take over.
  //
  // Computed here rather than in each surface so there is one answer: the bar's
  // playhead, the analyser and the queue's marker are all wearing the same
  // record.
  readonly property color artAccentReadable: {
    if (!root.hasArtAccent) return Color.accent
    var background = Color.menu.background
    var candidate = Qt.color(root.artAccent)
    if (Design.contrast(candidate, background) >= 3) return candidate
    var lightness = Design.contrastLightness(candidate.hslHue, candidate.hslSaturation,
                                             candidate.hslLightness, background, 3)
    if (lightness < 0) return Color.accent
    return Qt.hsla(candidate.hslHue, candidate.hslSaturation, lightness, 1)
  }

  function imageKeyFromUrl(url) {
    var m = String(url || "").match(/\/api\/image\/([^?]+)/)
    return m ? m[1] : ""
  }

  onArtUrlChanged: {
    var key = root.imageKeyFromUrl(root.artUrl)
    if (key === "" || key === root.paletteKey) return
    root.paletteKey = key
    Roond.palette(key, function(p) {
      if (!root.alive || !p) return
      // A monochrome cover honestly has no colour, and the daemon returns null
      // rather than a washed-out grey. Fall back to the theme rather than
      // tinting the interface with something that is not there.
      root.hasArtAccent = !!p.color
      root.artAccent = p.color ? p.color : "transparent"
      root.artIsLight = !!p.isLight
      root.artLuma = p.luma !== undefined ? p.luma : 0
    }, function() {
      if (!root.alive) return
      root.hasArtAccent = false
      root.artAccent = "transparent"
      root.artIsLight = false
      root.artLuma = 0
    })
  }

  // ---- daemon state --------------------------------------------------------

  property bool daemonUp: false
  property string zoneName: ""
  property string zoneId: ""
  property string zoneState: "stopped"
  property string imageBase: ""
  property var zones: []
  // Present only when the pinned zone is this machine's own endpoint: another
  // room is played by hardware this machine knows nothing about.
  property var outputFormat: null
  property bool notificationsOn: true
  property string lastError: ""

  // Set by the panel so the poll can slow down when nobody is looking at it.
  property bool panelOpen: false

  // Zone membership changes rarely and never urgently: a room is renamed, an
  // endpoint appears, someone re-pins. Everything second-by-second already
  // arrives over MPRIS, so the closed-panel rate only has to keep the bar's zone
  // name honest -- and that changes about never.
  // False until the first answer, either way. "Not answered yet" and "answered
  // and it is down" look identical on a boolean, and a surface that treats them
  // the same shows a connection error every time the shell restarts.
  property bool probed: false

  Timer {
    id: stateTimer
    interval: (root.panelOpen || root.openSurfaces > 0) ? 3000 : 20000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  function refresh() {
    if (!root.alive) return
    Roond.state(function(s) {
      if (!root.alive || !s) return
      root.probed = true
      root.daemonUp = true
      root.lastError = ""
      root.imageBase = s.image_base || ""
      root.zones = s.zones || []
      root.notificationsOn = !!s.notifications
      root.outputFormat = s.output_format || null
      root.zoneId = s.pinned_zone_id || ""
      var z = null
      for (var i = 0; i < root.zones.length; i++) {
        if (root.zones[i].zone_id === root.zoneId) { z = root.zones[i]; break }
      }
      root.zoneName = z ? z.name : ""
      root.zoneState = z ? z.state : "stopped"
    }, function(err) {
      if (!root.alive) return
      root.probed = true
      root.daemonUp = false
      root.lastError = err
    })
  }

  // ---- the queue -----------------------------------------------------------
  //
  // The daemon holds one subscription, following the pinned zone, so /queue is
  // a read of its memory rather than a call to the Core. It is still only
  // fetched while a surface is showing it: nothing in the bar renders a queue,
  // and a poll nobody reads is a poll not worth making.

  property var queue: []
  property string queueZoneId: ""

  // The counters come from the zone, not from the list: the subscription is
  // capped at 100 items, so counting rows would report the window rather than
  // the queue.
  readonly property int queueRemaining:
    pinnedZone ? (pinnedZone.queue_items_remaining || 0) : 0
  readonly property real queueTimeRemaining:
    pinnedZone ? (pinnedZone.queue_time_remaining || 0) : 0

  Timer {
    id: queueTimer
    running: root.openSurfaces > 0
    interval: 5000
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshQueue()
  }

  function refreshQueue() {
    if (!root.alive) return
    Roond.queue(function(q) {
      if (!root.alive || !q) return
      root.queue = q.items || []
      root.queueZoneId = q.zone_id || ""
    }, function() {
      if (!root.alive) return
      root.queue = []
    })
  }

  function playFromHere(queueItemId) {
    if (queueItemId === undefined || queueItemId === null) return
    Roond.playFromHere(queueItemId, function() {
      if (!root.alive) return
      // The queue shortens from the front when you play from the middle, so
      // ask again rather than waiting out the poll.
      root.refreshQueue()
      root.refresh()
    })
  }

  function artForKey(key, px) {
    return Roond.art(root.imageBase, key, px || 96)
  }

  // ---- first-run setup -------------------------------------------------------
  //
  // The daemon computes the ladder; this only holds the answer and asks again
  // while someone is looking at it. Polled briskly rather than on the slow
  // state cadence, because the rung people get stuck on -- approval -- is one a
  // human is acting on RIGHT NOW, on a phone, and the surface should notice
  // within a second or two of them tapping Enable.

  property var setupRungs: []
  property bool setupReady: false
  property string setupBlockedOn: ""
  // Same trap as `probed`: "not asked yet" must not render as "not set up".
  property bool setupProbed: false

  Timer {
    id: setupTimer
    running: root.openSurfaces > 0 && !root.setupReady
    interval: 2000
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshSetup()
  }

  function refreshSetup() {
    if (!root.alive) return
    Roond.setup(function(s) {
      if (!root.alive || !s) return
      root.setupProbed = true
      root.setupRungs = s.rungs || []
      root.setupReady = !!s.ready
      root.setupBlockedOn = s.blocked_on || ""
    }, function() {
      if (!root.alive) return
      // The daemon not answering is its own state, rendered by the surface as
      // "the daemon is down" rather than as a half-built ladder.
      root.setupProbed = true
      root.setupRungs = []
      root.setupReady = false
    })
  }

  // ---- playback modes --------------------------------------------------------
  //
  // Shuffle, repeat and Roon Radio are properties of the ZONE, not of this
  // client: changing one changes it for the room, and for whoever is looking at
  // their phone. That is Roon's model rather than a shortcut here, and it is
  // why these read from the zone's own settings rather than from anything
  // stored locally.

  readonly property var zoneSettings: pinnedZone ? (pinnedZone.settings || ({})) : ({})
  readonly property bool shuffle: !!zoneSettings.shuffle
  readonly property bool autoRadio: !!zoneSettings.auto_radio
  // "disabled" | "loop" | "loop_one", which is Roon's own vocabulary.
  readonly property string loopMode: String(zoneSettings.loop || "disabled")

  function applySettings(settings) {
    if (!root.zoneId) return
    // Refresh rather than guess: the daemon is on loopback and answers in
    // milliseconds, so the honest value is back before the menu redraws.
    Roond.settings(root.zoneId, settings, function() {
      if (root.alive) root.refresh()
    })
  }

  function toggleShuffle() { root.applySettings({ shuffle: !root.shuffle }) }
  function toggleAutoRadio() { root.applySettings({ auto_radio: !root.autoRadio }) }

  function cycleLoop() {
    var next = root.loopMode === "disabled" ? "loop"
             : (root.loopMode === "loop" ? "loop_one" : "disabled")
    root.applySettings({ loop: next })
  }

  // ---- surfaces --------------------------------------------------------------
  //
  // How many of this plugin's windows are on screen. The state poll speeds up
  // while any of them is, and the notification card is silenced for a track a
  // surface is already showing.

  property int openSurfaces: 0

  function surfaceOpened() {
    root.openSurfaces = root.openSurfaces + 1
    root.suppressNotifications(true)
    root.refresh()
    root.refreshQueue()
    root.refreshSetup()
  }

  function surfaceClosed() {
    root.openSurfaces = Math.max(0, root.openSurfaces - 1)
    if (root.openSurfaces === 0) root.suppressNotifications(false)
  }

  // Summon the overlay, optionally straight onto one of its views.
  function openView(view) {
    if (!shell) return false
    return shell.summon(pluginId, JSON.stringify({ view: view || "nowPlaying" })) === true
  }

  // Messages go to Omarchy's own OSD rather than to a banner of our own: a
  // browse action that says "Playing" is exactly what that surface is for, and
  // one notification style across the shell beats two.
  //
  // The text carries catalogue strings -- an album name, an error from the Core
  // -- so the angle brackets come out here, at the boundary, rather than
  // trusting the other side not to treat them as markup.
  function osd(message) {
    if (!shell || !message) return
    shell.summon("omarchy.osd", JSON.stringify({
      icon: "media",
      message: String(message).replace(/[<>]/g, "")
    }))
  }

  // ---- actions -------------------------------------------------------------
  //
  // Transport goes through MPRIS when it can: the player object is already
  // bound, so it is one D-Bus call with no round trip through the daemon. The
  // HTTP path is the fallback for when MPRIS is unavailable but the daemon is
  // not, which is exactly the case where the bar should still work.

  function playPause() {
    if (player) { player.togglePlaying(); return }
    if (zoneId) Roond.control(zoneId, "playpause")
  }

  function next() {
    if (player && player.canGoNext) { player.next(); return }
    if (zoneId) Roond.control(zoneId, "next")
  }

  function previous() {
    if (player && player.canGoPrevious) { player.previous(); return }
    if (zoneId) Roond.control(zoneId, "previous")
  }

  // ---- mute ----------------------------------------------------------------
  //
  // MPRIS has no concept of mute, so this comes from the daemon's zone state and
  // goes back through Roon's own mute call. Driving the fader to zero would look
  // the same for a second and then lose the level you were at.

  readonly property var pinnedZone: {
    for (var i = 0; i < zones.length; i++) {
      if (zones[i].zone_id === root.zoneId) return zones[i]
    }
    return null
  }

  // The daemon publishes a format only when the pinned zone IS this machine's
  // own endpoint, so its presence is the honest test for "this room is here".
  // Another room is played by hardware we know nothing about -- including
  // whether its audio ever touches this machine's PipeWire monitor, which is
  // what the spectrum analyser reads.
  readonly property bool isLocalZone: outputFormat !== null

  readonly property var pinnedOutput: {
    for (var i = 0; i < zones.length; i++) {
      if (zones[i].zone_id !== root.zoneId) continue
      var outs = zones[i].outputs || []
      for (var j = 0; j < outs.length; j++) {
        if (outs[j].can_mute) return outs[j]
      }
      return outs.length > 0 ? outs[0] : null
    }
    return null
  }

  readonly property bool canMute: pinnedOutput ? !!pinnedOutput.can_mute : false

  // Zone state arrives on a four-second poll, which is far too slow for a button
  // the user just pressed. The optimistic value wins until the poll catches up
  // and agrees.
  property int mutedOverride: -1
  readonly property bool muted: mutedOverride >= 0
                                ? mutedOverride === 1
                                : (pinnedOutput ? !!pinnedOutput.muted : false)

  function toggleMute() {
    if (!canMute || !pinnedOutput) return
    var next = !root.muted
    root.mutedOverride = next ? 1 : 0
    Roond.mute(pinnedOutput.output_id, next, function() {
      if (!root.alive) return
      root.refresh()
    }, function() {
      if (!root.alive) return
      root.mutedOverride = -1     // the call failed; trust the daemon again
      root.refresh()
    })
  }

  // Once the poll reports what we asked for, stop overriding it.
  onPinnedOutputChanged: {
    if (mutedOverride < 0 || !pinnedOutput) return
    if (!!pinnedOutput.muted === (mutedOverride === 1)) mutedOverride = -1
  }

  function setVolume(v) {
    if (player && player.volumeSupported) player.volume = Math.max(0, Math.min(1, v))
  }

  function pinZone(id) {
    Roond.pin(id, function() { root.refresh() })
  }

  // Transient: silence the duplicate card while a surface showing the track is
  // on screen. Not persisted, so it can never leave notifications off for good.
  function suppressNotifications(on) {
    Roond.request("POST", "/notifications", { suppress: !!on }, null, null)
  }

  function toggleNotifications() {
    Roond.notifications(!root.notificationsOn, function(r) {
      if (!root.alive || !r) return
      root.notificationsOn = !!r.notifications
    })
  }

  function artFor(px) {
    // Prefer MPRIS's art URL: it is already the Core's own URL, put there by the
    // daemon, so there is nothing to rebuild.
    if (root.artUrl !== "") return root.artUrl
    return ""
  }

  // ---- IPC -----------------------------------------------------------------
  //
  // Keybindings and menu entries become `omarchy-shell roon <action>`.

  IpcHandler {
    target: "roon"

    function playpause(): string { root.playPause(); return "ok" }
    function next(): string      { root.next();      return "ok" }
    function previous(): string  { root.previous();  return "ok" }
    function refresh(): string   { root.refresh();   return "ok" }
    function player(): string    { root.toggleRequested(); return "ok" }
    function toggle(): string    { root.toggleRequested(); return "ok" }
    // The overlay is a separate surface from the bar's mini player: the shell
    // routes a summon to the plugin's overlay entry point, which the bar
    // popup's own toggle cannot do.
    function overlay(): string   { return root.openView("nowPlaying") ? "ok" : "unhandled" }
    function queue(): string     { return root.openView("queue") ? "ok" : "unhandled" }
    function library(): string   { return root.openView("browse") ? "ok" : "unhandled" }
    function home(): string      { return root.openView("home") ? "ok" : "unhandled" }
    function notifications(): string {
      root.toggleNotifications()
      return root.notificationsOn ? "off" : "on"
    }
    function zone(): string {
      return root.zoneName === "" ? "(no zone)" : root.zoneName
    }
    function status(): string {
      if (!root.daemonUp) return "daemon down: " + root.lastError
      if (!root.connected) return "no MPRIS player"
      return root.zoneName + ": " + (root.playing ? "playing" : "paused")
             + (root.hasTrack ? " — " + root.title + " · " + root.artist : "")
    }
  }
}

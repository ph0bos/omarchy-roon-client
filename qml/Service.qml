import QtQuick
import Quickshell.Io
import Quickshell.Services.Mpris
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
    root.alive = false
    stateTimer.running = false
    positionTimer.running = false
    resyncTimer.running = false
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
  property string paletteKey: ""

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
    }, function() {
      if (!root.alive) return
      root.hasArtAccent = false
      root.artAccent = "transparent"
      root.artIsLight = false
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
  Timer {
    id: stateTimer
    interval: root.panelOpen ? 3000 : 20000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  function refresh() {
    if (!root.alive) return
    Roond.state(function(s) {
      if (!root.alive || !s) return
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
      root.daemonUp = false
      root.lastError = err
    })
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

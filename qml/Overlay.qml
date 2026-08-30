import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import QtQuick
import qs.Commons
import qs.Ui
import "components"
import "views"

// The plugin's single summoned surface.
//
// A plugin only ever gets ONE panel-kind entry point loaded -- the shell's
// computePanelEntries() picks "panel" over "overlay" over "menu" and loads just
// that one -- so now playing and the queue cannot be separate plugin surfaces.
// They are views here instead, chosen by the summon payload:
//
//   omarchy-shell shell summon quickshell.roon '{"view":"queue"}'
//
// keepLoaded is set in the manifest, so this window and its state survive
// between summons: reopening lands you back where you were.
//
// Structure ported from omarchy-tidal's Overlay.qml, which is where the screen
// picking, the cross-fade between views and the keyboard model were worked out.
Item {
  id: root

  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property string currentView: "nowPlaying"

  readonly property var svc: shell ? shell.serviceFor("quickshell.roon") : null

  readonly property string pluginDir:
    manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""

  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color borderColor: Color.menu.border
  readonly property color scrim: Color.menu.scrim
  readonly property string fontFamily: Style.font.menuFamily

  // Setup is shown when we KNOW something is missing, never merely because
  // nothing has answered yet. Both probes are asynchronous and the first summon
  // after a shell restart beats them, so testing readiness alone would open the
  // wizard on a perfectly healthy install every single time.
  readonly property bool decided: svc ? (svc.probed && (!svc.daemonUp || svc.setupProbed)) : false
  readonly property bool blocked: decided && (!svc.daemonUp || !svc.setupReady)

  // The view the summon actually asked for, remembered so that finishing setup
  // drops you where you were headed instead of leaving you in the wizard.
  property string requestedView: "nowPlaying"

  onBlockedChanged: {
    if (!root.opened) return
    if (root.blocked) root.currentView = "setup"
    else if (root.currentView === "setup") root.currentView = root.requestedView
  }

  function open(payloadJson) {
    var args = {}
    if (payloadJson) {
      try { args = JSON.parse(payloadJson) || {} } catch (e) { args = {} }
    }
    var requested = String(args.view || "nowPlaying")
    if (requested !== "queue" && requested !== "browse") requested = "nowPlaying"
    root.requestedView = requested
    root.currentView = root.blocked ? "setup" : requested
    root.menuOpen = false
    root.shortcutsOpen = false
    root.targetScreen = root.pickScreen()
    root.opened = true
    root.markLoaded(root.currentView)
    // Tell the service a surface is up: it polls faster while something is
    // watching, and silences the duplicate notification card for a track this
    // window is already showing.
    if (root.svc) root.svc.surfaceOpened()
    Qt.callLater(root.focusView)
  }

  function close() {
    root.menuOpen = false
    root.shortcutsOpen = false
    root.opened = false
    if (root.svc) root.svc.surfaceClosed()
  }

  function focusView() {
    // The browse view drives a list and a text field, so it takes the keyboard
    // while it is showing. Keys it does not accept still bubble up to the
    // catcher, which is what keeps Escape and the transport working from in
    // there. Handing focus to the catcher unconditionally is the bug that
    // silently kills a view's entire keyboard model.
    if (root.currentView === "browse" && browseLoader.item) {
      browseLoader.item.forceActiveFocus()
      return
    }
    keyCatcher.forceActiveFocus()
  }

  property bool menuOpen: false
  property bool shortcutsOpen: false

  function toggleShortcuts() {
    root.menuOpen = false
    root.shortcutsOpen = !root.shortcutsOpen
    Qt.callLater(root.shortcutsOpen ? shortcutSheet.forceActiveFocus : root.focusView)
  }

  function runMenuAction(action) {
    root.menuOpen = false
    if (!root.svc) return
    switch (action) {
      case "nowPlaying":    root.currentView = "nowPlaying"; break
      case "queue":         root.currentView = "queue"; break
      case "library":       root.currentView = "browse"; break
      case "shuffle":       root.svc.toggleShuffle(); break
      case "repeat":        root.svc.cycleLoop(); break
      case "radio":         root.svc.toggleAutoRadio(); break
      case "notifications": root.svc.toggleNotifications(); break
      case "keys":          root.toggleShortcuts(); break
    }
  }

  // Which screen to open on, decided at open time rather than left to whatever
  // the window was created against.
  //
  // `keepLoaded` keeps this window alive between summons, so it can outlive the
  // monitor it was first created on. Unplug a display -- or let one come back
  // after a fallback output -- and the surface holds a screen that no longer
  // exists: Quickshell logs "Layershell screen does not correspond to a real
  // screen" and the overlay never maps again until the shell is restarted.
  // Re-picking on every open also means it opens on the screen you are actually
  // looking at.
  property var targetScreen: null

  function pickScreen() {
    var monitor = Hyprland.focusedMonitor
    var name = monitor ? String(monitor.name || "") : ""
    var screens = Quickshell.screens
    for (var i = 0; i < screens.length; i++) {
      if (String(screens[i].name) === name) return screens[i]
    }
    // No match: let the compositor choose.
    return null
  }

  // Views stay loaded once visited. Destroying and rebuilding them on every
  // switch throws away scroll position, and tears down the analyser's audio
  // capture along with it.
  property bool nowPlayingLoaded: false
  property bool queueLoaded: false
  property bool browseLoaded: false

  function markLoaded(view) {
    if (view === "queue") root.queueLoaded = true
    else if (view === "browse") root.browseLoaded = true
    else if (view === "nowPlaying") root.nowPlayingLoaded = true
  }

  onCurrentViewChanged: {
    root.markLoaded(root.currentView)
    if (root.opened) Qt.callLater(root.focusView)
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.targetScreen
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-roon"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
      MouseArea {
        anchors.fill: parent
        onClicked: root.close()
      }
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: root.opened
      Keys.onEscapePressed: root.close()

      // Neither view drives a list with the keyboard yet, so the keys are the
      // transport and the two faces. Browse and search will take their own
      // focus when they arrive, and keys they do not accept still bubble here.
      Keys.onPressed: function(event) {
        if (!root.svc) return
        if (event.key === Qt.Key_Space) {
          root.svc.playPause()
          event.accepted = true
        } else if (event.key === Qt.Key_Q) {
          root.currentView = "queue"
          event.accepted = true
        } else if (event.key === Qt.Key_N) {
          root.currentView = "nowPlaying"
          event.accepted = true
        } else if (event.key === Qt.Key_Right) {
          root.svc.next()
          event.accepted = true
        } else if (event.key === Qt.Key_Left) {
          root.svc.previous()
          event.accepted = true
        } else if (event.key === Qt.Key_M) {
          root.menuOpen = !root.menuOpen
          event.accepted = true
        } else if (event.key === Qt.Key_L || event.key === Qt.Key_Slash) {
          root.currentView = "browse"
          event.accepted = true
        } else if (event.key === Qt.Key_Question) {
          root.toggleShortcuts()
          event.accepted = true
        }
      }

      Rectangle {
        id: card
        anchors.centerIn: parent
        width: root.blocked
          ? Math.min(Style.space(620), parent.width - Style.gapsOut * 4)
          : Math.min(Style.space(1020), parent.width - Style.gapsOut * 4)
        height: root.blocked
          ? Math.min(Style.space(120) + setupLoader.height,
                     parent.height - Style.gapsOut * 4)
          : Math.min(Style.space(760), parent.height - Style.gapsOut * 4)
        radius: Style.cornerRadius
        color: root.background
        border.width: Math.max(1, Style.space(1))
        border.color: root.borderColor

        // Swallow clicks so they do not fall through to the dismiss scrim.
        MouseArea { anchors.fill: parent }

        Item {
          id: header
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(18)
          height: Style.space(30)

          Row {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(10)

            // Mark and wordmark sit on one baseline, and the mark is drawn to
            // the height of the capitals rather than to the text's full line
            // box, which includes ascent and descent the letters never fill.
            RoonMark {
              anchors.baseline: wordmark.baseline
              anchors.baselineOffset: 1
              markHeight: Math.round(Style.font.heading * 0.86)
              color: Color.accent
              live: root.svc ? root.svc.playing : false
              struck: root.svc ? !root.svc.daemonUp : true
            }

            Text {
              id: wordmark
              textFormat: Text.PlainText
              anchors.verticalCenter: parent.verticalCenter
              text: "Roon"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.weight: Font.DemiBold
              font.letterSpacing: 0.6
            }
          }

          Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(6)

            HeaderButton {
              glyph: ""
              tooltip: "Now playing"
              visible: !root.blocked
              active: root.currentView === "nowPlaying"
              fontFamily: root.fontFamily
              foreground: root.foreground
              onActivated: root.currentView = "nowPlaying"
            }

            HeaderButton {
              glyph: ""
              tooltip: "Library"
              visible: !root.blocked
              active: root.currentView === "browse"
              fontFamily: root.fontFamily
              foreground: root.foreground
              onActivated: root.currentView = "browse"
            }

            HeaderButton {
              glyph: ""
              tooltip: "Queue"
              visible: !root.blocked
              active: root.currentView === "queue"
              fontFamily: root.fontFamily
              foreground: root.foreground
              onActivated: root.currentView = "queue"
            }

            HeaderButton {
              glyph: ""
              tooltip: "Menu"
              visible: !root.blocked
              active: root.menuOpen
              fontFamily: root.fontFamily
              foreground: root.foreground
              onActivated: root.menuOpen = !root.menuOpen
            }
          }
        }

        Rectangle {
          id: headerRule
          anchors.top: header.bottom
          anchors.topMargin: Style.space(12)
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(1, Style.space(1))
          color: root.borderColor
          opacity: 0.5
        }

        Loader {
          id: nowPlayingLoader
          anchors.top: headerRule.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: transportBar.top
          anchors.margins: Style.space(4)
          active: root.nowPlayingLoaded
          // Cross-faded rather than cut. Both views stay loaded, so the swap is
          // a change of attention, not a page load, and it should look like one.
          opacity: root.currentView === "nowPlaying" && !root.blocked ? 1 : 0
          visible: opacity > 0.01
          Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

          sourceComponent: NowPlayingView {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
        }

        Loader {
          id: browseLoader
          anchors.top: headerRule.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: transportBar.top
          anchors.margins: Style.space(10)
          anchors.topMargin: Style.space(10)
          active: root.browseLoaded
          opacity: root.currentView === "browse" && !root.blocked ? 1 : 0
          visible: opacity > 0.01
          Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

          sourceComponent: BrowseView {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
            focus: root.currentView === "browse" && root.opened
            // "Playing" and "Not found" alike go to Omarchy's own OSD: a browse
            // action's answer is a message, not a page.
            onActionMessage: function(text, isError) {
              if (root.svc) root.svc.osd(text)
            }
          }
        }

        Loader {
          id: queueLoader
          anchors.top: headerRule.bottom
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: transportBar.top
          anchors.margins: Style.space(10)
          anchors.topMargin: Style.space(14)
          active: root.queueLoaded
          opacity: root.currentView === "queue" && !root.blocked ? 1 : 0
          visible: opacity > 0.01
          Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

          sourceComponent: QueueView {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
        }

        Loader {
          id: setupLoader
          anchors.top: headerRule.bottom
          anchors.topMargin: Style.space(18)
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.leftMargin: Style.space(18)
          anchors.rightMargin: Style.space(18)
          active: root.currentView === "setup"
          visible: active
          height: item ? item.implicitHeight : 0

          sourceComponent: SetupWizard {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
        }

        // Click anywhere else to dismiss the menu, rather than leaving it up
        // until something is chosen.
        MouseArea {
          anchors.fill: parent
          visible: root.menuOpen
          z: 90
          onClicked: root.menuOpen = false
        }

        QuickMenu {
          id: quickMenu
          visible: root.menuOpen
          z: 100
          anchors.top: header.bottom
          anchors.right: parent.right
          anchors.topMargin: Style.space(6)
          anchors.rightMargin: Style.space(14)
          svc: root.svc
          foreground: root.foreground
          fontFamily: root.fontFamily
          onRequested: function(action) { root.runMenuAction(action) }
          onZoneRequested: function(zoneId) {
            root.menuOpen = false
            // The queue follows the pin, so switching rooms here changes what
            // this whole window is about -- which is the point.
            if (root.svc) root.svc.pinZone(zoneId)
          }
        }

        ShortcutSheet {
          id: shortcutSheet
          anchors.fill: parent
          z: 210
          visible: root.shortcutsOpen
          foreground: root.foreground
          fontFamily: root.fontFamily
          onClosed: {
            root.shortcutsOpen = false
            Qt.callLater(root.focusView)
          }
        }

        // One transport strip shared by every view: the controls should not
        // disappear just because you switched to the queue.
        PlayerBar {
          id: transportBar
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(10)
          visible: !root.blocked
          svc: root.svc
          foreground: root.foreground
          fontFamily: root.fontFamily
          expanded: root.currentView === "nowPlaying"
          onArtClicked: root.currentView =
            root.currentView === "nowPlaying" ? "queue" : "nowPlaying"
        }
      }
    }
  }
}

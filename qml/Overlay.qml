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

  // Which of Roon's hierarchies the library view is in, so the sidebar can show
  // where you are rather than merely which view is up.
  property string hierarchy: "albums"

  // Searching is a place of its own, and the sidebar should say so while you
  // are in it rather than leaving the last hierarchy lit.
  readonly property bool searchingNow:
    currentView === "browse" && browseLoader.item ? browseLoader.item.searchMode : false

  // The sidebar's own key: a view for the standalone entries, a hierarchy for
  // the library ones.
  readonly property string place: currentView !== "browse" ? currentView
    : (root.searchingNow ? "search" : root.hierarchy)
  property bool sidebarFocused: false

  // Now playing is the record, given the whole window -- the same move TIDAL's
  // now-playing face makes. The sidebar is navigation, and while you are
  // looking at a sleeve there is nothing to navigate; the transport stays,
  // because that is what you reach for from here.
  readonly property bool fullBleed: currentView === "nowPlaying" && !blocked

  // Where the artwork came from, so leaving it puts you back rather than
  // somewhere arbitrary.
  property string lastPageView: "browse"

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
    if (requested === "library") requested = "browse"
    if (requested !== "queue" && requested !== "browse" && requested !== "home")
      requested = "nowPlaying"
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

  // One way in for every navigation: the sidebar, the keys and the summon
  // payload all land here, so "where am I" has one answer.
  // `reset` is the difference between choosing a place and returning to one.
  // Clicking Albums in the sidebar means "take me to the albums", top and all;
  // coming back from the artwork means "put me back where I was", three levels
  // into a record if that is where I left.
  function goTo(key, reset) {
    if (root.currentView !== "nowPlaying") root.lastPageView = root.place
    if (key === "nowPlaying" || key === "queue" || key === "home") {
      root.currentView = key
      return
    }
    if (key === "search") {
      // Search is a page you arrive at with the cursor already in the field --
      // not a box in the corner of whatever you were reading.
      root.currentView = "browse"
      Qt.callLater(function() {
        if (browseLoader.item) browseLoader.item.beginSearch()
      })
      return
    }
    var moved = root.hierarchy !== key
    root.hierarchy = key
    root.currentView = "browse"
    if ((moved || reset) && browseLoader.item) browseLoader.item.openHierarchy(key)
    Qt.callLater(root.focusView)
  }

  function toggleShortcuts() {
    root.menuOpen = false
    root.shortcutsOpen = !root.shortcutsOpen
    Qt.callLater(root.shortcutsOpen ? shortcutSheet.forceActiveFocus : root.focusView)
  }

  function runMenuAction(action) {
    root.menuOpen = false
    if (!root.svc) return
    switch (action) {
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
  property bool homeLoaded: false

  function markLoaded(view) {
    if (view === "home") root.homeLoaded = true
    else if (view === "queue") root.queueLoaded = true
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
        } else if (event.key === Qt.Key_H) {
          root.goTo("home", false)
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
        } else if (event.key === Qt.Key_L) {
          root.goTo(root.hierarchy, false)
          event.accepted = true
        } else if (event.key === Qt.Key_Slash) {
          root.goTo("search", false)
          event.accepted = true
        } else if (event.key === Qt.Key_Tab) {
          root.sidebarFocused = !root.sidebarFocused
          if (!root.sidebarFocused) Qt.callLater(root.focusView)
          event.accepted = true
        } else if (root.sidebarFocused && event.key === Qt.Key_Down) {
          sidebar.move(1); event.accepted = true
        } else if (root.sidebarFocused && event.key === Qt.Key_Up) {
          sidebar.move(-1); event.accepted = true
        } else if (root.sidebarFocused
                   && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
          sidebar.activate(); event.accepted = true
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

        // ---- the sidebar ----
        //
        // The shape of the library, permanently on screen. Navigation is a
        // place you are in rather than a mode you toggle, which is how both
        // Apple Music and TIDAL are laid out and what a row of unlabelled
        // glyphs in a header cannot be.
        Item {
          id: sidebarPane
          anchors.left: parent.left
          anchors.top: parent.top
          anchors.bottom: transportBar.top
          anchors.leftMargin: Style.space(10)
          anchors.topMargin: Style.space(14)
          anchors.bottomMargin: Style.space(10)
          width: root.fullBleed ? 0 : Style.space(186)
          visible: !root.blocked && width > 0
          clip: true
          // Slides away rather than vanishing: the artwork arriving and the
          // navigation leaving are one movement, not two events.
          Behavior on width { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }

          // Laid out by hand rather than in a Row: a Row positions its
          // children itself and IGNORES their anchors, so the baseline anchor
          // did nothing and the mark sat low and left of the word. Here the
          // mark is centred on the text's own capitals, which is the line the
          // eye reads it against.
          Item {
            id: wordmarkRow
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Style.space(11)
            height: Style.space(30)

            RoonMark {
              id: mark
              anchors.left: parent.left
              anchors.verticalCenter: wordmark.verticalCenter
              markHeight: Math.round(Style.font.heading * 0.86)
              color: Color.accent
              live: root.svc ? root.svc.playing : false
              struck: root.svc ? !root.svc.daemonUp : true
            }

            Text {
              id: wordmark
              textFormat: Text.PlainText
              anchors.left: mark.right
              anchors.leftMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              text: "Roon"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.heading
              font.weight: Font.DemiBold
              font.letterSpacing: 0.6
            }
          }

          Sidebar {
            id: sidebar
            anchors.top: wordmarkRow.bottom
            anchors.topMargin: Style.space(14)
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
            current: root.place
            focused: root.sidebarFocused
            onChosen: function(key, label) {
              root.sidebarFocused = false
              root.goTo(key, true)
            }
            onRoomsRequested: root.menuOpen = !root.menuOpen
          }
        }

        Rectangle {
          id: sidebarRule
          anchors.left: sidebarPane.right
          anchors.leftMargin: Style.space(10)
          anchors.top: parent.top
          anchors.bottom: transportBar.top
          width: Math.max(1, Style.space(1))
          color: root.borderColor
          opacity: 0.4
          visible: !root.blocked && !root.fullBleed
        }

        // The wizard has no sidebar to sit beside, so it keeps the mark of its
        // own and the card shrinks around it.
        Item {
          id: setupHeader
          anchors.top: parent.top
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.margins: Style.space(18)
          height: Style.space(30)
          visible: root.blocked

          RoonMark {
            id: setupMark
            anchors.left: parent.left
            anchors.verticalCenter: setupWordmark.verticalCenter
            markHeight: Math.round(Style.font.heading * 0.86)
            color: Color.accent
            live: false
            struck: root.svc ? !root.svc.daemonUp : true
          }

          Text {
            id: setupWordmark
            textFormat: Text.PlainText
            anchors.left: setupMark.right
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            text: "Roon"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.weight: Font.DemiBold
            font.letterSpacing: 0.6
          }
        }

        Rectangle {
          id: headerRule
          anchors.top: setupHeader.bottom
          anchors.topMargin: Style.space(12)
          anchors.left: parent.left
          anchors.right: parent.right
          height: Math.max(1, Style.space(1))
          color: root.borderColor
          opacity: 0.5
          visible: root.blocked
        }

        // ---- the page ----
        Item {
          id: content
          anchors.left: sidebarRule.right
          anchors.leftMargin: root.fullBleed ? 0 : Style.space(12)
          anchors.right: parent.right
          anchors.rightMargin: root.fullBleed ? 0 : Style.space(4)
          anchors.top: parent.top
          anchors.topMargin: root.fullBleed ? 0 : Style.space(12)
          anchors.bottom: transportBar.top
          visible: !root.blocked
        }

        Loader {
          id: nowPlayingLoader
          anchors.fill: content
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
          id: homeLoader
          anchors.fill: content
          active: root.homeLoaded
          opacity: root.currentView === "home" && !root.blocked ? 1 : 0
          visible: opacity > 0.01
          Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

          sourceComponent: HomeView {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
            onNavigate: function(key) { root.goTo(key, true) }
            // A shelf card and a playlist row both mean "open this", and the
            // library view is what knows how to open things -- so the home page
            // hands it the item rather than growing a second browse cursor.
            onOpenItem: function(hierarchy, index) {
              root.goTo(hierarchy, true)
              // The Loader may only be resolving on this very call, so the
              // hand-off waits a tick rather than racing it.
              Qt.callLater(function() {
                if (browseLoader.item) browseLoader.item.openLater(index)
              })
            }
          }
        }

        Loader {
          id: browseLoader
          anchors.fill: content
          active: root.browseLoaded
          opacity: root.currentView === "browse" && !root.blocked ? 1 : 0
          visible: opacity > 0.01
          Behavior on opacity { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }

          sourceComponent: BrowseView {
            svc: root.svc
            foreground: root.foreground
            fontFamily: root.fontFamily
            // Where the sidebar says we are, so the page it loads on creation
            // is the page the sidebar is pointing at. Without this the view
            // opens its own default and the two disagree on screen.
            hierarchy: root.hierarchy
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
          anchors.fill: content
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
          // Anchored to the corner it is summoned from -- the room at the
          // foot of the sidebar -- the way Apple Music hangs its AirPlay and
          // account popovers off theirs.
          anchors.bottom: transportBar.top
          anchors.left: parent.left
          anchors.bottomMargin: Style.space(6)
          anchors.leftMargin: Style.space(12)
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
          onArtClicked: root.goTo(
            root.currentView === "nowPlaying" ? root.lastPageView : "nowPlaying")
        }
      }
    }
  }
}

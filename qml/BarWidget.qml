import QtQuick
import qs.Ui
import qs.Commons
import "components"

// The Roon icon in the bar, and the mini player behind it.
//
// A tray-sized icon rather than an inline label: an endpoint is a thing you
// glance at and occasionally poke, not a running commentary that shoves the
// clock sideways every few minutes. The glyph carries state -- playing, idle,
// daemon down -- and everything else lives one click away.
//
// Built on Panel rather than BarWidget because that is the shell's own pattern
// for "icon in the cluster that opens something": Bluetooth, Network, Audio and
// Display are all Panels, and inheriting it means the popup gets the shell's
// anchoring, keyboard handling and popout-switching for free.
//
// State comes from the plugin's service, which is bound to OUR MPRIS player
// specifically, so this never polls and never speaks HTTP itself.
Panel {
  id: root
  moduleName: "quickshell.roon"
  // The service owns the "roon" IPC target: it is a singleton, whereas a bar
  // widget is instantiated once per monitor, and a target only permits one
  // handler. `omarchy-shell roon player` reaches us through its signal instead.
  ipcTarget: "roon"
  manageIpc: false

  readonly property var svc: bar?.shell?.serviceFor("quickshell.roon") ?? null

  readonly property bool daemonUp: svc ? svc.daemonUp : false
  readonly property bool playing: svc ? svc.playing : false
  readonly property bool hasTrack: svc ? svc.hasTrack : false
  readonly property string title: svc ? svc.title : ""
  readonly property string artist: svc ? svc.artist : ""
  readonly property string album: svc ? svc.album : ""
  readonly property string artUrl: svc ? svc.artUrl : ""
  readonly property string zoneName: svc ? svc.zoneName : ""
  readonly property string zoneId: svc ? svc.zoneId : ""
  readonly property var zones: svc && svc.zones ? svc.zones : []
  readonly property real trackPosition: svc ? svc.position : 0
  readonly property real trackLength: svc ? svc.length : 0

  // What is actually coming out of this machine. Roon's extension API exposes no
  // format data at all, but this machine is the endpoint: RAATServer writes down
  // exactly what the Core hands it, and the daemon reads that back.
  readonly property var outputFormat: svc ? svc.outputFormat : null
  readonly property string qualityLabel: outputFormat ? outputFormat.label : ""
  readonly property bool hiRes: outputFormat
    ? (outputFormat.sample_rate > 48000 || outputFormat.bits > 16) : false

  // Collapsed by default and reset on close: the picker is an occasional errand,
  // not the state the panel should reopen in.
  property bool zonesExpanded: false

  function clock(seconds) {
    var s = Math.max(0, Math.floor(seconds || 0))
    return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2)
  }

  readonly property color markColor: bar ? bar.barForeground : "#ffffff"

  // The sleeve's own colour, when it has one. A black-and-white cover reports
  // none, and the theme's accent is the honest fallback rather than a grey.
  readonly property color artAccent: svc && svc.hasArtAccent
                                     ? svc.artAccent : Color.accent
  readonly property string summary: {
    if (!daemonUp) return "Roon daemon unavailable"
    if (!hasTrack) return zoneName !== "" ? zoneName + " · idle" : "Roon"
    return zoneName + " · " + title + (artist !== "" ? " — " + artist : "")
  }

  // Ui/Panel is a bare Item with no size of its own, and the bar sizes each slot
  // from `implicitWidth`. Without these the widget occupies zero pixels: present
  // in the layout, invisible, and impossible to click. Every first-party Panel
  // does the same two lines.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Connections {
    target: root.svc
    function onToggleRequested() { root.toggle() }
  }

  // A notification card announcing the track, drawn on top of the player that
  // is already showing the track, is noise -- and on this bar it lands directly
  // over the panel. Silence it for as long as the panel is open.
  onOpenedChanged: {
    if (svc) {
      svc.suppressNotifications(opened)
      // Let the service slow its poll right down while nothing is on screen.
      svc.panelOpen = opened
      if (opened) svc.refresh()
    }
    // The picker is an occasional errand, not the state the panel reopens in.
    if (!opened) zonesExpanded = false
  }
  Component.onDestruction: if (svc) svc.suppressNotifications(false)

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // No text: the mark below is drawn instead, so it can carry state and read
    // as an application rather than as another audio glyph.
    text: ""
    iconComponent: Component {
      // The mark lives in components/RoonMark.qml so the overlay header wears
      // the same one. It sizes itself from `markHeight` rather than from its
      // box, so it is centred in whatever the bar gives the icon.
      Item {
        RoonMark {
          anchors.centerIn: parent
          markHeight: Math.min(parent.width, parent.height)
          color: root.markColor
          live: root.playing && root.daemonUp
          struck: !root.daemonUp
        }
      }
    }
    onPressed: function(b) { root.toggle() }
    onWheelMoved: function(delta) {
      if (!root.svc) return
      if (delta > 0) root.svc.previous()
      else root.svc.next()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.fill: parent
        spacing: Style.space(10)

        // ---------- now playing ----------
        Row {
          width: parent.width
          spacing: Style.space(10)

          BorderSurface {
            id: sleeve
            width: Style.space(64)
            height: Style.space(64)
            radius: Style.spacing.labelGap
            color: Style.normalFillFor(root.bar.foreground, Color.accent)
            borderSpec: Border.controlSpec("normal", root.bar.foreground, Color.accent)

            Image {
              anchors.fill: parent
              anchors.margins: Style.space(2)
              source: root.artUrl
              fillMode: Image.PreserveAspectCrop
              asynchronous: true
              cache: true
              visible: source !== "" && status === Image.Ready
            }

            Text {
              anchors.centerIn: parent
              visible: root.artUrl === ""
              text: "󰝚"
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.icon
            }
          }

          Column {
            width: parent.width - sleeve.width - Style.space(10)
            spacing: Style.space(1)
            anchors.verticalCenter: parent.verticalCenter

            // Title and the quality badge share a line: the format belongs to
            // what is playing, not to the chrome, and this is the one number a
            // Roon listener looks for first.
            Item {
              width: parent.width
              height: titleText.implicitHeight

              Text {
                id: titleText
                anchors.left: parent.left
                anchors.right: quality.visible ? quality.left : parent.right
                anchors.rightMargin: quality.visible ? Style.space(8) : 0
                text: root.hasTrack ? root.title
                                    : (root.daemonUp ? "Nothing playing" : "Daemon unavailable")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.subtitle
                elide: Text.ElideRight
              }

              Row {
                id: quality
                anchors.right: parent.right
                anchors.verticalCenter: titleText.verticalCenter
                spacing: Style.space(4)
                visible: root.qualityLabel !== ""

                // Above CD gets the record's colour; CD quality gets the theme.
                // A badge that shouts on every track says nothing.
                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(5)
                  height: width
                  radius: width / 2
                  color: root.hiRes ? root.artAccent : root.bar.foreground
                  opacity: root.hiRes ? 1.0 : 0.45
                  antialiasing: true
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: root.qualityLabel
                  color: root.bar.foreground
                  opacity: root.hiRes ? 0.95 : 0.6
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }
            Text {
              width: parent.width
              text: root.artist
              color: root.bar.foreground
              opacity: 0.7
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
              visible: root.artist !== ""
            }
            Text {
              width: parent.width
              text: root.album
              color: root.bar.foreground
              opacity: 0.45
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              visible: root.album !== ""
            }
          }
        }

        // ---------- the spectrum ----------
        //
        // Real audio: cava taps PipeWire's default sink monitor, the same signal
        // reaching the DAC. It only works because the bridge is routed through
        // plug:pipewire rather than taking the ALSA device exclusively.
        Visualizer {
          width: parent.width
          height: Style.space(46)
          visible: root.daemonUp && root.svc && root.svc.cavaPath !== ""
          binPath: root.svc ? root.svc.cavaPath : ""
          active: root.opened && root.playing
          bars: 28
          segments: 14
          litColor: root.artAccent
          peakColor: Qt.lighter(root.artAccent, 1.4)
          dimColor: root.bar.foreground
        }

        // ---------- timeline ----------
        Column {
          width: parent.width
          spacing: Style.space(3)
          visible: root.hasTrack && root.trackLength > 0

          PanelSlider {
            id: timeline
            width: parent.width
            bar: root.bar
            minimum: 0
            maximum: Math.max(1, root.trackLength)
            step: 1
            value: root.trackPosition
            // The record's own colour, so the timeline reads as part of the
            // album rather than part of the chrome.
            fillColor: root.artAccent
            knobColor: root.artAccent
            onMoved: function(v) { if (root.svc) root.svc.seekTo(v) }
            onReleased: function(v) { if (root.svc) root.svc.seekTo(v) }
          }

          Item {
            width: parent.width
            height: elapsed.implicitHeight

            Text {
              id: elapsed
              anchors.left: parent.left
              text: root.clock(timeline.dragging ? timeline.liveValue : root.trackPosition)
              color: root.bar.foreground
              opacity: 0.55
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              anchors.right: parent.right
              text: "-" + root.clock(Math.max(0, root.trackLength - root.trackPosition))
              color: root.bar.foreground
              opacity: 0.55
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        // ---------- transport ----------
        //
        // One primary action, filled in the record's colour, flanked by two
        // secondary ones at the same size. Emphasis by fill rather than by making
        // one glyph bigger, which is what made the row look accidental before.
        Item {
          width: parent.width
          height: Style.space(40)

          Row {
            anchors.centerIn: parent
            spacing: Style.space(14)

            PanelActionButton {
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰒮"
              tooltipText: "Previous"
              foreground: root.bar.foreground
              fontSize: Style.font.icon
              opacity: root.daemonUp ? 0.8 : 0.35
              enabled: root.daemonUp
              onClicked: if (root.svc) root.svc.previous()
            }

            PanelActionButton {
              anchors.verticalCenter: parent.verticalCenter
              iconText: root.playing ? "󰏤" : "󰐊"
              tooltipText: root.playing ? "Pause" : "Play"
              foreground: root.bar.foreground
              // Emphasis by size alone, the way Apple Music does it. A filled
              // accent disc was louder than anything else in the panel, and in a
              // monochrome shell it read as a button from a different app.
              fontSize: Style.font.icon * 1.5
              enabled: root.daemonUp
              opacity: root.daemonUp ? 1.0 : 0.35
              onClicked: if (root.svc) root.svc.playPause()
            }

            PanelActionButton {
              anchors.verticalCenter: parent.verticalCenter
              iconText: "󰒭"
              tooltipText: "Next"
              foreground: root.bar.foreground
              fontSize: Style.font.icon
              opacity: root.daemonUp ? 0.8 : 0.35
              enabled: root.daemonUp
              onClicked: if (root.svc) root.svc.next()
            }
          }

          // Announcements: a preference, so it sits quietly at the edge rather
          // than competing with the transport for the centre.
          PanelActionButton {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            iconText: root.svc && root.svc.notificationsOn ? "󰂚" : "󰂛"
            tooltipText: root.svc && root.svc.notificationsOn
                         ? "Announcing each track" : "Track announcements off"
            foreground: root.bar.foreground
            opacity: root.svc && root.svc.notificationsOn ? 0.75 : 0.35
            fontSize: Style.font.body
            onClicked: if (root.svc) root.svc.toggleNotifications()
          }
        }

        // ---------- volume ----------
        //
        // The quiet-speaker end is the mute button, which is where every player
        // puts it -- Apple Music, Spotify, the shell's own audio panel. Muted
        // dims the fill rather than zeroing it, so the level you will come back
        // to stays visible.
        Item {
          width: parent.width
          height: Style.space(22)
          visible: root.svc ? root.svc.volumeSupported : false

          readonly property bool muted: root.svc ? root.svc.muted : false
          readonly property bool canMute: root.svc ? root.svc.canMute : false

          Item {
            id: muteButton
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(18)
            height: Style.space(18)

            Text {
              anchors.centerIn: parent
              text: parent.parent.muted ? "󰝟" : "󰕿"
              color: root.bar.foreground
              opacity: parent.parent.muted ? 0.9
                       : (muteHover.containsMouse ? 0.75 : 0.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption

              Behavior on opacity { NumberAnimation { duration: 120 } }
            }

            MouseArea {
              id: muteHover
              anchors.fill: parent
              hoverEnabled: true
              enabled: muteButton.parent.canMute
              cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: if (root.svc) root.svc.toggleMute()
            }
          }

          Text {
            id: volHigh
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "󰕾"
            color: root.bar.foreground
            opacity: 0.4
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }

          PanelSlider {
            anchors.left: muteButton.right
            anchors.right: volHigh.left
            anchors.leftMargin: Style.space(6)
            anchors.rightMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            bar: root.bar
            minimum: 0
            maximum: 1
            step: 0.02
            value: root.svc ? root.svc.volume : 0
            // Muted keeps the position and loses the colour, so the level you
            // will return to is still readable.
            fillColor: parent.muted ? root.bar.foreground : root.artAccent
            knobColor: parent.muted ? root.bar.foreground : root.artAccent
            opacity: parent.muted ? 0.35 : 1.0
            onMoved: function(v) { if (root.svc) root.svc.setVolume(v) }
            onReleased: function(v) { if (root.svc) root.svc.setVolume(v) }

            Behavior on opacity { NumberAnimation { duration: 140 } }
          }
        }

        PanelSeparator {
          width: parent.width
          visible: root.daemonUp && root.zones.length > 0
        }

        // ---------- where ----------
        //
        // Roon's own apps keep the zone picker quiet: a speaker and a name at
        // the foot of the player, not a form control competing with the
        // transport. A full-width dropdown made choosing a room look like the
        // main thing you came here to do, when almost always you came to press
        // pause. It expands in place when you actually want it.
        Column {
          width: parent.width
          spacing: 0
          visible: root.daemonUp && root.zones.length > 0

          Item {
            width: parent.width
            height: Style.space(24)

            Row {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(6)

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "󰓃"
                color: root.bar.foreground
                opacity: zoneHover.containsMouse ? 0.8 : 0.5
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.zoneName !== "" ? root.zoneName : "no zone"
                color: root.bar.foreground
                opacity: zoneHover.containsMouse ? 0.95 : 0.6
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.zonesExpanded ? "󰅃" : "󰅀"
                color: root.bar.foreground
                opacity: 0.4
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                visible: root.zones.length > 1
              }
            }

            MouseArea {
              id: zoneHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: root.zones.length > 1 ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: if (root.zones.length > 1) root.zonesExpanded = !root.zonesExpanded
            }
          }

          Column {
            width: parent.width
            visible: root.zonesExpanded

            Repeater {
              model: root.zones

              delegate: Rectangle {
                required property var modelData
                readonly property bool current: modelData.zone_id === root.zoneId

                width: parent.width
                height: Style.space(24)
                radius: Style.cornerRadius
                color: pickHover.containsMouse
                       ? Style.normalFillFor(root.bar.foreground, Color.accent)
                       : "transparent"

                Text {
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(20)
                  anchors.verticalCenter: parent.verticalCenter
                  width: parent.width - Style.space(40)
                  text: modelData.name
                  color: root.bar.foreground
                  // Only the pinned zone is at full weight: it is the one the
                  // bar and the media keys follow.
                  opacity: parent.current ? 0.95 : 0.5
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }

                Text {
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.state === "playing" ? "󰐊" : ""
                  color: root.bar.foreground
                  opacity: 0.45
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.caption
                }

                MouseArea {
                  id: pickHover
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    if (root.svc) root.svc.pinZone(modelData.zone_id)
                    root.zonesExpanded = false
                  }
                }
              }
            }
          }
        }

      }
    }
  }
}

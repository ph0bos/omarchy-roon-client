import QtQuick
import qs.Commons
import "../components"
import "../lib/Design.js" as Design

// The record, given the room.
//
// A leaner cousin of omarchy-tidal's NowPlayingView: no lyrics face and no
// credits face, because Roon's extension API returns neither -- `now_playing`
// is three display strings and an image key, and there is no metadata call to
// ask for more. What it does have that Tidal does not is the room and the
// format actually leaving this machine, so those are what the page says.
//
// The backdrop is the sleeve itself, blurred, so the page wears the record's
// colour rather than a second competing picture of it.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  readonly property bool hasTrack: svc ? svc.hasTrack : false
  readonly property string artUrl: svc ? svc.artUrl : ""

  // The sleeve's colour, lifted by the service until it reads against the panel.
  // One answer for every surface: the playhead, the analyser and the queue's
  // marker are all wearing the same record.
  readonly property color accent: svc ? svc.artAccentReadable : Color.accent

  // How light the sleeve is. A white cover lifts the blurred backdrop until
  // muted metadata disappears into it -- so the wash over it is measured from
  // the artwork rather than fixed.
  readonly property real artLuma: svc ? svc.artLuma : 0

  readonly property var outputFormat: svc ? svc.outputFormat : null

  // The blurred sleeve behind everything. Kept well back: it is a wash, not a
  // picture, and text has to stay readable over it on light themes too.
  RoundedImage {
    anchors.fill: parent
    radius: Style.space(6)
    blur: 1.0
    decodeSize: 320
    source: root.artUrl
    opacity: root.hasTrack ? 0.22 : 0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Design.slow } }
  }

  Rectangle {
    anchors.fill: parent
    radius: Style.space(6)
    // Measured, not fixed: a bright sleeve needs more wash under the text than
    // a dark one, and the same number cannot be right for both.
    color: Qt.rgba(Color.menu.background.r, Color.menu.background.g,
                   Color.menu.background.b,
                   0.45 + Math.min(0.35, root.artLuma * 0.5))
    Behavior on color { ColorAnimation { duration: Design.slow } }
  }

  Column {
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(48), Style.space(560))
    spacing: Style.space(18)

    Item {
      id: sleeve
      anchors.horizontalCenter: parent.horizontalCenter
      width: Math.min(Style.space(340), root.height - Style.space(210))
      height: width
      visible: width > Style.space(60)

      TiltFrame {
        id: tilt
        anchors.fill: parent
        radius: Style.space(6)
        // It does not listen for the pointer itself -- two overlapping hover
        // areas means only the topmost hears anything -- so the area below
        // feeds it what it already knows.
        active: sleeveHover.containsMouse
        pointerX: sleeveHover.mouseX
        pointerY: sleeveHover.mouseY

        RoundedImage {
          id: sleeveArt
          anchors.fill: parent
          radius: Style.space(6)
          decodeSize: 640
          source: root.artUrl
        }
      }

      MouseArea {
        id: sleeveHover
        anchors.fill: parent
        hoverEnabled: true
      }

      // A record arriving, rather than one picture being swapped for another.
      // Fired off the artwork rather than the title because MPRIS pushes the
      // art at the moment the track changes, where the polled state is seconds
      // behind.
      Connections {
        target: root.svc
        function onArtUrlChanged() { arrive.restart() }
      }

      SequentialAnimation {
        id: arrive
        PropertyAction { target: sleeve; property: "opacity"; value: 0 }
        PropertyAction { target: sleeve; property: "scale"; value: 0.965 }
        ParallelAnimation {
          NumberAnimation {
            target: sleeve; property: "opacity"; to: 1
            duration: Design.base; easing.type: Easing.OutCubic
          }
          NumberAnimation {
            target: sleeve; property: "scale"; to: 1
            duration: Design.slow; easing.type: Easing.OutBack; easing.overshoot: 1.05
          }
        }
      }
    }

    Column {
      id: words
      width: parent.width
      spacing: Style.space(4)

      // A beat behind the sleeve: letting the object move first and the words
      // follow reads as one thing making room for another, where moving both
      // at once reads as the whole panel wobbling.
      Connections {
        target: root.svc
        function onArtUrlChanged() { settle.restart() }
      }

      SequentialAnimation {
        id: settle
        PauseAnimation { duration: Design.stagger }
        PropertyAction { target: words; property: "opacity"; value: 0 }
        NumberAnimation {
          target: words; property: "opacity"; to: 1
          duration: Design.base; easing.type: Easing.OutCubic
        }
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: root.hasTrack ? root.svc.title : "Nothing playing"
        elide: Text.ElideRight
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.weight: Font.DemiBold
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        visible: root.hasTrack
        text: root.svc ? root.svc.artist : ""
        elide: Text.ElideRight
        color: root.foreground
        opacity: 0.75
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        visible: root.hasTrack && root.svc.album !== ""
        text: root.svc ? root.svc.album : ""
        elide: Text.ElideRight
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    // Real audio: cava taps PipeWire's default sink monitor, the same signal
    // reaching the DAC. It only works because the bridge is routed through
    // plug:pipewire rather than taking the ALSA device exclusively -- and only
    // when the pinned zone is this machine, since another room's audio never
    // touches this monitor.
    Visualizer {
      width: parent.width
      height: Style.space(52)
      visible: root.svc && root.svc.cavaPath !== "" && root.svc.isLocalZone
      binPath: root.svc ? root.svc.cavaPath : ""
      active: root.visible && root.svc && root.svc.playing
      bars: 34
      segments: 16
      litColor: root.accent
      peakColor: Qt.lighter(root.accent, 1.4)
      dimColor: root.foreground
    }

    // Room and format, on one quiet line. The format is only shown when the
    // pinned zone is this machine's own endpoint: reporting our numbers for a
    // network streamer in another room would be a confident lie.
    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(8)
      visible: root.svc && root.svc.zoneName !== ""

      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: root.svc ? root.svc.zoneName : ""
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        visible: root.outputFormat !== null
        width: Style.space(3)
        height: width
        radius: width / 2
        color: Color.muted
        opacity: 0.6
      }

      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        visible: root.outputFormat !== null
        text: root.outputFormat ? root.outputFormat.label : ""
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}

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

  // The sleeve's own colour when it has one AND it can be seen against the
  // panel. `readableOr` is the measurement rather than the hope: a colour
  // lifted from artwork often lands within a couple of percent of the surface
  // it is drawn on, and WCAG asks 3:1 of anything that carries meaning.
  readonly property color accent: svc && svc.hasArtAccent
    ? Design.readableOr(svc.artAccent, Color.menu.background, Color.accent)
    : Color.accent

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
    color: Qt.rgba(Color.menu.background.r, Color.menu.background.g,
                   Color.menu.background.b, 0.55)
  }

  Column {
    anchors.centerIn: parent
    width: Math.min(parent.width - Style.space(48), Style.space(560))
    spacing: Style.space(18)

    RoundedImage {
      anchors.horizontalCenter: parent.horizontalCenter
      width: Math.min(Style.space(300),
                      root.height - Style.space(210))
      height: width
      radius: Style.space(6)
      decodeSize: 640
      source: root.artUrl
      visible: width > Style.space(60)
    }

    Column {
      width: parent.width
      spacing: Style.space(4)

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

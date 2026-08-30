import QtQuick
import qs.Commons

// Transport strip along the bottom of the overlay.
//
// Laid out with anchors, not a Row: a Row sums fixed child widths plus a
// "remaining space" child, and any miscalculation pushes the right-hand group
// off the edge. Anchoring the left and right groups to their edges and letting
// the seek bar fill what is between them cannot overflow at any width.
//
// Ported from omarchy-tidal's PlayerBar, with the links taken out. Tidal's
// title and artist are links into their pages; Roon has no metadata API, so
// there is no artist object to open -- an artist page is a position in the
// browse tree, reached by browsing to it. Making them look clickable would be
// a promise the API cannot keep. What takes their place on the right is the
// thing Roon does know and Tidal does not: which room this is.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  readonly property bool hasTrack: svc ? svc.hasTrack : false
  readonly property bool playing: svc ? svc.playing : false

  // What is actually coming out of this machine. Roon's extension API exposes
  // no format data at all, but this machine is the endpoint: RAATServer writes
  // down what the Core hands it and the daemon reads that back. Present only
  // when the pinned zone IS this machine -- another room is played by hardware
  // we know nothing about.
  readonly property var outputFormat: svc ? svc.outputFormat : null
  readonly property string qualityLabel: outputFormat ? outputFormat.label : ""
  readonly property bool hiRes: outputFormat
    ? (outputFormat.sample_rate > 48000 || outputFormat.bits > 16) : false

  // The sleeve's own colour, lifted until it can be seen against the panel. A
  // black-and-white cover reports none, and the theme's accent is the honest
  // fallback rather than a grey.
  readonly property color artAccent: svc ? svc.artAccentReadable : Color.accent

  readonly property color scrim: Qt.rgba(Color.menu.background.r, Color.menu.background.g,
                                         Color.menu.background.b, 0.45)

  // Clicking the artwork expands to the full now-playing view and clicking it
  // again contracts back. The host owns the view state; the bar only reports
  // the intent and is told which direction it is currently pointing.
  property bool expanded: false
  signal artClicked()

  implicitHeight: Style.space(64)
  height: implicitHeight

  Rectangle {
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    height: Math.max(1, Style.space(1))
    color: Color.menu.border
    opacity: 0.4
  }

  // ---- left: art + title ----
  Row {
    id: leftGroup
    anchors.left: parent.left
    anchors.leftMargin: Style.space(4)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(11)
    width: Style.space(250)

    Item {
      anchors.verticalCenter: parent.verticalCenter
      width: root.hasTrack ? Style.space(42) : 0
      height: width
      visible: width > 0

      RoundedImage {
        anchors.fill: parent
        radius: Style.space(3)
        decodeSize: 96
        source: root.svc ? root.svc.artUrl : ""
      }

      // Expand affordance, revealed on hover so it does not clutter the bar.
      Rectangle {
        anchors.fill: parent
        radius: Style.space(3)
        color: root.scrim
        opacity: artHover.containsMouse ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
      }

      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.expanded ? "" : ""
        color: root.foreground
        opacity: artHover.containsMouse ? 0.95 : 0
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Behavior on opacity { NumberAnimation { duration: 120 } }
      }

      MouseArea {
        id: artHover
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.artClicked()
      }
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(53)
      spacing: 2

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.hasTrack ? root.svc.title : "Nothing playing"
        elide: Text.ElideRight
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        visible: root.hasTrack
        text: root.svc ? root.svc.artist : ""
        elide: Text.ElideRight
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  // ---- right: mute, quality, room ----
  Row {
    id: rightGroup
    anchors.right: parent.right
    anchors.rightMargin: Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(10)

    // Roon's own mute, not a fader driven to zero: muting is reversible to the
    // level you were at, and survives a volume change.
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      visible: root.svc ? root.svc.canMute : false
      text: root.svc && root.svc.muted ? "󰝟" : "󰕿"
      color: root.svc && root.svc.muted ? Color.accent : Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall

      MouseArea {
        anchors.fill: parent
        anchors.margins: -Style.space(5)
        cursorShape: Qt.PointingHandCursor
        onClicked: { if (root.svc) root.svc.toggleMute() }
      }
    }

    // Above CD gets the record's colour; CD quality gets the theme. A badge
    // that shouts on every track says nothing.
    Row {
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)
      visible: root.qualityLabel !== ""

      Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(5)
        height: width
        radius: width / 2
        color: root.hiRes ? root.artAccent : root.foreground
        opacity: root.hiRes ? 1.0 : 0.45
        antialiasing: true
      }

      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: root.qualityLabel
        color: root.foreground
        opacity: root.hiRes ? 0.95 : 0.6
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      visible: root.svc && root.svc.zoneName !== ""
      text: root.svc ? root.svc.zoneName : ""
      color: Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  // ---- transport ----
  Row {
    id: transport
    anchors.left: leftGroup.right
    anchors.leftMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(14)

    Repeater {
      model: [
        { glyph: "", action: "previous" },
        { glyph: root.playing ? "" : "", action: "playPause" },
        { glyph: "", action: "next" }
      ]

      Text {
        textFormat: Text.PlainText
        id: btn
        required property var modelData
        anchors.verticalCenter: parent.verticalCenter
        text: btn.modelData.glyph
        color: hover.containsMouse ? Color.accent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: btn.modelData.action === "playPause" ? Style.font.title : Style.font.body

        MouseArea {
          id: hover
          anchors.fill: parent
          anchors.margins: -Style.space(6)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            if (!root.svc) return
            if (btn.modelData.action === "previous") root.svc.previous()
            else if (btn.modelData.action === "next") root.svc.next()
            else root.svc.playPause()
          }
        }
      }
    }
  }

  // ---- seek bar: fills whatever is left between transport and the right group ----
  SeekBar {
    anchors.left: transport.right
    anchors.leftMargin: Style.space(16)
    anchors.right: rightGroup.left
    anchors.rightMargin: Style.space(16)
    anchors.verticalCenter: parent.verticalCenter
    height: Style.space(26)
    visible: width > Style.space(90)
    svc: root.svc
    foreground: root.foreground
    fontFamily: root.fontFamily
    // The playhead belongs to the record it is playing.
    accent: root.artAccent
    Behavior on accent { ColorAnimation { duration: 280 } }
  }
}

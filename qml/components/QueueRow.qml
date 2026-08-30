import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// One entry in the queue.
//
// Deliberately leaner than the row omarchy-tidal uses: there is no favourite to
// toggle, no artist page to open and no context menu, because Roon's extension
// API exposes none of those for a queue item. What a queue item has is an id, a
// sleeve and three display strings -- so that is what the row shows, and the
// one thing it can do is start playback from here.
Item {
  id: root

  property var item: null
  // Built by the view: a queue item carries an `image_key`, and the Core's
  // `image_base` lives in /state rather than on the item.
  property string artUrl: ""
  // Not `index`: a ListView delegate declares `required property int index` to
  // take the model's, and a property of that name here would collide with it.
  property int rowIndex: 0
  property bool playing: false
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily
  property color accent: Color.accent

  signal activated()

  implicitHeight: Style.space(46)
  height: implicitHeight

  readonly property string title: item ? String(item.title || "") : ""
  readonly property string artist: item ? String(item.artist || "") : ""
  readonly property string album: item ? String(item.album || "") : ""
  readonly property real length: item ? Number(item.length || 0) : 0

  Rectangle {
    anchors.fill: parent
    anchors.leftMargin: Style.space(2)
    anchors.rightMargin: Style.space(2)
    radius: Style.space(4)
    color: hover.containsMouse ? Color.menu.selectedBackground : "transparent"
    Behavior on color { ColorAnimation { duration: Design.fast } }
  }

  Row {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(10)
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(11)

    // The playing row swaps its position number for a speaker, which is the
    // only place the interface claims to know which item is current -- see
    // QueueView for why that is a match rather than a fact.
    Item {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(20)
      height: Style.space(20)

      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.playing ? "" : String(root.rowIndex + 1)
        color: root.playing ? root.accent : Color.muted
        opacity: hover.containsMouse && !root.playing ? 0 : 1
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      // Hovering a row offers the only verb there is.
      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: ""
        visible: hover.containsMouse && !root.playing
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    RoundedImage {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(34)
      height: Style.space(34)
      radius: Style.space(3)
      decodeSize: 80
      source: root.artUrl
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(20 + 34 + 22 + 46)
      spacing: 1

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.title
        elide: Text.ElideRight
        color: root.playing ? root.accent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.album !== "" && root.album !== root.artist
              ? root.artist + "  ·  " + root.album
              : root.artist
        elide: Text.ElideRight
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(40)
      horizontalAlignment: Text.AlignRight
      text: root.length > 0 ? Design.clock(root.length) : ""
      color: Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MouseArea {
    id: hover
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onDoubleClicked: root.activated()
    // A single click plays, the way a queue behaves everywhere else: there is
    // nothing else a queue row can do, so making the obvious click do nothing
    // would be a dead surface.
    onClicked: root.activated()
  }
}

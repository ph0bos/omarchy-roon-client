import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// One row of the browse tree.
//
// Roon tells us what a row IS through `hint`, and the row is drawn from that
// rather than from anything we decide: "list" pushes deeper, "action" does
// something and comes back with a message, "header" is a label with nothing
// behind it. Guessing instead -- treating everything as a list -- is how you
// get a UI that opens an empty page when the user meant "play".
Item {
  id: root

  property var item: null
  property string artUrl: ""
  property bool selected: false
  // Round art for a person, square for a record; the view knows which.
  property bool circular: false
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  signal activated()

  readonly property string title: item ? String(item.title || "") : ""
  readonly property string subtitle: item ? String(item.subtitle || "") : ""
  readonly property string hint: item ? String(item.hint || "list") : "list"
  readonly property bool isHeader: hint === "header"
  readonly property bool isAction: hint === "action" || hint === "action_list"

  implicitHeight: isHeader ? Style.space(30) : Style.space(46)
  height: implicitHeight

  Rectangle {
    anchors.fill: parent
    anchors.leftMargin: Style.space(2)
    anchors.rightMargin: Style.space(2)
    radius: Style.space(4)
    visible: !root.isHeader
    color: root.selected || hover.containsMouse
      ? Color.menu.selectedBackground : "transparent"
    Behavior on color { ColorAnimation { duration: Design.fast } }
  }

  // A header is a label in the list, not a row you can land on.
  Text {
    textFormat: Text.PlainText
    visible: root.isHeader
    anchors.left: parent.left
    anchors.leftMargin: Style.space(12)
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Style.space(6)
    text: root.title.toUpperCase()
    color: Color.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1.3
  }

  Row {
    visible: !root.isHeader
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(10)
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(11)

    RoundedImage {
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(34)
      height: Style.space(34)
      // Round for a person, square for a record: the convention every music
      // app uses to separate an artist from an album at a glance. Roon does
      // not say which a row is, so the shape follows the hierarchy the surface
      // is in -- see BrowseView.
      radius: root.circular ? width / 2 : Style.space(3)
      decodeSize: 80
      visible: root.artUrl !== ""
      source: root.artUrl
    }

    // Something has to hold the left margin when a row has no art, or titles
    // jump left and right down the list.
    Item {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.artUrl === ""
      width: Style.space(34)
      height: Style.space(34)

      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.isAction ? "\uf04b" : "\uf001"
        color: Color.muted
        opacity: 0.5
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - Style.space(34 + 11 + 26)
      spacing: 1

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.title
        elide: Text.ElideRight
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        visible: root.subtitle !== ""
        text: root.subtitle
        elide: Text.ElideRight
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    // The verb, quietly: a chevron for somewhere to go, a play for something
    // that happens.
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(14)
      horizontalAlignment: Text.AlignRight
      text: root.isAction ? "\uf04b" : "\uf054"
      color: root.selected || hover.containsMouse ? Color.accent : Color.muted
      opacity: root.selected || hover.containsMouse ? 1.0 : 0.35
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MouseArea {
    id: hover
    anchors.fill: parent
    enabled: !root.isHeader
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: root.activated()
  }
}

import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// A row of artwork under a heading, with the way to the rest of it.
//
// Ported in shape from omarchy-tidal's Shelf. What it does NOT do is claim an
// order it does not have: Roon's extension API exposes no "recently played" and
// no "recently added", so a shelf here is the top of a hierarchy and is
// labelled as exactly that. Inventing "Jump back in" out of an alphabetical
// list would be the kind of lie an interface never recovers from.
Item {
  id: root

  property string title: ""
  property string action: "See all"
  property var items: []
  property var svc: null
  property bool circular: false
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  // The POSITION, not the item.
  //
  // An `item_key` is scoped to the browse session that produced it: the shelf
  // browses on its own key, so its keys mean nothing to the library view. An
  // index into the same hierarchy does -- re-browsing `albums` gives the same
  // list in the same order -- so that is what travels.
  signal opened(int index)
  signal actioned()

  implicitHeight: header.height + row.height + Style.space(6)

  Item {
    id: header
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    height: Style.space(26)

    Text {
      textFormat: Text.PlainText
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: root.title
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.weight: Font.DemiBold
    }

    Text {
      textFormat: Text.PlainText
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: root.action !== ""
      text: root.action
      color: seeAll.containsMouse ? Color.accent : Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption

      MouseArea {
        id: seeAll
        anchors.fill: parent
        anchors.margins: -Style.space(6)
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.actioned()
      }
    }
  }

  Row {
    id: row
    anchors.top: header.bottom
    anchors.topMargin: Style.space(6)
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.space(14)

    // A shelf is a row with spacing, so its gutters fall only BETWEEN the
    // cards: n cards and n-1 gaps. Using a grid's sum here would make every
    // shelf one gutter too wide.
    readonly property int columns: Math.max(1,
      Design.fitCards(row.width, Style.space(14), Style.space(Design.cardIdeal)))
    readonly property int cardWidth:
      Design.cardWidth(row.width, Style.space(14), row.columns)

    Repeater {
      model: root.items.slice(0, row.columns)

      ArtCard {
        required property var modelData
        required property int index

        width: row.cardWidth
        item: modelData
        circular: root.circular
        artUrl: root.svc && modelData.image_key
                ? root.svc.artForKey(modelData.image_key, 320) : ""
        foreground: root.foreground
        fontFamily: root.fontFamily
        onActivated: root.opened(index)
      }
    }
  }
}

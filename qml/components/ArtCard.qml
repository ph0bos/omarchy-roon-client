import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// One record, or one artist, as a tile.
//
// The card is mostly picture. The name and whoever made it sit underneath in
// two fixed lines, so a grid stays on one baseline no matter what its items
// are: a card whose subtitle happens to be empty still occupies both lines
// rather than pulling its neighbours out of alignment.
//
// Ported from omarchy-tidal's ArtCard with its second verb removed. Tidal's
// card has two ways in -- the picture opens the page, the play button starts it
// -- because its backend can play an album from an id. Roon cannot: playing
// something is an ACTION ITEM inside that album's own page, so the only thing a
// card here can do is open. A play button that had to walk the tree first would
// be a different gesture wearing the same glyph.
Item {
  id: root

  property var item: null
  property string artUrl: ""
  property bool selected: false
  // Round for a person, softly square for a record.
  property bool circular: false
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  signal activated()

  readonly property string label: item ? String(item.title || "") : ""
  readonly property string sublabel: item ? String(item.subtitle || "") : ""

  // "Play Album" is a verb sitting in a list of records. Drawn as a card it is
  // a big empty tile that reads as artwork that failed to load, so it gets the
  // shape of a button instead: same cell, same grid, obviously not a sleeve.
  readonly property string hint: item ? String(item.hint || "list") : "list"
  readonly property bool isAction: hint === "action" || hint === "action_list"

  // Keyboard selection and the pointer get the same treatment. A card that is
  // "selected" but looks nothing like a card under the cursor teaches two
  // different affordances for one state.
  readonly property bool hot: hover.containsMouse || root.selected

  // The space under a tile should be the space you can see. A text item's box
  // starts above its capitals, so a 9px margin draws as 12 and the labels sit
  // adrift from their artwork.
  FontMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.bodySmall
  }

  readonly property real labelCapGap: labelMetrics.ascent - labelMetrics.capitalHeight

  implicitWidth: Style.space(Design.cardIdeal)
  height: width + labels.implicitHeight + Style.space(9)

  Item {
    id: artFrame
    width: parent.width
    height: width

    Rectangle {
      anchors.fill: parent
      visible: root.isAction
      radius: Style.space(4)
      color: root.hot
        ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.22)
        : Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.10)
      border.width: Math.max(1, Style.space(1))
      border.color: root.hot ? Color.accent : "transparent"
      Behavior on color { ColorAnimation { duration: Design.fast } }

      Text {
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: "\uf04b"
        color: root.hot ? Color.accent : Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
      }
    }

    RoundedImage {
      id: art
      anchors.fill: parent
      visible: !root.isAction
      radius: root.circular ? width / 2 : Style.space(4)
      decodeSize: 256
      source: root.artUrl

      // The picture leans towards the cursor. Scaling the masked item scales
      // its mask with it, so the corners stay round through the whole move.
      // Only the pointer does this: the keyboard cursor gets a ring instead, so
      // the two states stay tellable apart when both are on screen.
      scale: hover.containsMouse ? 1.035 : 1.0
      Behavior on scale { NumberAnimation { duration: Design.fast; easing.type: Easing.OutCubic } }
    }

    // The keyboard cursor. A ring rather than a fill: the artwork is the
    // content, and a selected card should still be a picture. Drawn on the
    // artwork's own edge, where it cannot be misaligned -- it is the same
    // rectangle the artwork is.
    Rectangle {
      anchors.fill: parent
      radius: root.isAction ? Style.space(4) : art.radius
      color: "transparent"
      antialiasing: true
      border.width: Math.max(2, Style.space(2))
      border.color: Color.accent
      opacity: root.selected ? 1 : 0
      Behavior on opacity { NumberAnimation { duration: Design.fast } }
    }
  }

  Column {
    id: labels
    anchors.top: artFrame.bottom
    anchors.topMargin: Style.space(9) - root.labelCapGap
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: 1

    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: root.label
      elide: Text.ElideRight
      color: root.hot ? Color.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      Behavior on color { ColorAnimation { duration: Design.fast } }
    }

    // Always present, even when empty: two fixed lines is what keeps a grid on
    // one baseline.
    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: root.sublabel
      elide: Text.ElideRight
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
    onClicked: root.activated()
  }
}

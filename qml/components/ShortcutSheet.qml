import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// What the keyboard does, on the keyboard.
//
// A shell whose premise is the keyboard should be able to answer the question
// itself, so `?` puts the map on screen rather than leaving it in the README.
//
// Only keys this window actually handles are listed. The Super bindings are
// suggestions rather than facts -- a plugin cannot install a keybinding, so
// they are whatever you put in `bindings.lua` -- and they are labelled as such
// instead of being advertised as though they were already yours.
Item {
  id: root

  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  signal closed()

  readonly property var groups: [
    {
      title: "In this window",
      keys: [
        { keys: "Space", what: "Play or pause" },
        { keys: "← →", what: "Previous and next" },
        { keys: "N", what: "Now playing" },
        { keys: "Q", what: "The queue" },
        { keys: "L  /", what: "The library" },
        { keys: "M", what: "Menu: modes and rooms" },
        { keys: "?", what: "This list" },
        { keys: "Esc", what: "Close" }
      ]
    },
    {
      title: "In the library",
      keys: [
        { keys: "\u2191 \u2193", what: "Move" },
        { keys: "Enter", what: "Open it, or play it" },
        { keys: "Backspace", what: "Back up a level" },
        { keys: "/", what: "Search" },
        { keys: "Esc", what: "Leave the search field" }
      ]
    },
    {
      title: "With the mouse",
      keys: [
        { keys: "Click a row", what: "Play from there" },
        { keys: "Click the sleeve", what: "Swap view" },
        { keys: "Drag the playhead", what: "Seek" }
      ]
    },
    {
      title: "From anywhere, if you bind them",
      keys: [
        { keys: "roon overlay", what: "Open this window" },
        { keys: "roon queue", what: "Open it on the queue" },
        { keys: "roon playpause", what: "Play or pause" },
        { keys: "roon player", what: "The bar's mini player" }
      ]
    }
  ]

  Keys.onEscapePressed: root.closed()
  Keys.onPressed: function(event) {
    // Any second press of the key that opened it closes it again.
    if (event.key === Qt.Key_Question || event.key === Qt.Key_Slash) {
      root.closed()
      event.accepted = true
    }
  }

  Rectangle {
    anchors.fill: parent
    color: Color.menu.background
    opacity: root.visible ? 0.72 : 0
    Behavior on opacity { NumberAnimation { duration: Design.fast } }

    MouseArea {
      anchors.fill: parent
      onClicked: root.closed()
    }
  }

  Rectangle {
    anchors.centerIn: parent
    width: Math.min(Style.space(720), parent.width - Style.space(60))
    height: Math.min(content.implicitHeight + Style.space(34),
                     parent.height - Style.space(50))
    radius: Style.cornerRadius
    color: Color.menu.background
    border.width: Math.max(1, Style.space(1))
    border.color: Color.menu.border

    MouseArea { anchors.fill: parent }

    Column {
      id: content
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.margins: Style.space(17)
      spacing: Style.space(14)

      Text {
        textFormat: Text.PlainText
        text: "Keyboard"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        font.weight: Font.DemiBold
      }

      // Two columns, because stacked sections would be a scroll and this should
      // be readable at a glance.
      Row {
        width: parent.width
        spacing: Style.space(26)

        Repeater {
          model: 2

          Column {
            id: sheetColumn
            required property int index

            width: (content.width - Style.space(26)) / 2
            spacing: Style.space(14)

            Repeater {
              model: root.groups

              Column {
                id: group
                required property int index
                required property var modelData

                // Alternate groups down the two columns.
                visible: group.index % 2 === sheetColumn.index
                width: sheetColumn.width
                spacing: Style.space(5)

                Text {
                  textFormat: Text.PlainText
                  text: group.modelData.title.toUpperCase()
                  color: Color.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.letterSpacing: 1.3
                  bottomPadding: Style.space(2)
                }

                Repeater {
                  model: group.modelData.keys

                  Item {
                    id: row
                    required property var modelData

                    width: group.width
                    height: Style.space(19)

                    Text {
                      textFormat: Text.PlainText
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      width: Style.space(140)
                      text: row.modelData.keys
                      elide: Text.ElideRight
                      color: Color.accent
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.bodySmall
                    }

                    Text {
                      textFormat: Text.PlainText
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(146)
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      text: row.modelData.what
                      elide: Text.ElideRight
                      color: root.foreground
                      opacity: 0.85
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.bodySmall
                    }
                  }
                }
              }
            }
          }
        }
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Media keys work everywhere; they drive MPRIS directly. "
            + "The last group are omarchy-shell commands to bind in bindings.lua."
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}

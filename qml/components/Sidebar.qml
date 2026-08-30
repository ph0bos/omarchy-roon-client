import QtQuick
import qs.Commons
import "../lib/Design.js" as Design

// Where you are, and everywhere else you could be.
//
// The shape of the library, permanently on screen -- which is what Apple Music
// and TIDAL both do, and what a row of unlabelled glyphs in a header cannot.
// Navigation stops being a mode you toggle and becomes a place you are in.
//
// Every entry below the first two is a Roon *hierarchy*, which the API lets you
// jump straight into. That matters here: reaching the albums by walking the
// tree is Explore -> Library -> Albums, three moves to a place the protocol
// will take you in one.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  // "nowPlaying" | "queue" | a hierarchy name
  property string current: "nowPlaying"
  property bool focused: false
  property int index: 0

  signal chosen(string key, string label)
  signal roomsRequested()

  readonly property var sections: [
    {
      title: "",
      items: [
        { key: "nowPlaying", label: "Now playing", glyph: "" },
        { key: "queue",      label: "Queue",       glyph: "" }
      ]
    },
    {
      title: "Library",
      items: [
        { key: "albums",    label: "Albums",     glyph: "" },
        { key: "artists",   label: "Artists",    glyph: "" },
        { key: "genres",    label: "Genres",     glyph: "" },
        { key: "composers", label: "Composers",  glyph: "" },
        { key: "playlists", label: "Playlists",  glyph: "" }
      ]
    },
    {
      title: "More",
      items: [
        { key: "internet_radio", label: "Live radio", glyph: "" },
        { key: "browse",         label: "Explore",    glyph: "" }
      ]
    }
  ]

  // The sections flattened, because the keyboard moves through entries and does
  // not care which heading they sit under.
  readonly property var entries: {
    var out = []
    for (var s = 0; s < root.sections.length; s++) {
      var items = root.sections[s].items
      for (var i = 0; i < items.length; i++) out.push(items[i])
    }
    return out
  }

  function move(delta) {
    var next = root.index + delta
    root.index = Math.max(0, Math.min(root.entries.length - 1, next))
  }

  function activate() {
    var entry = root.entries[root.index]
    if (entry) root.chosen(entry.key, entry.label)
  }

  function selectCurrent() {
    for (var i = 0; i < root.entries.length; i++) {
      if (root.entries[i].key === root.current) { root.index = i; return }
    }
  }

  onCurrentChanged: root.selectCurrent()

  Column {
    id: column
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: room.top
    anchors.bottomMargin: Style.space(8)
    spacing: Style.space(2)

    Repeater {
      model: root.sections

      Column {
        id: section
        required property var modelData
        required property int index

        width: column.width
        spacing: 1

        Item {
          width: parent.width
          height: section.modelData.title === "" ? 0 : Style.space(26)
          visible: height > 0

          Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.leftMargin: Style.space(11)
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Style.space(5)
            text: section.modelData.title.toUpperCase()
            color: Color.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 1.3
          }
        }

        Repeater {
          model: section.modelData.items

          Rectangle {
            id: navRow
            required property var modelData

            readonly property bool isCurrent: modelData.key === root.current
            // The keyboard cursor and the current place are different things
            // and must look it: one is where you are, the other is where you
            // are about to go.
            readonly property bool cursor:
              root.focused && root.entries[root.index]
              && root.entries[root.index].key === navRow.modelData.key

            width: column.width
            height: Style.space(30)
            radius: Style.space(3)
            color: navRow.cursor ? Color.menu.selectedBackground
                 : (navRow.isCurrent
                    ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.10)
                    : (hover.containsMouse ? Color.menu.selectedBackground : "transparent"))
            Behavior on color { ColorAnimation { duration: Design.fast } }

            Row {
              anchors.verticalCenter: parent.verticalCenter
              anchors.left: parent.left
              anchors.leftMargin: Style.space(11)
              spacing: Style.space(9)

              Text {
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(16)
                text: navRow.modelData.glyph
                color: navRow.isCurrent ? Color.accent : Color.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }

              Text {
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                text: navRow.modelData.label
                color: navRow.isCurrent ? Color.accent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
            }

            MouseArea {
              id: hover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.chosen(navRow.modelData.key, navRow.modelData.label)
            }
          }
        }
      }
    }
  }

  // The room, at the foot of the sidebar.
  //
  // It belongs here rather than in a menu because everything above it is scoped
  // to it: the queue, the transport, the media keys and the bar all follow the
  // pinned zone. Apple Music puts the AirPlay target in the same corner for the
  // same reason.
  Rectangle {
    id: room
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    height: Style.space(42)
    radius: Style.space(3)
    color: roomHover.containsMouse ? Color.menu.selectedBackground : "transparent"
    Behavior on color { ColorAnimation { duration: Design.fast } }

    Row {
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.space(11)
      anchors.right: parent.right
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(9)

      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(16)
        text: ""
        color: root.svc && root.svc.playing ? Color.accent : Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
      }

      Column {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - Style.space(34)
        spacing: 0

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: root.svc && root.svc.zoneName !== "" ? root.svc.zoneName : "No room"
          elide: Text.ElideRight
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: "Change room"
          color: Color.muted
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }

    MouseArea {
      id: roomHover
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.roomsRequested()
    }
  }
}

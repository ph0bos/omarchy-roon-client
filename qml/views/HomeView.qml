import QtQuick
import qs.Commons
import "../components"
import "../lib/Design.js" as Design
import "../lib/Roond.js" as Roond

// The landing page, built only from what Roon's extension API actually has.
//
// Apple Music and TIDAL open on an algorithmic home -- jump back in, recently
// played, made for you. **None of that is reachable here.** The browse root a
// Roon extension sees is Library, Playlists, My Live Radio, Genres and
// Settings; there is no recently-played list, no recently-added, and no
// ordering other than the Core's own. So this page is what is true instead:
//
//   what is playing, given the top of the page, because on a client you drive
//   from your phone that IS the news;
//   Roon Radio, which is the one thing that decides what happens next;
//   your playlists and genres, which are yours and are not alphabetical noise;
//   and the top of the album shelf, labelled as the top of the album shelf.
//
// A shelf called "Jump back in" filled with albums beginning with a digit is
// the kind of lie an interface never recovers from.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  // Asks the overlay to go somewhere: a hierarchy key, or "nowPlaying".
  signal navigate(string key)
  // Hierarchy plus POSITION: an item_key belongs to the session that made it,
  // and these shelves each browse on their own. The library view re-browses the
  // hierarchy and opens the row at that index, which is the same record.
  signal openItem(string hierarchy, int index)

  readonly property bool hasTrack: svc ? svc.hasTrack : false
  readonly property color accent: svc ? svc.artAccentReadable : Color.accent

  property var albums: []
  property var playlists: []
  property var genres: []

  Component.onCompleted: root.load()

  Connections {
    target: root.svc
    function onDaemonUpChanged() { if (root.svc && root.svc.daemonUp) root.load() }
  }

  // Each shelf browses on its OWN session key. They are separate cursors and
  // must be: three lists sharing one key would each land on whatever the last
  // request left behind.
  function load() {
    root.fetch("albums", "home-albums", function(items) { root.albums = items })
    root.fetch("playlists", "home-playlists", function(items) { root.playlists = items })
    root.fetch("genres", "home-genres", function(items) { root.genres = items })
  }

  function fetch(hierarchy, key, assign) {
    Roond.page({ session_key: key, hierarchy: hierarchy, pop_all: true, count: 24 },
      function(r) {
        if (!r || r.action !== "list") return
        assign(r.items || [])
      },
      function() { assign([]) })
  }

  Flickable {
    anchors.fill: parent
    anchors.leftMargin: Style.space(4)
    anchors.rightMargin: Style.space(10)
    clip: true
    contentHeight: column.implicitHeight + Style.space(20)
    boundsBehavior: Flickable.StopAtBounds

    Column {
      id: column
      width: parent.width
      spacing: Style.space(22)

      // ---- what is playing ----
      Item {
        width: parent.width
        height: Style.space(132)

        RoundedImage {
          id: heroArt
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          width: Style.space(116)
          height: width
          radius: Style.space(5)
          decodeSize: 256
          source: root.svc ? root.svc.artUrl : ""
        }

        Column {
          anchors.left: heroArt.right
          anchors.leftMargin: Style.space(18)
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(4)

          Text {
            textFormat: Text.PlainText
            width: parent.width
            text: root.svc && root.svc.zoneName !== ""
                  ? (root.svc.playing ? "Playing in " + root.svc.zoneName
                                      : "Paused in " + root.svc.zoneName)
                  : "Nothing playing"
            color: Color.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            text: root.hasTrack ? root.svc.title : "Pick something to play"
            elide: Text.ElideRight
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.weight: Font.DemiBold
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            visible: root.hasTrack
            text: root.svc
                  ? root.svc.artist + (root.svc.album !== "" ? "  ·  " + root.svc.album : "")
                  : ""
            elide: Text.ElideRight
            color: root.foreground
            opacity: 0.75
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Row {
            spacing: Style.space(8)
            topPadding: Style.space(6)

            // Open the artwork. The hero is a doorway, not a decoration.
            Rectangle {
              width: openRow.implicitWidth + Style.space(20)
              height: Style.space(26)
              radius: Style.space(3)
              color: openHover.containsMouse
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.20)
                : Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.12)
              Behavior on color { ColorAnimation { duration: Design.fast } }

              Row {
                id: openRow
                anchors.centerIn: parent
                spacing: Style.space(7)

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: "\uf144"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: "Now playing"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                id: openHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.navigate("nowPlaying")
              }
            }

            // Roon Radio: the one control that decides what happens after the
            // queue runs dry, and a property of the ROOM rather than of this
            // client -- turning it on here turns it on for whoever else is
            // listening.
            Rectangle {
              id: radioChip
              readonly property bool on: root.svc ? root.svc.autoRadio : false

              width: radioRow.implicitWidth + Style.space(20)
              height: Style.space(26)
              radius: Style.space(3)
              color: radioHover.containsMouse
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.20)
                : (radioChip.on
                   ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.14)
                   : Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.12))
              Behavior on color { ColorAnimation { duration: Design.fast } }

              Row {
                id: radioRow
                anchors.centerIn: parent
                spacing: Style.space(7)

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: "\uf012"
                  color: radioChip.on ? root.accent : Color.muted
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  textFormat: Text.PlainText
                  anchors.verticalCenter: parent.verticalCenter
                  text: radioChip.on ? "Roon Radio on" : "Roon Radio off"
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              MouseArea {
                id: radioHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { if (root.svc) root.svc.toggleAutoRadio() }
              }
            }
          }
        }
      }

      // ---- your playlists ----
      //
      // A list rather than a shelf: Roon returns no artwork for playlists, and
      // a row of blank tiles is worse than a row of names.
      Column {
        width: parent.width
        spacing: Style.space(6)
        visible: root.playlists.length > 0

        Item {
          width: parent.width
          height: Style.space(22)

          Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Your playlists"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.weight: Font.DemiBold
          }

          Text {
            textFormat: Text.PlainText
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "See all"
            color: allPlaylists.containsMouse ? Color.accent : Color.muted
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption

            MouseArea {
              id: allPlaylists
              anchors.fill: parent
              anchors.margins: -Style.space(6)
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.navigate("playlists")
            }
          }
        }

        Repeater {
          model: root.playlists.slice(0, 5)

          Rectangle {
            id: playlistRow
            required property var modelData
            required property int index

            width: parent.width
            height: Style.space(32)
            radius: Style.space(3)
            color: playlistHover.containsMouse ? Color.menu.selectedBackground : "transparent"
            Behavior on color { ColorAnimation { duration: Design.fast } }

            Text {
              textFormat: Text.PlainText
              anchors.left: parent.left
              anchors.leftMargin: Style.space(10)
              anchors.right: playlistCount.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              text: String(playlistRow.modelData.title || "")
              elide: Text.ElideRight
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              textFormat: Text.PlainText
              id: playlistCount
              anchors.right: parent.right
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              text: String(playlistRow.modelData.subtitle || "")
              color: Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            MouseArea {
              id: playlistHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.openItem("playlists", playlistRow.index)
            }
          }
        }
      }

      // ---- genres ----
      //
      // Chips, because there are twenty of them and they are one word each.
      Column {
        width: parent.width
        spacing: Style.space(8)
        visible: root.genres.length > 0

        Text {
          textFormat: Text.PlainText
          text: "Genres"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.weight: Font.DemiBold
        }

        Flow {
          width: parent.width
          spacing: Style.space(8)

          Repeater {
            model: root.genres.slice(0, 12)

            Rectangle {
              id: chip
              required property var modelData
              required property int index

              width: chipLabel.implicitWidth + Style.space(22)
              height: Style.space(28)
              radius: height / 2
              color: chipHover.containsMouse
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.18)
                : Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.12)
              Behavior on color { ColorAnimation { duration: Design.fast } }

              Text {
                textFormat: Text.PlainText
                id: chipLabel
                anchors.centerIn: parent
                text: String(chip.modelData.title || "")
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              MouseArea {
                id: chipHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openItem("genres", chip.index)
              }
            }
          }
        }
      }

      // ---- the albums, honestly labelled ----
      Shelf {
        width: parent.width
        visible: root.albums.length > 0
        title: "Albums"
        action: "See all"
        items: root.albums
        svc: root.svc
        foreground: root.foreground
        fontFamily: root.fontFamily
        onActioned: root.navigate("albums")
        onOpened: function(index) { root.openItem("albums", index) }
      }
    }
  }
}

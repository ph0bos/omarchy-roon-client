import QtQuick
import qs.Commons

// The actions that are not worth a button of their own: playback modes, Roon
// Radio, notifications, and the rooms.
//
// Rendered inline by whatever hosts it rather than as its own layer-shell
// surface, because a plugin only gets one panel-kind entry point and that is
// already spent on the overlay.
//
// Shuffle, repeat and Roon Radio are properties of the ZONE. Changing one here
// changes it for the room and for whoever is looking at their phone -- so they
// are shown with the room's own state, never with a local guess.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  signal requested(string action)
  signal zoneRequested(string zoneId)

  readonly property bool shuffled: svc ? svc.shuffle : false
  readonly property string loopMode: svc ? svc.loopMode : "disabled"
  readonly property bool autoRadio: svc ? svc.autoRadio : false
  readonly property bool notifications: svc ? svc.notificationsOn : false
  readonly property var zones: svc ? svc.zones : []
  readonly property string pinnedZoneId: svc ? svc.zoneId : ""

  // Roon's "loop_one" said the way a person would.
  readonly property string loopLabel: loopMode === "loop" ? "all"
    : (loopMode === "loop_one" ? "one" : "off")

  readonly property var items: [
    { glyph: "", label: "Now playing", action: "nowPlaying", state: "", on: false },
    { glyph: "", label: "Queue",       action: "queue",      state: "", on: false },
    { glyph: "\uf02d", label: "Library",   action: "library",    state: "", on: false },
    { glyph: "",  label: "",            action: "sep",        state: "", on: false },
    { glyph: "", label: "Shuffle",     action: "shuffle",
      state: root.shuffled ? "on" : "off", on: root.shuffled },
    { glyph: "", label: "Repeat",      action: "repeat",
      state: root.loopLabel, on: root.loopMode !== "disabled" },
    { glyph: "", label: "Roon Radio",  action: "radio",
      state: root.autoRadio ? "on" : "off", on: root.autoRadio },
    { glyph: "",  label: "",            action: "sep",        state: "", on: false },
    { glyph: "", label: "Track notifications", action: "notifications",
      state: root.notifications ? "on" : "off", on: root.notifications },
    { glyph: "", label: "Keyboard shortcuts",  action: "keys", state: "?", on: false }
  ]

  implicitWidth: Style.space(248)
  implicitHeight: column.implicitHeight + Style.space(12)

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: Color.menu.background
    border.width: Math.max(1, Style.space(1))
    border.color: Color.menu.border

    Column {
      id: column
      anchors.top: parent.top
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.topMargin: Style.space(6)
      spacing: 0

      Repeater {
        model: root.items

        Item {
          id: entry
          required property var modelData
          width: column.width
          height: entry.modelData.action === "sep" ? Style.space(9) : Style.space(30)

          Rectangle {
            visible: entry.modelData.action === "sep"
            anchors.centerIn: parent
            width: parent.width - Style.space(20)
            height: Math.max(1, Style.space(1))
            color: Color.menu.border
            opacity: 0.45
          }

          Rectangle {
            visible: entry.modelData.action !== "sep"
            anchors.fill: parent
            anchors.leftMargin: Style.space(5)
            anchors.rightMargin: Style.space(5)
            radius: Style.space(3)
            color: hover.containsMouse ? Color.menu.selectedBackground : "transparent"

            Text {
              textFormat: Text.PlainText
              id: icon
              anchors.left: parent.left
              anchors.leftMargin: Style.space(9)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(16)
              text: entry.modelData.glyph
              color: entry.modelData.on ? Color.accent : Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              textFormat: Text.PlainText
              anchors.left: icon.right
              anchors.leftMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              text: entry.modelData.label
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Text {
              textFormat: Text.PlainText
              anchors.right: parent.right
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              visible: entry.modelData.state !== ""
              text: entry.modelData.state
              color: entry.modelData.on ? Color.accent : Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            MouseArea {
              id: hover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.requested(entry.modelData.action)
            }
          }
        }
      }

      // ---- the rooms ----
      //
      // The pinned zone is what MPRIS, the media keys, the bar and the queue
      // all follow, so switching rooms belongs with the other things that
      // change what this window is about -- not behind a separate surface.
      Item {
        width: column.width
        height: root.zones.length > 0 ? Style.space(9) : 0
        visible: height > 0

        Rectangle {
          anchors.centerIn: parent
          width: parent.width - Style.space(20)
          height: Math.max(1, Style.space(1))
          color: Color.menu.border
          opacity: 0.45
        }
      }

      Text {
        textFormat: Text.PlainText
        visible: root.zones.length > 0
        x: Style.space(14)
        bottomPadding: Style.space(3)
        text: "ROOMS"
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 1.3
      }

      Repeater {
        model: root.zones

        Item {
          id: zoneEntry
          required property var modelData
          width: column.width
          height: Style.space(28)

          readonly property bool pinned: modelData.zone_id === root.pinnedZoneId
          readonly property bool playing: modelData.state === "playing"

          Rectangle {
            anchors.fill: parent
            anchors.leftMargin: Style.space(5)
            anchors.rightMargin: Style.space(5)
            radius: Style.space(3)
            color: zoneHover.containsMouse ? Color.menu.selectedBackground : "transparent"

            Text {
              textFormat: Text.PlainText
              id: pin
              anchors.left: parent.left
              anchors.leftMargin: Style.space(9)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(16)
              // A dot for the room this window is following; a hollow one for
              // a room that is playing to someone else.
              text: zoneEntry.pinned ? "" : (zoneEntry.playing ? "" : "")
              color: zoneEntry.pinned ? Color.accent : Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              textFormat: Text.PlainText
              anchors.left: pin.right
              anchors.leftMargin: Style.space(8)
              anchors.right: parent.right
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              text: zoneEntry.modelData.name
              elide: Text.ElideRight
              color: zoneEntry.pinned ? Color.accent : root.foreground
              opacity: zoneEntry.pinned ? 1.0 : 0.85
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            MouseArea {
              id: zoneHover
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.zoneRequested(zoneEntry.modelData.zone_id)
            }
          }
        }
      }
    }
  }
}

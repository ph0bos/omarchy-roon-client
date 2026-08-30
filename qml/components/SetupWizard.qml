import QtQuick
import Quickshell
import qs.Commons
import "../lib/Design.js" as Design

// First run, without ever opening a terminal.
//
// `omarchy-roon-endpoint doctor` has answered "what is true right now" since R1,
// but only in a terminal -- and the person who most needs it is the person who
// has not opened one. This is the same ladder, computed by the daemon and served
// over `/setup`, with each rung saying what to do about itself: "Approved in
// Roon" on its own is a diagnosis without a treatment.
//
// The rung people get stuck on is approval. An unapproved extension does not
// fail -- registration simply never answers -- so it is drawn as *waiting on
// you*, somewhere else, rather than as an error on this machine. Roon ships no
// interface for Linux at all, which is why that step has to happen on a phone.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  readonly property bool daemonUp: svc ? svc.daemonUp : false
  readonly property string blockedOn: daemonUp ? (svc ? svc.setupBlockedOn : "") : "daemon"

  // The daemon is rung zero, and it is the only one this side has to synthesise:
  // every other rung is computed BY the daemon, so when it is not answering
  // there is no ladder to draw and the reason is the ladder.
  readonly property var rungs: {
    if (root.daemonUp) return svc ? svc.setupRungs : []
    return [{
      key: "daemon",
      title: "The Roon daemon",
      state: "pending",
      detail: svc && svc.lastError !== "" ? svc.lastError
                                          : "Nothing is listening on 127.0.0.1:9821",
      fix: "Run: systemctl --user start omarchy-roond — or "
         + "omarchy-roon-endpoint daemon if it has never been installed."
    }]
  }

  implicitHeight: content.implicitHeight

  function stateGlyph(state) {
    if (state === "ok") return "\uf00c"
    if (state === "blocked") return "\uf0a4"
    return "\uf10c"
  }

  Column {
    id: content
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    spacing: Style.space(14)

    Column {
      width: parent.width
      spacing: Style.space(4)

      Text {
        textFormat: Text.PlainText
        text: "Set up Roon"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.heading
        font.weight: Font.DemiBold
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: root.daemonUp
          ? "Five things stand between this machine and sound in the room. "
            + "They are checked continuously; this page follows along."
          : "The daemon holds the connection to your Core, and it is not "
            + "answering. Nothing else can be checked until it is."
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    // ---- the ladder ----
    Column {
      width: parent.width
      spacing: Style.space(2)

      Repeater {
        model: root.rungs

        Item {
          id: rung
          required property var modelData
          required property int index

          readonly property bool pointed: rung.modelData.key === root.blockedOn
          readonly property bool done: rung.modelData.state === "ok"

          width: content.width
          height: rungColumn.implicitHeight + Style.space(14)

          Rectangle {
            anchors.fill: parent
            radius: Style.space(4)
            // Only the rung being pointed at is lifted off the panel. Marking
            // every unfinished one would make a fresh install look like five
            // separate problems rather than one ladder.
            color: rung.pointed
              ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.08)
              : "transparent"
          }

          Text {
            textFormat: Text.PlainText
            id: mark
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.top: parent.top
            anchors.topMargin: Style.space(8)
            width: Style.space(18)
            text: root.stateGlyph(rung.modelData.state)
            color: rung.done ? Color.accent
                             : (rung.pointed ? root.foreground : Color.muted)
            opacity: rung.done || rung.pointed ? 1.0 : 0.5
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Column {
            id: rungColumn
            anchors.left: mark.right
            anchors.leftMargin: Style.space(8)
            anchors.right: parent.right
            anchors.rightMargin: Style.space(12)
            anchors.top: parent.top
            anchors.topMargin: Style.space(7)
            spacing: Style.space(2)

            Row {
              width: parent.width
              spacing: Style.space(8)

              Text {
                textFormat: Text.PlainText
                text: (rung.index + 1) + ". " + rung.modelData.title
                color: root.foreground
                // Done rungs recede rather than disappear: the ladder is the
                // explanation, and a finished step still says what happened.
                opacity: rung.done ? 0.65 : 1.0
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.weight: rung.pointed ? Font.DemiBold : Font.Normal
              }

              Text {
                textFormat: Text.PlainText
                topPadding: Style.space(3)
                visible: rung.modelData.state === "blocked"
                text: "waiting on you"
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: text !== ""
              wrapMode: Text.WordWrap
              text: String(rung.modelData.detail || "")
              color: Color.muted
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            // The fix, shown only for the rung actually in the way. Five fixes
            // on screen at once is a wall of text; one is an instruction.
            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: rung.pointed
              wrapMode: Text.WordWrap
              topPadding: Style.space(3)
              text: String(rung.modelData.fix || "")
              color: root.foreground
              opacity: 0.9
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }

    Rectangle {
      width: parent.width
      height: Math.max(1, Style.space(1))
      color: Color.menu.border
      opacity: 0.45
    }

    // ---- the terminal, for anyone who wants it ----
    Column {
      width: parent.width
      spacing: Style.space(3)

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Everything above, plus the audio and firewall checks, in one "
            + "read-only command:"
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      Text {
        textFormat: Text.PlainText
        text: "omarchy-roon-endpoint doctor"
        color: Color.accent
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}

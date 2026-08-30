import QtQuick
import qs.Commons
import "../components"
import "../lib/Design.js" as Design

// What is coming next in the pinned room.
//
// The daemon holds one queue subscription, following the pinned zone, so this
// view is a read of state that is already in memory rather than a call to the
// Core. Switching rooms is what changes the list; there is deliberately no
// per-zone queue route, because holding every room's queue to render one of
// them is a copy of the whole house.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  readonly property var items: svc ? svc.queue : []
  readonly property int remaining: svc ? svc.queueRemaining : 0
  readonly property real timeRemaining: svc ? svc.queueTimeRemaining : 0

  // Which row is playing is a guess, and an honest one only because it is
  // cosmetic. Roon's `now_playing` carries three display strings and an image
  // key -- no track id -- so there is nothing to compare a queue item's
  // `queue_item_id` against. Matching the strings is the best available answer;
  // when it is wrong a row is simply un-marked, and nothing else changes.
  //
  // Only the FIRST match is marked. A queue repeats -- a playlist that comes
  // round again, an album played twice -- and marking every row that matches
  // says the same track is playing in four places at once. Roon's queue starts
  // at what is playing, so the first match is the one.
  readonly property int playingIndex: {
    if (!svc || !svc.hasTrack) return -1
    for (var i = 0; i < items.length; i++) {
      if (String(items[i].title || "") === svc.title
          && String(items[i].artist || "") === svc.artist) return i
    }
    return -1
  }

  Item {
    id: header
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(12)
    height: Style.space(28)

    Text {
      textFormat: Text.PlainText
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: "Queue"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.weight: Font.DemiBold
    }

    Text {
      textFormat: Text.PlainText
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      // The counters come from the zone rather than from the list: the
      // subscription is capped at 100 items, so counting rows would report the
      // window rather than the queue.
      text: {
        if (root.remaining <= 0) return ""
        var left = root.remaining + (root.remaining === 1 ? " track" : " tracks")
        return root.timeRemaining > 0
          ? left + "  ·  " + Design.duration(root.timeRemaining) + " left"
          : left
      }
      color: Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  ListView {
    id: list
    anchors.top: header.bottom
    anchors.topMargin: Style.space(4)
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    model: root.items
    cacheBuffer: Style.space(400)

    delegate: QueueRow {
      required property var modelData
      required property int index

      width: list.width
      item: modelData
      rowIndex: index
      artUrl: root.svc ? root.svc.artForKey(modelData.image_key, 80) : ""
      playing: index === root.playingIndex
      foreground: root.foreground
      fontFamily: root.fontFamily
      accent: root.svc ? root.svc.artAccentReadable : Color.accent
      onActivated: {
        if (root.svc) root.svc.playFromHere(modelData.queue_item_id)
      }
    }
  }

  // Empty is three different situations, and saying which one costs nothing.
  Text {
    textFormat: Text.PlainText
    anchors.centerIn: parent
    visible: root.items.length === 0
    horizontalAlignment: Text.AlignHCenter
    text: {
      if (!root.svc || !root.svc.daemonUp) return "The Roon daemon is not answering"
      if (root.svc.zoneName === "") return "No zone to show a queue for"
      return "Nothing queued in " + root.svc.zoneName
    }
    color: Color.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
  }
}

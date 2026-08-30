import QtQuick

// The plugin's mark: a four-bar level meter that moves while audio is playing.
//
// Extracted from the bar widget so the overlay header wears the same mark the
// bar does -- two drawings of "Roon" that drifted apart would read as two
// plugins. Sized by `markHeight` rather than by its box, so it can sit on a
// text baseline without the line box's ascent and descent pushing it around.
//
// No accent, no gradient: every other icon in the bar cluster is a flat
// monochrome glyph, and a coloured one stops reading as part of the set and
// starts reading as a notification. State is carried by motion and weight --
// the bars move while something is playing and sit still, dimmer, when it is
// not, and a struck-through mark means the daemon is not answering.
//
// NOTE: never name a property here `x`, `y`, `width`, `height` or `scale`.
// They are FINAL on QQuickItem, and shadowing one makes the whole widget fail
// to load with nothing but a warning in the journal.
Item {
  id: root

  property real markHeight: 16
  property color color: "#ffffff"
  property bool live: false
  property bool struck: false
  property real dimOpacity: 0.55

  readonly property real span: root.markHeight
  readonly property real barW: Math.max(1, Math.round(span * 0.15))
  readonly property real gap: Math.max(1, Math.round(span * 0.13))
  readonly property real maxH: span * 0.9

  implicitWidth: 4 * barW + 3 * gap
  implicitHeight: span
  width: implicitWidth
  height: implicitHeight

  Row {
    anchors.centerIn: parent
    spacing: root.gap

    Repeater {
      // Four bars, evenly weighted. Five was a bar too many at this size: the
      // gaps closed up and it read as a smear rather than as levels.
      model: [
        { rest: 0.30, peak: 0.58, ms: 700 },
        { rest: 0.58, peak: 0.98, ms: 920 },
        { rest: 0.42, peak: 0.80, ms: 780 },
        { rest: 0.26, peak: 0.52, ms: 1040 }
      ]

      delegate: Rectangle {
        id: barRect
        required property var modelData
        required property int index

        width: root.barW
        height: root.maxH * modelData.rest
        radius: root.barW / 2
        color: root.color
        opacity: (root.live ? 1.0 : root.dimOpacity) * (root.struck ? 0.3 : 1.0)
        anchors.verticalCenter: parent.verticalCenter
        antialiasing: true

        // Each bar at its own tempo and phase, so they never move in lockstep
        // -- the difference between a level meter and a spinner.
        SequentialAnimation on height {
          running: root.live
          loops: Animation.Infinite
          PauseAnimation { duration: barRect.index * 120 }
          NumberAnimation {
            to: root.maxH * barRect.modelData.peak
            duration: barRect.modelData.ms
            easing.type: Easing.InOutSine
          }
          NumberAnimation {
            to: root.maxH * barRect.modelData.rest
            duration: barRect.modelData.ms
            easing.type: Easing.InOutSine
          }
        }

        // Settle rather than snap when playback stops.
        Behavior on height {
          enabled: !root.live
          NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
        }
      }
    }
  }

  // Daemon down: struck through, so "not connected" never reads as merely
  // "nothing playing".
  Rectangle {
    anchors.centerIn: parent
    width: root.span * 0.98
    height: Math.max(1, Math.round(root.span * 0.085))
    radius: height / 2
    color: root.color
    rotation: -45
    visible: root.struck
    opacity: 0.85
    antialiasing: true
  }
}

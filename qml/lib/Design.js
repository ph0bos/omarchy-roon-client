// The plugin's motion and density constants.
//
// Ported from omarchy-tidal, whose surfaces this client's overlay is built
// from. Durations live here rather than as literals at each call site because
// the surfaces animate together: a card lifting under the cursor, a shelf
// fading in, and a queue row taking focus read as one machine only if they move
// at the same speeds. Three steps is the whole vocabulary --
//
//   fast   a state change under the pointer, felt rather than seen
//   base   something appearing or swapping places
//   slow   a whole face of the UI changing
//
// Pure functions and numbers only: no QML imports, so the maths below can be
// exercised without a shell.

var fast = 130
var base = 190
var slow = 280

// How long the arriving half of a transition waits for the leaving half.
//
// When a sleeve shrinks aside and the queue takes its place, moving both at
// once reads as the whole panel wobbling. Letting the object move first and the
// content follow makes it read as one thing making room for another.
var stagger = 110

// Artwork tiles. `cardIdeal` is the width a card wants; a shelf fits as many
// as it can at or above `cardMin` and then shares the remainder out, so cards
// stay on a common grid instead of every shelf picking its own size.
var cardIdeal = 148
var cardMin = 96

// How many cards fit across `width`, given `gutter` between them.
//
// Rounded rather than floored: at 700px the floor rule leaves a 5th card 20px
// short and drops it, wasting the space on four fat tiles. Rounding takes the
// nearer answer and lets the shared remainder absorb the difference, which is
// what keeps a shelf from visibly changing card size as the panel resizes.
function fitCards(width, gutter, ideal) {
  var w = Number(width)
  if (!isFinite(w) || w <= 0) return 0
  var g = Number(gutter) || 0
  var want = Number(ideal) || cardIdeal
  var n = Math.round((w + g) / (want + g))
  if (n < 1) n = 1
  // Never shrink below cardMin: fewer, legible tiles beat a row of stamps.
  while (n > 1 && cardWidth(w, g, n) < cardMin) n = n - 1
  return n
}

// The width one card gets when `count` of them share `width`.
function cardWidth(width, gutter, count) {
  var n = Number(count) || 0
  if (n <= 0) return 0
  var w = Number(width) || 0
  var g = Number(gutter) || 0
  return Math.floor((w - (n - 1) * g) / n)
}

// The width one card gets in a grid whose cells carry their own gutter.
//
// Not the same sum as `cardWidth`. A shelf is a row with spacing, so its
// gutters fall only *between* the cards: n cards and n-1 gaps. A GridView's
// cell is card-plus-gutter, so a row of n cells is n cards and n gaps, with the
// last one falling off the right edge. Feeding a shelf's width to a grid makes
// every row one gutter too wide, GridView fits one fewer column, and a column's
// worth of space sits empty down the right of the page.
function gridCardWidth(width, gutter, count) {
  var n = Number(count) || 0
  if (n <= 0) return 0
  var w = Number(width) || 0
  var g = Number(gutter) || 0
  return Math.max(1, Math.floor((w - n * g) / n))
}

// Elapsed/total as "1:04", the only time format the UI shows.
function clock(seconds) {
  var total = Number(seconds)
  if (!isFinite(total) || total < 0) return "0:00"
  total = Math.floor(total)
  var m = Math.floor(total / 60)
  var s = total % 60
  return m + ":" + (s < 10 ? "0" + s : s)
}

// "48 min left", for a queue's remaining time. Hours once it runs past one,
// because "127 min" is a number to do arithmetic on rather than read.
function duration(seconds) {
  var total = Math.max(0, Math.floor(Number(seconds) || 0))
  var minutes = Math.round(total / 60)
  if (minutes < 60) return minutes + " min"
  var hours = Math.floor(minutes / 60)
  var rest = minutes % 60
  return rest === 0 ? hours + " hr" : hours + " hr " + rest + " min"
}

// ---- contrast ---------------------------------------------------------------
//
// The interface draws over album art, and album art is not under our control:
// a white sleeve lifts a blurred backdrop until muted text vanishes into it.
// These are the WCAG definitions, so "is this readable" can be a measurement
// rather than an opinion. Channels are 0..1, which is what QML colours use.

function _channel(value) {
  return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)
}

// Relative luminance of a QML colour, 0 (black) to 1 (white).
function luminance(color) {
  if (!color) return 0
  return 0.2126 * _channel(color.r) + 0.7152 * _channel(color.g) + 0.0722 * _channel(color.b)
}

// Contrast between two QML colours: 1 (identical) to 21 (black on white).
// WCAG asks 4.5 for body text and 3 for large text or a meaningful graphic.
function contrast(first, second) {
  var a = luminance(first)
  var b = luminance(second)
  return ((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05))
}

// A colour taken from artwork is only worth using if it can be seen against
// what it is drawn on. `minimum` defaults to 3, the threshold WCAG asks of a
// user interface component. The daemon's `/palette` gives us the sleeve's
// colour; this decides whether the interface may actually wear it.
function readableOr(candidate, background, fallback, minimum) {
  if (!candidate) return fallback
  return contrast(candidate, background) >= (minimum || 3) ? candidate : fallback
}

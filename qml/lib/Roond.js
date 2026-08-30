// HTTP client for omarchy-roond.
//
// Quickshell ships no WebSocket module and qt6-websockets is not installed, so
// the daemon's /ws is unreachable from QML. That is less of a loss than it
// sounds: reactive playback state arrives over MPRIS instead, which is
// push-based and costs nothing. What is left for HTTP is the handful of things
// MPRIS has no vocabulary for -- which zone this is, what other zones exist,
// and switching between them.

var BASE = "http://127.0.0.1:9821"
var TIMEOUT_MS = 4000

function request(method, path, body, onOk, onErr) {
  var xhr = new XMLHttpRequest()
  var settled = false

  function fail(msg) {
    if (settled) return
    settled = true
    if (onErr) onErr(msg)
  }

  xhr.onreadystatechange = function() {
    if (xhr.readyState !== XMLHttpRequest.DONE || settled) return
    if (xhr.status === 0) { fail("daemon unreachable"); return }
    var payload = null
    try { payload = JSON.parse(xhr.responseText) } catch (e) { payload = null }
    if (xhr.status >= 400) {
      fail(payload && payload.error ? payload.error : "HTTP " + xhr.status)
      return
    }
    settled = true
    if (onOk) onOk(payload)
  }

  try {
    xhr.open(method, BASE + path)
    if (body) xhr.setRequestHeader("Content-Type", "application/json")
    xhr.timeout = TIMEOUT_MS
    xhr.ontimeout = function() { fail("daemon timed out") }
    xhr.send(body ? JSON.stringify(body) : undefined)
  } catch (e) {
    fail(String(e))
  }
}

function state(onOk, onErr)          { request("GET",  "/state", null, onOk, onErr) }
function palette(key, onOk, onErr)   { request("GET",  "/palette/" + key, null, onOk, onErr) }
function health(onOk, onErr)         { request("GET",  "/health", null, onOk, onErr) }
// The five rungs between a fresh install and sound, computed by the daemon from
// what it already knows. Read-only, and answerable while nothing else works --
// which is exactly when it is needed.
function setup(onOk, onErr)          { request("GET",  "/setup", null, onOk, onErr) }
function pin(zoneId, onOk, onErr)    { request("POST", "/pin", { zone_id: zoneId }, onOk, onErr) }
function mute(outputId, muted, onOk, onErr) {
  request("POST", "/mute", { output_id: outputId, muted: !!muted }, onOk, onErr)
}
function control(zoneId, action, onOk, onErr) {
  request("POST", "/control", { zone_id: zoneId, action: action }, onOk, onErr)
}

// The queue of the zone the daemon is subscribed to, which is always the pinned
// one. Reading it does not reach the Core: the daemon holds a live subscription
// and answers from memory.
function queue(onOk, onErr) { request("GET", "/queue", null, onOk, onErr) }

// Start playback from an item already in the queue. `queue_item_id` is the
// Core's own handle -- there is no "play item n", because a position is not a
// handle when the list edits underneath it.
function playFromHere(queueItemId, onOk, onErr) {
  request("POST", "/play_from_here", { queue_item_id: queueItemId }, onOk, onErr)
}
// Playback modes for one zone: shuffle, loop, auto_radio. Roon keeps these per
// zone rather than per client, so changing one here changes it for the room --
// including for whoever is looking at their phone.
function settings(zoneId, settings, onOk, onErr) {
  var body = { zone_id: zoneId }
  for (var k in settings) body[k] = settings[k]
  request("POST", "/settings", body, onOk, onErr)
}
// One move of the browse cursor and the window it lands on, done as a single
// request: the Core holds a cursor per session key, and a browse and a load
// sent as two requests can be interleaved by anything else browsing. Every
// surface passes its OWN session_key -- two surfaces sharing one yank each
// other around.
function page(body, onOk, onErr) { request("POST", "/page", body, onOk, onErr) }

// Read another window of wherever a cursor already is, WITHOUT moving it.
// Paging must not re-browse: a browse with no item_key is not guaranteed to
// leave the cursor where it was, and re-sending the item_key would push into
// the same item a second time. This is the one place /load is the right verb.
function loadPage(sessionKey, hierarchy, offset, count, onOk, onErr) {
  request("POST", "/load", {
    multi_session_key: sessionKey, hierarchy: hierarchy,
    offset: offset, count: count
  }, onOk, onErr)
}

function notifications(on, onOk, onErr) {
  request("POST", "/notifications", { enabled: on }, onOk, onErr)
}

// Art is served by the Roon Core itself, so QML points Image straight at it and
// Qt's own image cache does the work. `imageBase` comes from /state.
function art(imageBase, key, px) {
  if (!imageBase || !key) return ""
  return imageBase + "/" + key +
         "?scale=fit&width=" + px + "&height=" + px + "&format=image/jpeg"
}

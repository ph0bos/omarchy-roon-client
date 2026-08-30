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
function pin(zoneId, onOk, onErr)    { request("POST", "/pin", { zone_id: zoneId }, onOk, onErr) }
function mute(outputId, muted, onOk, onErr) {
  request("POST", "/mute", { output_id: outputId, muted: !!muted }, onOk, onErr)
}
function control(zoneId, action, onOk, onErr) {
  request("POST", "/control", { zone_id: zoneId, action: action }, onOk, onErr)
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

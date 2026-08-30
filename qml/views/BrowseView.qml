import QtQuick
import qs.Commons
import "../components"
import "../lib/Design.js" as Design
import "../lib/Roond.js" as Roond

// The library: the browse tree, and search over it.
//
// Roon's browse API is a cursor, not a query. The Core holds one position per
// `multi_session_key` and every browse MOVES it, so this view owns exactly one
// key and never shares it -- search runs on its own, because a search that
// yanked the library's cursor sideways is the classic way to break this API.
//
// Paging is deliberately a `/load` rather than another `/page`: reading another
// window must not move the cursor, and re-sending the item_key would push into
// the same item twice.
//
// There is no metadata API behind any of this. An "album page" is a position in
// a server-driven tree, so what looks like a page here is the same list
// machinery one level deeper -- which is also why going back is `pop_levels`
// rather than a remembered URL.
Item {
  id: root

  property var svc: null
  property color foreground: Color.menu.text
  property string fontFamily: Style.font.menuFamily

  // This surface's own cursor. Anything else that browses must pass its own.
  property string sessionKey: "library"
  property string searchKey: "library-search"

  // Where we are: one entry per level pushed into, so the header can say it and
  // Back knows how many levels to pop.
  property var trail: []
  property var items: []
  property var listInfo: null
  property int total: 0
  property bool loading: false
  property bool paging: false
  property string message: ""
  property int selected: 0

  property string query: ""

  // Every move takes a ticket, and only the current ticket may draw. Browse is
  // asynchronous and a Core is not uniformly fast: a slow root load landing
  // after a search -- or a search for "mile" landing after one for "miles" --
  // otherwise paints an answer to a question nobody asked any more. This is
  // that bug's fix, and it was a real one, observed rather than imagined.
  property int serial: 0
  readonly property bool searching: query.trim() !== ""
  // Whether the last thing rendered came from a search, so the flip between
  // tree and results can clear the list exactly once.
  property bool wasSearching: false
  readonly property string activeKey: searching ? root.searchKey : root.sessionKey
  readonly property string activeHierarchy: searching ? "search" : "browse"

  // Artists get round art, records square: the convention every music app uses
  // to separate a person from a thing. Roon does not label rows, but it does
  // title the list they are in.
  readonly property bool peopleHere:
    listInfo && String(listInfo.title || "").toLowerCase().indexOf("artist") === 0

  signal actionMessage(string text, bool isError)

  Component.onCompleted: root.openRoot()

  // ---- moving the cursor ----
  function apply(result, trailEntry, ticket) {
    if (ticket !== undefined && ticket !== root.serial) return
    root.loading = false
    if (!result) return
    if (result.action !== "list") {
      // An action item did something -- played a record, started radio. There
      // is no list to show, so the surface says what the Core said and stays
      // where it is.
      root.message = String(result.message || "")
      root.actionMessage(root.message, !!result.is_error)
      return
    }
    root.message = ""
    root.listInfo = result.list || null
    root.items = result.items || []
    root.total = result.list && result.list.count ? result.list.count : root.items.length
    root.selected = 0
    if (trailEntry !== undefined) root.trail = trailEntry
    list.positionViewAtBeginning()
  }

  function openRoot() {
    var ticket = ++root.serial
    root.loading = true
    Roond.page({ session_key: root.sessionKey, hierarchy: "browse",
                 pop_all: true, count: 100 },
      function(r) { root.apply(r, [], ticket) },
      function(e) { root.fail(e, ticket) })
  }

  function fail(reason, ticket) {
    if (ticket !== root.serial) return
    root.loading = false
    root.message = reason
  }

  function open(item) {
    if (!item) return
    var isAction = String(item.hint || "") === "action"
    var ticket = ++root.serial
    root.loading = true
    var trail = isAction ? undefined
      : root.trail.concat([{ title: String(item.title || "") }])
    Roond.page({ session_key: root.activeKey, hierarchy: root.activeHierarchy,
                 item_key: item.item_key, count: 100 },
      function(r) { root.apply(r, trail, ticket) },
      function(e) { root.fail(e, ticket) })
  }

  function goBack() {
    // Inside a search result, Back means "up one level of these results", not
    // "abandon the search" -- pushing into an album from a search and being
    // thrown back to the library root loses the search you are working in.
    // Only at the top of the results does Back leave searching.
    if (root.trail.length === 0) {
      if (root.searching) root.query = ""
      return
    }
    var ticket = ++root.serial
    root.loading = true
    var trail = root.trail.slice(0, root.trail.length - 1)
    Roond.page({ session_key: root.activeKey, hierarchy: root.activeHierarchy,
                 pop_levels: 1, count: 100 },
      function(r) { root.apply(r, trail, ticket) },
      function(e) { root.fail(e, ticket) })
  }

  // ---- searching ----
  //
  // Two round trips minimum and no typeahead, so it waits for a pause rather
  // than sending a request per keystroke.
  Timer {
    id: debounce
    interval: 350
    onTriggered: root.runSearch()
  }

  onQueryChanged: {
    // Computed here rather than read from `searching`: a binding derived from
    // `query` is not guaranteed to have re-evaluated by the time query's own
    // change handler runs, and on the FIRST keystroke it had not -- so this
    // took the "query is empty" branch and re-loaded the browse root, whose
    // answer then landed on top of the search.
    var typed = String(root.query).trim()
    if (typed !== "") {
      // Clear as soon as the mode flips, not when the answer lands. Roon's
      // search is two round trips and a real Core takes a second or three over
      // it; leaving the tree on screen under a "Search" header for that long
      // reads as though the search had returned the browse root.
      if (!root.wasSearching) {
        root.items = []
        root.listInfo = null
        root.wasSearching = true
      }
      root.loading = true
      debounce.restart()
    } else {
      debounce.stop()
      root.wasSearching = false
      root.openRoot()
    }
  }

  function runSearch() {
    var typed = String(root.query).trim()
    if (typed === "") return
    var ticket = ++root.serial
    root.loading = true
    Roond.page({ session_key: root.searchKey, hierarchy: "search",
                 input: typed, pop_all: true, count: 100 },
      function(r) { root.apply(r, [], ticket) },
      function(e) { root.fail(e, ticket) })
  }

  // ---- paging ----
  function loadMore() {
    if (root.paging || root.items.length >= root.total) return
    var ticket = root.serial
    root.paging = true
    Roond.loadPage(root.activeKey, root.activeHierarchy, root.items.length, 100,
      function(r) {
        root.paging = false
        // Appending a window belonging to a list we have since navigated away
        // from would splice another page's rows into this one.
        if (ticket !== root.serial || !r || !r.items) return
        root.items = root.items.concat(r.items)
      },
      function() { root.paging = false })
  }

  function activateSelected() {
    if (root.selected >= 0 && root.selected < root.items.length)
      root.open(root.items[root.selected])
  }

  function move(delta) {
    if (root.items.length === 0) return
    var next = root.selected + delta
    root.selected = Math.max(0, Math.min(root.items.length - 1, next))
    list.positionViewAtIndex(root.selected, ListView.Contain)
  }

  // Keys the list wants; everything else bubbles to the overlay, which is what
  // keeps Escape and the transport working from in here.
  Keys.onPressed: function(event) {
    if (event.key === Qt.Key_Down) { root.move(1); event.accepted = true }
    else if (event.key === Qt.Key_Up) { root.move(-1); event.accepted = true }
    else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
      root.activateSelected(); event.accepted = true
    } else if (event.key === Qt.Key_Backspace) {
      root.goBack(); event.accepted = true
    } else if (event.key === Qt.Key_Slash) {
      searchField.forceActiveFocus(); event.accepted = true
    }
  }

  // ---- the header: where you are, and the way back ----
  Item {
    id: header
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(10)
    anchors.rightMargin: Style.space(10)
    height: Style.space(32)

    HeaderButton {
      id: backButton
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      glyph: "\uf053"
      tooltip: "Back"
      interactive: root.trail.length > 0 || root.searching
      fontFamily: root.fontFamily
      foreground: root.foreground
      onActivated: root.goBack()
    }

    Text {
      textFormat: Text.PlainText
      anchors.left: backButton.right
      anchors.leftMargin: Style.space(8)
      anchors.right: searchBox.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      elide: Text.ElideRight
      text: {
        // The trail rather than just the title: "Albums › Slow Light" says how
        // you got here, which a server-driven tree otherwise hides. A search is
        // the root of its own trail, so pushing into a result reads
        // "Search › Miles Davis" rather than losing either half.
        var names = root.searching ? ["Search"] : []
        for (var i = 0; i < root.trail.length; i++) names.push(root.trail[i].title)
        if (names.length === 0)
          return root.listInfo ? String(root.listInfo.title || "") : ""
        return names.join("  ›  ")
      }
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.weight: Font.DemiBold
    }

    Text {
      textFormat: Text.PlainText
      anchors.right: searchBox.left
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      visible: root.loading
      text: root.searching ? "Searching…" : "Loading…"
      color: Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    Rectangle {
      id: searchBox
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(230)
      height: Style.space(26)
      radius: Style.space(4)
      color: Color.menu.selectedBackground
      border.width: Math.max(1, Style.space(1))
      border.color: searchField.activeFocus ? Color.accent : Color.menu.border

      Text {
        textFormat: Text.PlainText
        id: searchGlyph
        anchors.left: parent.left
        anchors.leftMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        text: "\uf002"
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      TextInput {
        id: searchField
        anchors.left: searchGlyph.right
        anchors.leftMargin: Style.space(7)
        anchors.right: parent.right
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        clip: true
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        selectByMouse: true
        selectionColor: Color.accent
        onTextChanged: root.query = text
        // Escape leaves the field rather than closing the whole window: the
        // first Escape should get you out of what you are typing in.
        Keys.onEscapePressed: function(event) {
          if (searchField.text !== "") { searchField.text = "" }
          root.forceActiveFocus()
          event.accepted = true
        }
        Keys.onDownPressed: { root.forceActiveFocus(); root.move(0) }
        Keys.onReturnPressed: { root.forceActiveFocus(); root.activateSelected() }

        Text {
          textFormat: Text.PlainText
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          visible: searchField.text === "" && !searchField.activeFocus
          text: "Search your library"
          color: Color.muted
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  // ---- the list ----
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
    currentIndex: root.selected
    // What is on screen during a move is the OLD page. Dimming it says so,
    // rather than letting it read as the answer to what was just asked.
    opacity: root.loading ? 0.4 : 1.0
    Behavior on opacity { NumberAnimation { duration: Design.fast } }

    // A window at a time, asked for when the end comes into view.
    onContentYChanged: {
      if (contentY + height > contentHeight - Style.space(600)) root.loadMore()
    }

    delegate: BrowseRow {
      required property var modelData
      required property int index

      width: list.width
      item: modelData
      selected: index === root.selected
      circular: root.peopleHere
      artUrl: root.svc && modelData.image_key
              ? root.svc.artForKey(modelData.image_key, 80) : ""
      foreground: root.foreground
      fontFamily: root.fontFamily
      onActivated: {
        root.selected = index
        root.open(modelData)
      }
    }
  }

  // ---- what is going on, when it is not a list ----
  Text {
    textFormat: Text.PlainText
    anchors.centerIn: parent
    width: parent.width - Style.space(80)
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.WordWrap
    visible: root.items.length === 0
    text: {
      if (root.loading) return root.searching ? "Searching…" : "Loading…"
      if (root.message !== "") return root.message
      if (root.searching) return "Nothing matched \"" + root.query.trim() + "\""
      return "Nothing here"
    }
    color: Color.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
  }
}

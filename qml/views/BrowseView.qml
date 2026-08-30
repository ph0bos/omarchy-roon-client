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

  // Which of Roon's hierarchies this view is in. The API lets you jump straight
  // into one, which is the difference between reaching the albums in a click
  // and walking Explore -> Library -> Albums to get there.
  property string hierarchy: "browse"

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

  // Search is somewhere you go, not a filter on the page you were reading.
  // Arriving there shows an empty field over a search page rather than the
  // browse tree with a box in the corner, which is what it was before.
  property bool searchMode: false

  // The last few things you looked for, in this session. Not written anywhere:
  // a search history is a listening history, and this one costs nothing to
  // rebuild.
  property var recentSearches: []

  // Two characters before asking. Roon's search is two round trips and a
  // library is large; one letter is a question nobody meant to ask.
  readonly property int minimumQuery: 2

  // Roon titles the list it returns, but only once it has answered. The trail
  // needs a name for where it starts before then.
  readonly property string hierarchyLabel: {
    switch (root.hierarchy) {
      case "albums": return "Albums"
      case "artists": return "Artists"
      case "genres": return "Genres"
      case "composers": return "Composers"
      case "playlists": return "Playlists"
      case "internet_radio": return "Live radio"
      default: return "Explore"
    }
  }

  // Every move takes a ticket, and only the current ticket may draw. Browse is
  // asynchronous and a Core is not uniformly fast: a slow root load landing
  // after a search -- or a search for "mile" landing after one for "miles" --
  // otherwise paints an answer to a question nobody asked any more. This is
  // that bug's fix, and it was a real one, observed rather than imagined.
  property int serial: 0
  readonly property bool searching: query.trim().length >= root.minimumQuery
  // Whether the last thing rendered came from a search, so the flip between
  // tree and results can clear the list exactly once.
  property bool wasSearching: false
  readonly property string activeKey: searching ? root.searchKey : root.sessionKey
  readonly property string activeHierarchy: searching ? "search" : root.hierarchy

  // Artists get round art, records square: the convention every music app uses
  // to separate a person from a thing. Roon does not label rows, but it does
  // title the list they are in.
  readonly property bool peopleHere:
    listInfo && String(listInfo.title || "").toLowerCase().indexOf("artist") === 0

  // A list of records is a wall of covers; a list of menu entries is a list.
  //
  // Decided from the data rather than from the list's title, because the titles
  // are the user's library and come in every language Roon supports: if most
  // rows carry artwork, the artwork is the content and a grid shows more of it
  // per screen. Tracks inside an album carry none -- they inherit the sleeve --
  // so an album's own page stays a list, which is what it should be.
  readonly property bool artShaped: {
    var withArt = 0
    var records = 0
    for (var i = 0; i < root.items.length; i++) {
      var it = root.items[i]
      var hint = String(it.hint || "list")
      // The "Play Album" at the top of a page says nothing about whether the
      // page is a wall of covers, so it does not get a vote.
      if (hint === "action" || hint === "action_list" || hint === "header") continue
      records++
      if (it.image_key) withArt++
    }
    if (records < 5) return false
    return withArt / records > 0.7
  }

  // Columns, and therefore what up and down mean.
  readonly property int columns: Math.max(1,
    Design.fitCards(grid.width, Style.space(14), Style.space(Design.cardIdeal)))

  signal actionMessage(string text, bool isError)

  Component.onCompleted: {
    root.loadedOnce = true
    root.openRoot()
  }

  property bool loadedOnce: false

  // A daemon that went away and came back is a Core we were disconnected from,
  // and every `item_key` on screen belongs to a browse session that no longer
  // exists: the rows still render, and clicking one goes nowhere. Reload the
  // place we are in rather than leaving a page that only looks alive.
  //
  // Found the hard way: with the daemon swapped underneath a running shell, the
  // view happily kept showing the previous Core's albums.
  Connections {
    target: root.svc
    function onDaemonUpChanged() {
      if (!root.svc || !root.svc.daemonUp || !root.loadedOnce) return
      root.trail = []
      root.openRoot()
    }
  }

  // ---- moving the cursor ----
  // A row the home page asked for, by position, to be opened as soon as the
  // hierarchy it belongs to has loaded. Position rather than `item_key` because
  // a key is only valid in the session that produced it, and the home page
  // browses on its own.
  property int pendingIndex: -1

  function openLater(index) { root.pendingIndex = index }

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

    if (root.pendingIndex >= 0) {
      var wanted = root.pendingIndex
      root.pendingIndex = -1
      if (wanted < root.items.length) {
        root.selected = wanted
        root.open(root.items[wanted])
      }
    }
  }

  function openRoot() {
    var ticket = ++root.serial
    root.loading = true
    Roond.page({ session_key: root.sessionKey, hierarchy: root.hierarchy,
                 pop_all: true, count: 100 },
      function(r) { root.apply(r, [], ticket) },
      function(e) { root.fail(e, ticket) })
  }

  // Jump straight into one of Roon's hierarchies, which is what the sidebar
  // does. Leaving a search is part of it: the sidebar is a different place, not
  // a filter on the one you were already in.
  function beginSearch() {
    // Take a ticket first. Arriving at search from elsewhere may have just
    // created this view, whose own first load is already in flight -- and
    // without this its answer lands a moment later and paints a library page
    // under a search header.
    root.serial = root.serial + 1
    root.loading = false
    root.searchMode = true
    root.items = []
    root.listInfo = null
    root.message = ""
    if (root.query !== "") root.query = ""
    root.focusSearch()
  }

  function focusSearch() { searchField.forceActiveFocus() }

  function remember(typed) {
    var next = [typed]
    for (var i = 0; i < root.recentSearches.length && next.length < 6; i++) {
      if (root.recentSearches[i] !== typed) next.push(root.recentSearches[i])
    }
    root.recentSearches = next
  }

  function openHierarchy(name) {
    // Leaving search: the sidebar is a different place, not a filter on this one.
    root.searchMode = false
    root.hierarchy = name
    if (root.query !== "") root.query = ""   // reloads through onQueryChanged
    else root.openRoot()
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
    root.popTo(root.trail.length - 2)
  }

  // Climb back to a named step in the trail. `index` is a position in it;
  // -1 means the hierarchy the trail hangs off.
  function popTo(index) {
    var levels = root.trail.length - 1 - index
    if (levels <= 0) return
    var ticket = ++root.serial
    root.loading = true
    var trail = root.trail.slice(0, index + 1)
    Roond.page({ session_key: root.activeKey, hierarchy: root.activeHierarchy,
                 pop_levels: levels, count: 100 },
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
    if (typed.length > 0 && typed.length < root.minimumQuery) {
      // Typed, but not enough to ask about. Nothing in flight, nothing stale.
      debounce.stop()
      root.loading = false
      root.items = []
      root.listInfo = null
      return
    }
    if (typed.length >= root.minimumQuery) {
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
    } else if (root.searchMode) {
      // Back to an empty search page rather than back to the tree: you are
      // still in search, you have just stopped asking.
      debounce.stop()
      root.wasSearching = false
      root.loading = false
      root.items = []
      root.listInfo = null
    } else {
      debounce.stop()
      root.wasSearching = false
      root.openRoot()
    }
  }

  function runSearch() {
    var typed = String(root.query).trim()
    if (typed.length < root.minimumQuery) return
    root.remember(typed)
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
    if (root.artShaped) grid.positionViewAtIndex(root.selected, GridView.Contain)
    else list.positionViewAtIndex(root.selected, ListView.Contain)
  }

  // Keys the list wants; everything else bubbles to the overlay, which is what
  // keeps Escape and the transport working from in here.
  Keys.onPressed: function(event) {
    // In a grid, down is a row rather than an item, and left and right are
    // navigation rather than transport. The media keys still work globally, so
    // shadowing the arrows here costs nothing and matches what the eye expects.
    var step = root.artShaped ? root.columns : 1
    if (event.key === Qt.Key_Down) { root.move(step); event.accepted = true }
    else if (event.key === Qt.Key_Up) { root.move(-step); event.accepted = true }
    else if (root.artShaped && event.key === Qt.Key_Right) {
      root.move(1); event.accepted = true
    } else if (root.artShaped && event.key === Qt.Key_Left) {
      root.move(-1); event.accepted = true
    }
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

    // The trail rather than just the title: "Albums › Slow Light" says how you
    // got here, which a server-driven tree otherwise hides. Each step back is a
    // click, because a breadcrumb you cannot use is decoration.
    Row {
      id: crumbs
      anchors.left: backButton.right
      anchors.leftMargin: Style.space(8)
      anchors.right: searchBox.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(7)
      clip: true

      // The place the trail starts from: the hierarchy, or the search itself.
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: {
          if (root.searchMode || root.searching) return "Search"
          if (root.trail.length === 0)
            return root.listInfo ? String(root.listInfo.title || "") : ""
          return root.hierarchyLabel
        }
        color: root.trail.length === 0 ? root.foreground
                                       : (rootCrumb.containsMouse ? Color.accent : Color.muted)
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.weight: root.trail.length === 0 ? Font.DemiBold : Font.Normal

        MouseArea {
          id: rootCrumb
          anchors.fill: parent
          hoverEnabled: true
          enabled: root.trail.length > 0
          cursorShape: Qt.PointingHandCursor
          onClicked: root.popTo(-1)
        }
      }

      Repeater {
        model: root.trail

        Row {
          id: crumb
          required property var modelData
          required property int index

          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(7)

          readonly property bool last: crumb.index === root.trail.length - 1

          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            text: "›"
            color: Color.muted
            opacity: 0.7
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            text: String(crumb.modelData.title || "")
            elide: Text.ElideRight
            color: crumb.last ? root.foreground
                              : (step.containsMouse ? Color.accent : Color.muted)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            font.weight: crumb.last ? Font.DemiBold : Font.Normal

            MouseArea {
              id: step
              anchors.fill: parent
              hoverEnabled: true
              enabled: !crumb.last
              cursorShape: Qt.PointingHandCursor
              onClicked: root.popTo(crumb.index)
            }
          }
        }
      }
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

      // Clearing the field is a click, not a held backspace.
      Text {
        textFormat: Text.PlainText
        id: clearButton
        anchors.right: parent.right
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        visible: searchField.text !== ""
        text: "\uf00d"
        color: clearHover.containsMouse ? Color.accent : Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption

        MouseArea {
          id: clearHover
          anchors.fill: parent
          anchors.margins: -Style.space(5)
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: {
            searchField.text = ""
            searchField.forceActiveFocus()
          }
        }
      }

      TextInput {
        id: searchField
        anchors.left: searchGlyph.right
        anchors.leftMargin: Style.space(7)
        anchors.right: clearButton.visible ? clearButton.left : parent.right
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
          // Stays while the field is empty, focused or not: a placeholder that
          // vanishes the moment you click into the box is a label you can only
          // read when you do not need it.
          visible: searchField.text === ""
          text: "Search your library"
          color: Color.muted
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  // ---- the page's own artwork ----
  //
  // Roon puts the cover on the LIST object, not on the rows: an album page's
  // `list.image_key` is the sleeve, an artist page's is their photograph. It is
  // the one thing that makes a position in a tree read as a page, and it costs
  // nothing to show -- the Core is already serving the image.
  Item {
    id: banner
    anchors.top: header.bottom
    anchors.topMargin: Style.space(6)
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: Style.space(12)
    anchors.rightMargin: Style.space(12)
    height: visible ? Style.space(104) : 0
    visible: root.listInfo && root.listInfo.image_key

    RoundedImage {
      id: bannerArt
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(88)
      height: width
      radius: root.peopleHere ? width / 2 : Style.space(5)
      decodeSize: 256
      source: root.svc && root.listInfo && root.listInfo.image_key
              ? root.svc.artForKey(root.listInfo.image_key, 256) : ""
    }

    Column {
      anchors.left: bannerArt.right
      anchors.leftMargin: Style.space(16)
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(3)

      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.listInfo ? String(root.listInfo.title || "") : ""
        elide: Text.ElideRight
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        font.weight: Font.DemiBold
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        visible: text !== ""
        text: root.listInfo ? String(root.listInfo.subtitle || "") : ""
        elide: Text.ElideRight
        color: root.foreground
        opacity: 0.75
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        // Roon's own subtitle is usually the count already ("5 Albums"), so
        // this only speaks when nothing else has.
        visible: !root.listInfo || !root.listInfo.subtitle
        text: root.total === 1 ? "1 item" : root.total + " items"
        color: Color.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  // ---- the list ----
  ListView {
    id: list
    anchors.top: banner.visible ? banner.bottom : header.bottom
    anchors.topMargin: Style.space(4)
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    model: root.artShaped ? [] : root.items
    visible: !root.artShaped
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

  GridView {
    id: grid
    anchors.fill: list
    anchors.leftMargin: Style.space(8)
    anchors.rightMargin: Style.space(8)
    clip: true
    visible: root.artShaped
    boundsBehavior: Flickable.StopAtBounds
    model: root.artShaped ? root.items : []
    currentIndex: root.selected
    opacity: root.loading ? 0.4 : 1.0
    Behavior on opacity { NumberAnimation { duration: Design.fast } }

    // A GridView's cell carries its own gutter, so a row of n cells is n cards
    // and n gaps -- one more gap than a row of cards has. Sizing the cell with
    // the shelf sum is what silently costs a column and leaves a column's worth
    // of space down the right.
    readonly property int gutter: Style.space(14)
    readonly property int cardWidth:
      Design.gridCardWidth(grid.width, grid.gutter, root.columns)

    cellWidth: cardWidth + gutter
    cellHeight: cardWidth + Style.space(46)
    cacheBuffer: Style.space(800)

    onContentYChanged: {
      if (contentY + height > contentHeight - Style.space(600)) root.loadMore()
    }

    delegate: ArtCard {
      required property var modelData
      required property int index

      width: grid.cardWidth
      item: modelData
      selected: index === root.selected
      circular: root.peopleHere
      artUrl: root.svc && modelData.image_key
              ? root.svc.artForKey(modelData.image_key, 320) : ""
      foreground: root.foreground
      fontFamily: root.fontFamily
      onActivated: {
        root.selected = index
        root.open(modelData)
      }
    }
  }

  // ---- the search page, before you have asked it anything ----
  Column {
    anchors.top: header.bottom
    anchors.topMargin: Style.space(40)
    anchors.horizontalCenter: parent.horizontalCenter
    width: Math.min(parent.width - Style.space(80), Style.space(460))
    spacing: Style.space(14)
    visible: root.searchMode && !root.searching && !root.loading
             && root.items.length === 0

    Text {
      textFormat: Text.PlainText
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      text: root.query.length > 0 ? "Keep typing…" : "Search your library"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.weight: Font.DemiBold
    }

    Text {
      textFormat: Text.PlainText
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
      // Saying what comes back is worth two lines: Roon answers a search with
      // a best guess and then a count per category, which is not what most
      // search boxes do and is better than it sounds.
      text: "Roon answers with its best match, then artists, albums, "
          + "composers, tracks and works."
      color: Color.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }

    Flow {
      width: parent.width
      spacing: Style.space(8)
      visible: root.recentSearches.length > 0 && root.query === ""

      Repeater {
        model: root.recentSearches

        Rectangle {
          id: recent
          required property var modelData

          width: recentLabel.implicitWidth + Style.space(22)
          height: Style.space(28)
          radius: height / 2
          color: recentHover.containsMouse
            ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.18)
            : Qt.rgba(Color.muted.r, Color.muted.g, Color.muted.b, 0.12)
          Behavior on color { ColorAnimation { duration: Design.fast } }

          Text {
            textFormat: Text.PlainText
            id: recentLabel
            anchors.centerIn: parent
            text: String(recent.modelData)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          MouseArea {
            id: recentHover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              searchField.text = String(recent.modelData)
              root.focusSearch()
            }
          }
        }
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
    visible: root.items.length === 0 && !(root.searchMode && !root.searching)
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

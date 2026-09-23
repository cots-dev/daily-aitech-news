(function () {
  "use strict";

  var STORAGE_KEY = "daily-aitech-news-bookmarks";

  function loadBookmarks() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch (e) {
      return new Set();
    }
  }

  function saveBookmarks(set) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(set)));
    } catch (e) {
      /* localStorageが使えない環境（プライベートモード等）では何もしない */
    }
  }

  var bookmarks = loadBookmarks();

  function syncButtons() {
    document.querySelectorAll(".bookmark-btn").forEach(function (btn) {
      var on = bookmarks.has(btn.dataset.id);
      btn.textContent = on ? "★" : "☆";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("is-bookmarked", on);
    });
  }

  function toggle(id) {
    if (bookmarks.has(id)) {
      bookmarks.delete(id);
    } else {
      bookmarks.add(id);
    }
    saveBookmarks(bookmarks);
    syncButtons();
    renderBookmarkPanel();
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".bookmark-btn");
    if (!btn) return;
    e.preventDefault();
    toggle(btn.dataset.id);
  });

  function getAllArticles() {
    var el = document.getElementById("all-articles-data");
    if (!el) return [];
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return [];
    }
  }

  function buildArticleLi(a) {
    var li = document.createElement("li");
    var row = document.createElement("div");
    row.className = "article-row";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bookmark-btn is-bookmarked";
    btn.dataset.id = a.id;
    btn.setAttribute("aria-pressed", "true");
    btn.setAttribute("aria-label", "ブックマーク");
    btn.textContent = "★";
    row.appendChild(btn);

    var textDiv = document.createElement("div");
    textDiv.className = "article-text";

    var link = document.createElement("a");
    link.className = "article-link";
    link.href = a.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = a.title_ja || a.title;
    textDiv.appendChild(link);

    var metaParts = [];
    if (a.published_display) metaParts.push(a.published_display);
    if (a.source) metaParts.push(a.source);
    if (a.hashtags && a.hashtags.length) {
      metaParts.push(
        a.hashtags
          .slice(0, 3)
          .map(function (h) {
            return "#" + h;
          })
          .join(" ")
      );
    }
    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaParts.join(" ・ ");
    textDiv.appendChild(meta);

    row.appendChild(textDiv);

    if (a.thumbnail) {
      var thumbLink = document.createElement("a");
      thumbLink.href = a.url;
      thumbLink.target = "_blank";
      thumbLink.rel = "noopener";
      thumbLink.className = "thumb-link";

      var img = document.createElement("img");
      img.className = "article-thumb";
      img.src = a.thumbnail;
      img.alt = "";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("error", function () {
        thumbLink.remove();
      });

      thumbLink.appendChild(img);
      row.appendChild(thumbLink);
    }

    li.appendChild(row);
    return li;
  }

  function renderBookmarkPanel() {
    var panel = document.getElementById("panel-bookmark");
    if (!panel) return;
    var list = panel.querySelector(".article-list");
    if (!list) return;

    var all = getAllArticles();
    var items = all.filter(function (a) {
      return bookmarks.has(a.id);
    });

    list.innerHTML = "";
    if (items.length === 0) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "ブックマークした記事はまだありません";
      list.appendChild(empty);
      return;
    }
    items.forEach(function (a) {
      list.appendChild(buildArticleLi(a));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    syncButtons();
    renderBookmarkPanel();
  });
})();

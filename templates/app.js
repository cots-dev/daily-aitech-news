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

  function makeBadge(className, text) {
    var span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
  }

  function buildArticleLi(a) {
    var li = document.createElement("li");
    var row = document.createElement("div");
    row.className = "article-row";

    var textDiv = document.createElement("div");
    textDiv.className = "article-text";

    if (a.howto || a.is_english) {
      var badges = document.createElement("div");
      badges.className = "badges";
      if (a.howto) badges.appendChild(makeBadge("badge badge-howto", "すぐ試せる"));
      if (a.is_english) badges.appendChild(makeBadge("badge badge-en", "英語・翻訳で開く"));
      textDiv.appendChild(badges);
    }

    var link = document.createElement("a");
    link.className = "article-link";
    link.href = a.open_url || a.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = a.title_ja || a.title;
    textDiv.appendChild(link);

    var metaParts = [];
    if (a.published_display) metaParts.push(a.published_display);
    if (a.source) metaParts.push(a.source);
    var meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = metaParts.join(" ・ ");
    if (a.hashtags && a.hashtags.length) {
      meta.appendChild(document.createTextNode(" ・ "));
      var tags = document.createElement("span");
      tags.className = "hashtags";
      a.hashtags.forEach(function (h, i) {
        if (i > 0) tags.appendChild(document.createTextNode(" "));
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "#" + h;
        tags.appendChild(tag);
      });
      meta.appendChild(tags);
    }
    textDiv.appendChild(meta);

    row.appendChild(textDiv);

    var side = document.createElement("div");
    side.className = "article-side";

    if (a.thumbnail) {
      var thumbLink = document.createElement("a");
      thumbLink.href = a.open_url || a.url;
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
      side.appendChild(thumbLink);
    }

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "bookmark-btn is-bookmarked";
    btn.dataset.id = a.id;
    btn.setAttribute("aria-pressed", "true");
    btn.setAttribute("aria-label", "ブックマーク");
    btn.textContent = "★";
    side.appendChild(btn);

    row.appendChild(side);
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

  var THEME_KEY = "daily-aitech-news-theme";

  function currentTheme() {
    var t = document.documentElement.dataset.theme;
    if (t === "light" || t === "dark") return t;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".theme-toggle")) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (err) {
      /* 保存できない環境では、このページを開いている間だけ切り替える */
    }
  });

  // <details> のメニューは標準では外側を押しても閉じないため補う
  document.addEventListener("click", function (e) {
    document.querySelectorAll(".site-menu[open]").forEach(function (menu) {
      if (!menu.contains(e.target)) menu.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".site-menu[open]").forEach(function (menu) {
      menu.removeAttribute("open");
      menu.querySelector("summary").focus();
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    syncButtons();
    renderBookmarkPanel();
  });
})();

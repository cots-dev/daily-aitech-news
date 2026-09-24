"""data/*.json から docs/ 以下に静的HTMLサイトを生成するスクリプト。

- docs/index.html          … 当日分の一覧（総合＋カテゴリタブ＋ブックマークタブ）
- docs/{about,usage,sources,disclaimer}.html … ヘッダーメニューから辿る案内ページ
- docs/assets/style.css    … カテゴリ数に応じて動的生成するCSS
- docs/assets/app.js       … ブックマーク機能（localStorage）とメニュー開閉
- docs/robots.txt          … 検索エンジンからの発見を避けるための全面Disallow

過去日付ごとのアーカイブページは持たない（ブックマークした記事だけが
日付を問わず「ブックマーク」タブから参照できる）。
"""
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
TEMPLATES_DIR = ROOT / "templates"

# ブックマークタブから遡って参照できる日数（埋め込みJSONの肥大化を防ぐための上限）
BOOKMARK_LOOKBACK_DAYS = 90
MAX_HASHTAGS = 3

INFO_PAGES = [
    {"slug": "about", "label": "当Webページについて"},
    {"slug": "usage", "label": "主な使い方"},
    {"slug": "sources", "label": "出典サイト一覧"},
    {"slug": "disclaimer", "label": "免責事項"},
]

# 「note（ハッシュタグ: プロンプト）」→ 媒体名「note」＋補足「ハッシュタグ: プロンプト」
SOURCE_NAME_RE = re.compile(r"^(.*?)（(.+)）$")
# 補足部分のうち、ハッシュタグとして表示できるもの（タグ名だけを取り出す）
SOURCE_TAG_RE = re.compile(r"^(?:ハッシュタグ|タグ|トピック)[:：]\s*(.+)$")


def load_yaml(name: str):
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def split_source_name(name: str) -> tuple[str, str | None, str | None]:
    """(媒体名, 補足ラベル, 補足から取り出したタグ) を返す。"""
    m = SOURCE_NAME_RE.match(name or "")
    if not m:
        return name, None, None
    base, inner = m.group(1).strip(), m.group(2).strip()
    tag_m = SOURCE_TAG_RE.match(inner)
    return base, inner, (tag_m.group(1).strip() if tag_m else None)


def normalize_for_display(a: dict) -> dict:
    """媒体名から（ハッシュタグ: ○○）等を外し、ハッシュタグを「#○○」表記用に揃える。"""
    base, _, source_tag = split_source_name(a.get("source", ""))
    a["source"] = base

    tags = []
    seen = set()
    for h in (a.get("hashtags") or []) + ([source_tag] if source_tag else []):
        h = re.sub(r"\s+", "", str(h).lstrip("#＃"))
        if h and h.lower() not in seen:
            seen.add(h.lower())
            tags.append(h)
    a["hashtags"] = tags[:MAX_HASHTAGS]
    return a


def load_day(path: Path) -> list:
    articles = [normalize_for_display(a) for a in json.loads(path.read_text(encoding="utf-8"))]
    articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    return articles


def date_with_dow(date: str) -> str:
    dow = datetime.strptime(date, "%Y-%m-%d").strftime("%a").lower()
    return f"{date} ({dow})"


def build_source_groups(sources: list) -> list:
    """出典サイト一覧ページ用に、区分 → 媒体 → フィード の順にまとめる。"""
    groups: dict[str, dict[str, dict]] = {}
    for s in sources:
        if not s.get("enabled", True) or not s.get("url"):
            continue
        base, inner, tag = split_source_name(s["name"])
        sites = groups.setdefault(s.get("group", "その他"), {})
        site = sites.setdefault(base, {"name": base, "feeds": [], "keyword_filter": False})
        site["feeds"].append(
            {"label": f"#{tag}" if tag else inner, "site": s.get("site") or s["url"]}
        )
        site["keyword_filter"] = site["keyword_filter"] or bool(s.get("keyword_filter"))
    return [{"label": label, "sites": list(sites.values())} for label, sites in groups.items()]


def build() -> None:
    categories = load_yaml("categories.yaml").get("categories", [])
    sources = load_yaml("sources.yaml").get("sources", [])

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    style_template = env.get_template("style.css.jinja")

    if (DOCS_DIR / "archive").exists():
        shutil.rmtree(DOCS_DIR / "archive")
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)

    (DOCS_DIR / "assets" / "style.css").write_text(
        style_template.render(categories=categories), encoding="utf-8"
    )
    shutil.copyfile(TEMPLATES_DIR / "app.js", DOCS_DIR / "assets" / "app.js")
    for svg_name in ("network-corner-tl.svg", "network-corner-br.svg"):
        shutil.copyfile(TEMPLATES_DIR / "assets" / svg_name, DOCS_DIR / "assets" / svg_name)
    (DOCS_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    day_files = sorted(DATA_DIR.glob("20*-*-*.json"))
    if not day_files:
        print("[WARN] data/ に日別JSONがまだありません。docs/index.html は生成されません")
        return

    latest_date = day_files[-1].stem
    latest_articles = load_day(day_files[-1])

    cutoff = (datetime.now() - timedelta(days=BOOKMARK_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    all_articles = []
    for f in day_files:
        if f.stem >= cutoff:
            all_articles.extend(load_day(f))
    all_articles.sort(key=lambda a: a.get("published", ""), reverse=True)

    all_articles_json = json.dumps(all_articles, ensure_ascii=False)
    all_articles_json = all_articles_json.replace("</", "<\\/")  # </script> 対策

    common = {
        "date": latest_date,
        "date_display": date_with_dow(latest_date),
        "info_pages": INFO_PAGES,
    }

    html = env.get_template("page.html.jinja").render(
        **common,
        current_page="index",
        articles=latest_articles,
        categories=categories,
        all_articles_json=all_articles_json,
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")

    source_groups = build_source_groups(sources)
    for p in INFO_PAGES:
        html = env.get_template(f"{p['slug']}.html.jinja").render(
            **common,
            current_page=p["slug"],
            page_title=p["label"],
            source_groups=source_groups,
        )
        (DOCS_DIR / f"{p['slug']}.html").write_text(html, encoding="utf-8")

    print(f"ビルド完了: {latest_date}分のページを生成（ブックマーク対象 {len(all_articles)}件）")


if __name__ == "__main__":
    build()

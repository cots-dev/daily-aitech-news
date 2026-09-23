"""data/*.json から docs/ 以下に静的HTMLサイトを生成するスクリプト。

- docs/index.html          … 当日分の一覧（総合＋カテゴリタブ＋ブックマークタブ）
- docs/assets/style.css    … カテゴリ数に応じて動的生成するCSS
- docs/assets/app.js       … ブックマーク機能（localStorage、クライアント側）
- docs/robots.txt          … 検索エンジンからの発見を避けるための全面Disallow

過去日付ごとのアーカイブページは持たない（ブックマークした記事だけが
日付を問わず「ブックマーク」タブから参照できる）。
"""
import json
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


def load_yaml(name: str):
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_day(path: Path) -> list:
    articles = json.loads(path.read_text(encoding="utf-8"))
    articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    return articles


def date_with_dow(date: str) -> str:
    dow = datetime.strptime(date, "%Y-%m-%d").strftime("%a").lower()
    return f"{date} ({dow})"


def build() -> None:
    categories = load_yaml("categories.yaml").get("categories", [])
    prompt_links = [
        link for link in load_yaml("prompt_links.yaml").get("links", []) if link.get("url")
    ]

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    page_template = env.get_template("page.html.jinja")
    style_template = env.get_template("style.css.jinja")

    if (DOCS_DIR / "archive").exists():
        shutil.rmtree(DOCS_DIR / "archive")
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)

    (DOCS_DIR / "assets" / "style.css").write_text(
        style_template.render(categories=categories), encoding="utf-8"
    )
    shutil.copyfile(TEMPLATES_DIR / "app.js", DOCS_DIR / "assets" / "app.js")
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

    html = page_template.render(
        date=latest_date,
        date_display=date_with_dow(latest_date),
        articles=latest_articles,
        categories=categories,
        prompt_links=prompt_links,
        all_articles_json=all_articles_json,
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")

    print(f"ビルド完了: {latest_date}分のページを生成（ブックマーク対象 {len(all_articles)}件）")


if __name__ == "__main__":
    build()

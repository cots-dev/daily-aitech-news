"""data/*.json から docs/ 以下に静的HTMLサイトを生成するスクリプト。

- docs/index.html          … 最新日の一覧（総合＋カテゴリタブ）
- docs/archive/YYYY-MM-DD.html … 日付ごとのアーカイブ
- docs/archive/index.html  … 過去の記事一覧（日付リンク集）
- docs/assets/style.css    … カテゴリ数に応じて動的生成するCSS
- docs/robots.txt          … 検索エンジンからの発見を避けるための全面Disallow
"""
import json
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
TEMPLATES_DIR = ROOT / "templates"


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
    archive_index_template = env.get_template("archive_index.html.jinja")
    style_template = env.get_template("style.css.jinja")

    (DOCS_DIR / "archive").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)

    (DOCS_DIR / "assets" / "style.css").write_text(
        style_template.render(categories=categories), encoding="utf-8"
    )
    (DOCS_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    day_files = sorted(DATA_DIR.glob("20*-*-*.json"))
    all_dates = [f.stem for f in day_files]

    for f in day_files:
        date = f.stem
        articles = load_day(f)
        html = page_template.render(
            date=date,
            date_display=date_with_dow(date),
            articles=articles,
            categories=categories,
            prompt_links=prompt_links,
            css_href="../assets/style.css",
            home_href="../index.html",
            archive_href="index.html",
        )
        (DOCS_DIR / "archive" / f"{date}.html").write_text(html, encoding="utf-8")

    if all_dates:
        latest_date = all_dates[-1]
        latest_articles = load_day(DATA_DIR / f"{latest_date}.json")
        html = page_template.render(
            date=latest_date,
            date_display=date_with_dow(latest_date),
            articles=latest_articles,
            categories=categories,
            prompt_links=prompt_links,
            css_href="assets/style.css",
            home_href="index.html",
            archive_href="archive/index.html",
        )
        (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")
    else:
        print("[WARN] data/ に日別JSONがまだありません。docs/index.html は生成されません")

    (DOCS_DIR / "archive" / "index.html").write_text(
        archive_index_template.render(
            all_dates=[(d, date_with_dow(d)) for d in reversed(all_dates)]
        ),
        encoding="utf-8",
    )

    print(f"ビルド完了: {len(all_dates)}日分のページを生成しました")


if __name__ == "__main__":
    build()

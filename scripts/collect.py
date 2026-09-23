"""RSSソースから新着記事を収集し、Gemini APIでカテゴリタグを付けて
data/YYYY-MM-DD.json に追記するスクリプト。

要約文は生成しない（タイトル・出典・公開日・カテゴリタグのみ）。
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
BATCH_SIZE = 20


def load_yaml(name: str):
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def load_seen() -> set:
    path = DATA_DIR / "seen_urls.json"
    if path.exists():
        return set(json.loads(path.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "seen_urls.json"
    path.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def matches_keywords(text: str, keywords: list) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def collect() -> tuple[list, set]:
    sources = load_yaml("sources.yaml")["sources"]
    keywords = load_yaml("keywords.yaml")["keywords"]
    seen = load_seen()
    new_articles = []

    for src in sources:
        if not src.get("enabled", True) or not src.get("url"):
            continue

        feed = feedparser.parse(src["url"])
        if getattr(feed, "bozo", 0):
            print(
                f"[WARN] フィード取得に問題がある可能性: {src['name']} "
                f"({src['url']}) - {feed.bozo_exception}"
            )
        if not feed.entries:
            print(f"[WARN] 記事0件: {src['name']} ({src['url']})")

        for entry in feed.entries[: src.get("max_items", 15)]:
            url = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not url or not title:
                continue

            h = url_hash(url)
            if h in seen:
                continue

            if src.get("keyword_filter"):
                text = title + " " + (entry.get("summary") or "")
                if not matches_keywords(text, keywords):
                    continue

            published = entry.get("published") or entry.get("updated") or ""

            new_articles.append(
                {
                    "id": h,
                    "title": title,
                    "url": url,
                    "source": src["name"],
                    "published": published,
                }
            )
            seen.add(h)

    return new_articles, seen


def classify_articles(articles: list) -> list:
    """Geminiで各記事にカテゴリタグ（複数可）を付与する。
    GEMINI_API_KEY未設定・エラー時は 'other' にフォールバックする。
    """
    if not articles:
        return articles

    api_key = os.environ.get("GEMINI_API_KEY")
    categories = load_yaml("categories.yaml")["categories"]
    cat_ids = {c["id"] for c in categories}

    if not api_key:
        print("[WARN] GEMINI_API_KEY未設定のため分類をスキップし、'other'を付与します")
        for a in articles:
            a["tags"] = ["other"]
        return articles

    from google import genai

    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    cat_desc = "\n".join(f"- {c['id']}: {c['label']}（{c['description']}）" for c in categories)

    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        titles_block = "\n".join(f"{idx}. {a['title']}" for idx, a in enumerate(batch))
        prompt = f"""以下は生成AI・Microsoft 365関連ニュースのタイトル一覧です。
各記事に、下記カテゴリIDのうち該当するものを全て割り当ててください（複数可）。
どれにも当てはまらない場合は "other" のみを割り当ててください。

カテゴリ一覧:
{cat_desc}

記事一覧:
{titles_block}

出力は次のJSON形式のみを返してください（説明文・コードブロック不要）:
{{"0": ["excel"], "1": ["msofficial", "teams"]}}
"""
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = (resp.text or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
            result = json.loads(text)
            for idx, a in enumerate(batch):
                tags = result.get(str(idx)) or ["other"]
                tags = [t for t in tags if t in cat_ids] or ["other"]
                a["tags"] = tags
        except Exception as e:  # noqa: BLE001 - フォールバックのため広く捕捉
            print(f"[WARN] 分類APIエラー、このバッチは'other'として扱います: {e}")
            for a in batch:
                a["tags"] = ["other"]
        time.sleep(1)  # 無料枠のレート制限対策

    return articles


def main() -> None:
    new_articles, seen = collect()

    if not new_articles:
        print("新着記事なし")
        save_seen(seen)
        return

    new_articles = classify_articles(new_articles)

    today = datetime.now(JST).strftime("%Y-%m-%d")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{today}.json"

    existing = []
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))

    existing.extend(new_articles)
    out_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    save_seen(seen)
    print(f"{len(new_articles)}件を追加しました: {out_path}")


if __name__ == "__main__":
    main()

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


def extract_thumbnail(entry) -> str | None:
    """RSSエントリからサムネイル画像URLをベストエフォートで抽出する。
    見つからない場合はNone（テンプレート側で画像なし表示になる）。
    """
    media_thumb = entry.get("media_thumbnail")
    if media_thumb:
        url = media_thumb[0].get("url")
        if url:
            return url

    media_content = entry.get("media_content")
    if media_content:
        for m in media_content:
            mtype = (m.get("medium") or m.get("type") or "")
            if ("image" in mtype) and m.get("url"):
                return m["url"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and "image" in (link.get("type") or ""):
            return link.get("href")

    html = entry.get("summary") or entry.get("description") or ""
    match = re.search(r'<img[^>]+src="([^"]+)"', html)
    if match:
        return match.group(1)

    return None


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
                    "thumbnail": extract_thumbnail(entry),
                }
            )
            seen.add(h)

    return new_articles, seen


def classify_articles(articles: list) -> list:
    """Geminiで各記事にカテゴリタグ（複数可）と日本語タイトルを付与する。
    GEMINI_API_KEY未設定・エラー時は 'other'・原題のままにフォールバックする。
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
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    cat_desc = "\n".join(f"- {c['id']}: {c['label']}（{c['description']}）" for c in categories)

    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        titles_block = "\n".join(f"{idx}. {a['title']}" for idx, a in enumerate(batch))
        prompt = f"""以下は生成AI・Microsoft 365関連ニュースのタイトル一覧です。
各記事について、次の2つを行ってください。
1. 下記カテゴリIDのうち該当するものを全て割り当てる（複数可）。どれにも当てはまらない場合は "other" のみ。
2. タイトルが日本語以外の場合は自然な日本語に翻訳する。すでに日本語の場合はそのまま返す。

カテゴリ一覧:
{cat_desc}

記事一覧:
{titles_block}

出力は次のJSON形式のみを返してください（説明文・コードブロック不要）:
{{"0": {{"tags": ["excel"], "title_ja": "日本語タイトル"}}, "1": {{"tags": ["msofficial", "teams"], "title_ja": "..."}}}}
"""
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = (resp.text or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
            result = json.loads(text)
            for idx, a in enumerate(batch):
                entry_result = result.get(str(idx)) or {}
                tags = entry_result.get("tags") or ["other"]
                tags = [t for t in tags if t in cat_ids] or ["other"]
                a["tags"] = tags
                title_ja = entry_result.get("title_ja")
                if title_ja:
                    a["title_ja"] = title_ja
        except Exception as e:  # noqa: BLE001 - フォールバックのため広く捕捉
            print(f"[WARN] 分類APIエラー、このバッチは'other'・原題のまま扱います: {e}")
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

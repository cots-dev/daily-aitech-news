"""RSSソースから新着記事を収集し、Gemini APIで分類して data/YYYY-MM-DD.json に追記するスクリプト。

Geminiには次を判定させる（要約文は生成しない）。
- カテゴリ（複数可）・日本語タイトル・ハッシュタグ
- exclude: 会社員が仕事で試せる／知っておくべき内容でなければ true（サイトに掲載しない）
- howto: 手順やプロンプト例など、読んですぐ試せる内容なら true（「すぐ試せる」バッジ）

分類できなかった記事（API無料枠の上限など）は classified が付かないまま保存し、
次回以降の実行で直近 RECLASSIFY_DAYS 日分をまとめて分類し直す。
"""
import calendar
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
# Gemini無料枠はモデルによって1日あたりのリクエスト数上限が厳しい
# （gemini-3.6-flashは20リクエスト/日）。1リクエストあたりの記事数を増やし、
# 通常運用（1日1回のcron実行）でのリクエスト数に余裕を持たせる。
BATCH_SIZE = 40
# 1回の実行で使うリクエスト数の上限（無料枠20回/日のうち、手動実行の余地を残す）
MAX_REQUESTS_PER_RUN = 12
# 未分類の記事を分類し直す対象期間
RECLASSIFY_DAYS = 7
# モデル混雑（503 UNAVAILABLE）時の再試行までの待ち秒数
OVERLOAD_RETRY_WAITS = [20, 60]


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


def format_published(entry) -> tuple[str, str]:
    """(ソート用ISO文字列, 表示用「YYYY/M/D Www」文字列) を返す。
    パース不能な場合は生の文字列をそのまま両方に使う。
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        dt = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc).astimezone(JST)
        return dt.isoformat(), f"{dt.year}/{dt.month}/{dt.day} {dt.strftime('%a')}"
    raw = entry.get("published") or entry.get("updated") or ""
    return raw, raw


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

            published, published_display = format_published(entry)

            new_articles.append(
                {
                    "id": h,
                    "title": title,
                    "url": url,
                    "source": src["name"],
                    "published": published,
                    "published_display": published_display,
                    "thumbnail": extract_thumbnail(entry),
                }
            )
            seen.add(h)

    return new_articles, seen


def call_with_retries(client, model: str, prompt: str, batch_len: int):
    """(状態, 結果JSON, 使ったリクエスト数) を返す。状態は ok / overloaded / quota / error。"""
    used = 0
    for attempt in range(len(OVERLOAD_RETRY_WAITS) + 1):
        used += 1
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            text = (resp.text or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
            return "ok", json.loads(text), used
        except Exception as e:  # noqa: BLE001 - 失敗したバッチは次回に再分類する
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                print(f"[WARN] {model} の無料枠の上限に達しました: {msg[:120]}")
                return "quota", None, used
            if "UNAVAILABLE" in msg or "503" in msg:
                if attempt < len(OVERLOAD_RETRY_WAITS):
                    wait = OVERLOAD_RETRY_WAITS[attempt]
                    print(f"[INFO] {model} が混雑中のため{wait}秒待って再試行します（{attempt + 1}回目）")
                    time.sleep(wait)
                    continue
                print(f"[WARN] {model} の混雑が続いています")
                return "overloaded", None, used
            print(f"[WARN] 分類APIエラー、このバッチ{batch_len}件は次回分類します: {msg[:200]}")
            return "error", None, used
    return "overloaded", None, used


def discover_fallback_models(client, primary: str) -> list:
    """混雑・上限時の切り替え先。GEMINI_FALLBACK_MODELS（カンマ区切り）があればそれを使い、
    なければAPIキーで使えるテキスト用Flash系モデルから選ぶ（混雑しにくいlite版→新しい版の順）。"""
    configured = os.environ.get("GEMINI_FALLBACK_MODELS")
    if configured:
        return [m.strip() for m in configured.split(",") if m.strip() and m.strip() != primary]
    try:
        names = []
        for m in client.models.list():
            name = (m.name or "").split("/")[-1]
            if name == primary or "flash" not in name:
                continue
            if any(x in name for x in ("image", "tts", "audio", "live", "embed", "native")):
                continue
            if "generateContent" not in (m.supported_actions or []):
                continue
            names.append(name)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 利用可能なモデル一覧を取得できませんでした: {e}")
        return []
    names.sort(reverse=True)
    names.sort(key=lambda n: ("lite" not in n, "preview" in n))
    print(f"[INFO] 切り替え候補のモデル: {names[:3]}")
    return names[:3]


def classify_articles(articles: list) -> None:
    """記事リストをその場で分類する。分類できたものだけ classified=True を付ける。"""
    if not articles:
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[WARN] GEMINI_API_KEY未設定のため分類をスキップします（次回以降に再分類）")
        return

    from google import genai

    categories = load_yaml("categories.yaml")["categories"]
    cat_ids = {c["id"] for c in categories}
    cat_desc = "\n".join(f"- {c['id']}: {c['label']}（{c['description']}）" for c in categories)

    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    requests = 0
    fallbacks = None  # 混雑時に初めて問い合わせる
    for i in range(0, len(articles), BATCH_SIZE):
        if requests >= MAX_REQUESTS_PER_RUN:
            print(f"[INFO] 1回あたりのリクエスト上限に達したため、残り{len(articles) - i}件は次回分類します")
            break
        batch = articles[i : i + BATCH_SIZE]
        titles_block = "\n".join(
            f"{idx}. [{a.get('source', '')}] {a['title']}" for idx, a in enumerate(batch)
        )
        prompt = f"""あなたは、Windows環境でOffice（Microsoft 365）を使う日本の会社員向けに、
AI・Office・Windowsの情報を届けるニュースサイトの編集者です。
以下の記事一覧（[媒体名] タイトル）について、それぞれ次を判定してください。

1. exclude: 読者が「仕事で試してみたい」「知っておくべき」と思える記事でなければ true。
   例: 個人の日記・雑談・挨拶や近況報告、エンジニア向けのプログラミング・開発・インフラの記事、
   PC・スマホなどハードウェア製品の紹介やレビュー、セール・キャンペーン情報、
   AI・Office・Windowsと関係の薄い記事。迷う場合は false。
2. tags: 下記カテゴリIDのうち該当するものを全て（複数可）。exclude が true なら空配列。
3. howto: 操作手順・設定方法・関数の使い方・プロンプト例など、読んですぐ自分で試せる具体的な内容なら true。
4. title_ja: タイトルが日本語以外なら自然な日本語に翻訳。日本語ならそのまま。
5. hashtags: 記事の内容を端的に表すハッシュタグを2〜3個（例: Excel, Copilot, プロンプト, Windows11）。
   #記号やスペースは付けない。製品名・機能名・トピック名を優先する。

カテゴリ一覧:
{cat_desc}

記事一覧:
{titles_block}

出力は次のJSON形式のみを返してください（説明文・コードブロック不要）:
{{"0": {{"exclude": false, "tags": ["office"], "howto": true, "title_ja": "日本語タイトル", "hashtags": ["Excel", "関数"]}}, "1": {{"exclude": true, "tags": [], "howto": false, "title_ja": "...", "hashtags": []}}}}
"""
        result = None
        while result is None:
            status, result, used = call_with_retries(client, model, prompt, len(batch))
            requests += used
            if status in ("overloaded", "quota"):
                if fallbacks is None:
                    fallbacks = discover_fallback_models(client, model)
                if not fallbacks:
                    print("[WARN] 切り替え先のモデルがないため、今回の分類を打ち切ります（次回に再分類）")
                    return
                reason = "混雑" if status == "overloaded" else "無料枠の上限"
                next_model = fallbacks.pop(0)
                print(f"[INFO] {model} が{reason}のため {next_model} に切り替えて分類します")
                model = next_model
                continue
            break
        if result is None:
            continue

        for idx, a in enumerate(batch):
            r = result.get(str(idx))
            if not isinstance(r, dict):
                continue
            a["excluded"] = bool(r.get("exclude"))
            a["tags"] = [t for t in (r.get("tags") or []) if t in cat_ids]
            a["howto"] = bool(r.get("howto"))
            if r.get("title_ja"):
                a["title_ja"] = r["title_ja"]
            a["hashtags"] = [
                re.sub(r"\s+", "", str(h).lstrip("#")) for h in (r.get("hashtags") or []) if str(h).strip()
            ][:3]
            # カテゴリが1つも付かない記事は掲載しても行き場がないため除外扱いにする
            if not a["tags"]:
                a["excluded"] = True
            a["classified"] = True
        time.sleep(1)  # 無料枠のレート制限対策


def load_recent_days(today: str) -> dict:
    """直近 RECLASSIFY_DAYS 日分の {Path: 記事リスト}（新しい日付順）。"""
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=RECLASSIFY_DAYS)).strftime("%Y-%m-%d")
    days = {}
    for f in sorted(DATA_DIR.glob("20*-*-*.json"), reverse=True):
        if f.stem >= cutoff:
            days[f] = json.loads(f.read_text(encoding="utf-8"))
    return days


def main() -> None:
    new_articles, seen = collect()

    today = datetime.now(JST).strftime("%Y-%m-%d")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    days = load_recent_days(today)
    today_path = DATA_DIR / f"{today}.json"
    days.setdefault(today_path, []).extend(new_articles)

    # 当日の新着を優先し、その後に過去の未分類分（新しい日付順）を分類する
    new_ids = {id(a) for a in new_articles}
    pending = new_articles + [
        a for arts in days.values() for a in arts if not a.get("classified") and id(a) not in new_ids
    ]
    print(f"新着{len(new_articles)}件 / 分類対象{len(pending)}件")
    classify_articles(pending)

    for path, arts in days.items():
        if arts:
            path.write_text(json.dumps(arts, ensure_ascii=False, indent=2), encoding="utf-8")
    save_seen(seen)

    done = sum(1 for a in pending if a.get("classified"))
    excluded = sum(1 for a in pending if a.get("excluded"))
    print(f"分類完了{done}件（うち掲載対象外{excluded}件）/ 未分類のまま{len(pending) - done}件")


if __name__ == "__main__":
    main()

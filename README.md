# daily-aitech-news

Copilot / M365 / 生成AI関連のニュースを毎朝自動収集し、タイトル一覧＋カテゴリタブで表示する
無料運用の静的サイトです。仕様の背景は Obsidian Vault 側の
`03_Stock/Ideas/AIニュースダイジェスト_要件定義.md` を参照してください。

## 仕組み

```
GitHub Actions（毎朝 cron）
  → scripts/collect.py   … RSS収集 + 重複除外 + キーワードフィルタ
  → Gemini API            … カテゴリ分類・掲載可否（仕事で試せる内容か）・「すぐ試せる」判定（要約はしない）
  → scripts/build_site.py … 静的HTMLを生成
  → docs/ にコミット・push
  → GitHub Pages が docs/ を公開
```

- 要約文は生成しません。タイトルを押すと元記事に遷移する、はてなブックマーク風の一覧です。
- 既読/未読はブラウザの `:visited` 機能で判定します（JS・サーバー管理なし）。
  端末・ブラウザをまたぐと未読表示に戻ります。
- タブは記事内容ベースで分類します（ニュース／AI活用／Office Tips／Windows Tips。1記事が複数タブに該当してOK）。
  どのタブにも当てはまらない記事や、個人の日記・エンジニア向け記事・製品レビューなどは掲載しません。
- 利用者は日本語話者のため、収集先は原則日本語サイトに限定しています。英語記事が混ざった場合は
  「英語・翻訳で開く」バッジを付け、Google翻訳経由のリンクで開きます。
- Gemini APIの上限などで分類できなかった記事は未分類のまま保存し、次回以降の実行で
  直近7日分を自動で分類し直します（1回あたり最大12リクエスト）。
- 日付ごとのアーカイブページは持ちません（当日分のみ表示）。代わりに記事をブックマークでき、
  ブックマークした記事は日付を問わず「ブックマーク」タブから見返せます
  （`localStorage`ベース。既読/未読と同様、端末・ブラウザをまたいでは同期されません）。

## セットアップ手順

### 1. Gemini APIキーを取得する
1. [Google AI Studio](https://aistudio.google.com/) にアクセスし、無料のAPIキーを発行する
2. このリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で
   `GEMINI_API_KEY` という名前で登録する

キー未設定の間は、分類がスキップされ全記事が「その他」タブに入ります（サイト自体は動きます）。

**注意（無料枠の1日あたりリクエスト上限）**：Gemini無料枠はモデルによって
1日あたりのリクエスト数上限が厳しい場合がある（`gemini-3.6-flash`は実測20リクエスト/日）。
`scripts/collect.py`は1リクエストで最大40記事をまとめて分類し、1回の実行で最大12リクエストまでに抑えている。
上限に達して分類できなかった記事は未分類のまま保存され、翌日以降の実行で自動的に分類し直されるため、
手作業でデータを消して再実行する必要はない（分類されるまでは「総合」タブにのみ表示される）。

### 2. GitHub Pagesを有効化する
**Settings → Pages** で以下を設定する。

- Source: `Deploy from a branch`
- Branch: `main` / フォルダ: `/docs`

### 3. 初回実行
**Actions → Daily update → Run workflow** で手動実行し、`docs/index.html` が生成されることを確認する。
以降は毎朝自動実行される（cronは `.github/workflows/daily.yml` で調整可能）。

## ディレクトリ構成

```
config/
  sources.yaml       … RSS収集元の一覧（enabled: false のものは未検証・要確認）
  categories.yaml     … 表示タブの一覧（分類プロンプトにもそのまま使う）
  keywords.yaml        … 一般メディア（窓の杜・ASCII.jp・はてブ）向けのAI/Office関連キーワード
scripts/
  collect.py           … RSS収集・重複除外・Gemini分類
  build_site.py        … data/*.json から docs/ 以下のHTMLを生成
  generate_network_bg.py … 背景のコネクター柄SVG（templates/assets/）を生成する一度きりのツール
templates/
  base.html.jinja       … 全ページ共通の枠（ヘッダー・メニュー・フッター）
  page.html.jinja       … 当日ページ（総合＋カテゴリタブ＋ブックマークタブ）
  info_base.html.jinja  … メニューから辿る案内ページの共通枠（TOPへ戻る導線つき）
  about / usage / sources / disclaimer.html.jinja … 案内ページ本文（出典一覧は sources.yaml から自動生成）
  style.css.jinja       … 見た目一式（カテゴリ数に応じて動的生成）
  app.js                … ブックマークの追加/解除・一覧表示（localStorage）とメニュー開閉
  assets/               … 背景のコネクター柄SVG
data/
  YYYY-MM-DD.json       … 収集済み記事のアーカイブ（タグ付き）
  seen_urls.json        … 重複収集を防ぐための既収集URL一覧
docs/                  … GitHub Pagesの公開対象（ビルド成果物）
```

## ソースの追加・修正

`config/sources.yaml` に1件追加するだけで収集対象を増やせる。

```yaml
- name: ソース表示名        # 「媒体名（ハッシュタグ: ○○）」形式なら記事一覧では #○○ として表示
  url: https://example.com/feed
  site: https://example.com/  # 出典サイト一覧ページからのリンク先
  group: 現場・即戦力ノウハウ   # 出典サイト一覧ページでの区分
  enabled: true
  keyword_filter: false   # true にすると config/keywords.yaml のキーワードでフィルタする
  max_items: 15
```

### 未検証・要確認のソース（要件定義の未決事項に対応）

以下は仕様上リクエストされたが、実装時点でRSS URLを確認できなかったもの。
`config/sources.yaml` 内で `enabled: false` にしてコメントを付けてあるので、
URLが判明次第 `enabled: true` にして修正すること。

- Microsoft AI Blog / Copilot Blog（公式RSSが見つからず。Tech Communityの該当ボードIDを要確認）
- Tech Community (M365)（対象ボードID・フィルタ条件が未確定）
- Promptn AI（サイトの実在・RSS配信の有無が未確認）
- ASCII.jp AI関連（AI専用RSSが見つからず、サイト全体RSS + キーワードフィルタで代用中）

初回のAction実行ログで「フィード取得失敗の可能性」が出たソースも合わせて確認する。

## ローカルでのテスト

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=xxxx   # 未設定でも動く（分類はスキップされる）
python scripts/collect.py
python scripts/build_site.py
python -m http.server -d docs 8000   # http://localhost:8000 で確認
```

"""アプリアイコン・ファビコンを生成するスクリプト。

元画像（design/ に保存したデザイン案）から、角丸の紺色アイコン部分を切り出して
各サイズのPNG/ICOを作る一度きりの生成ツール。
  - design/icon-source-app.webp     … 文字入り。スマホのホーム画面用アイコン
  - design/icon-source-favicon.webp … 文字なし。ブラウザのタブ用ファビコン

出力先: templates/assets/icons/
build_site.py がそれを docs/ にコピーして使う（Pillowは生成時のみ必要）。

再生成したい場合は: pip install Pillow && python scripts/generate_icons.py
"""
import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
DESIGN_DIR = ROOT / "design"
OUT_DIR = ROOT / "templates" / "assets" / "icons"

# 元画像の背景（白〜薄いグレー）とみなす明るさ（RGBの合計）
LIGHT_SUM = 600
# 角の縁にある白っぽいにじみを避けるため、アイコンの縁からこの幅（px）は使わない
EDGE_INSET = 6


def find_icon_box(im):
    """白背景の中から、角丸アイコン本体の外接矩形を求める（下の説明文などは除く）。"""
    w, h = im.size
    px = im.load()

    def dark(x, y):
        return sum(px[x, y]) < LIGHT_SUM

    rows = [sum(dark(x, y) for x in range(w)) for y in range(h)]
    cols = [sum(dark(x, y) for y in range(h)) for x in range(w)]
    ys = [y for y, c in enumerate(rows) if c > w * 0.4]
    xs = [x for x, c in enumerate(cols) if c > h * 0.4]
    # 縁のにじみも背景として判定できるよう、少し外側（背景の白）まで含めて切り出す
    m = EDGE_INSET + 4
    return xs[0] - m, ys[0] - m, xs[-1] + 1 + m, ys[-1] + 1 + m


def square_icon(path):
    """角丸アイコンを切り出し、角の外側の白を内側の色で埋めた正方形の画像にする。

    iOS/Androidはアイコンを自前で角丸・円形に切り抜くため、元から角丸だと
    白いすき間が見えてしまう。縦横が少し違う場合も、正方形になるよう
    はみ出た部分を同じ方法で埋める。戻り値の2つ目は元デザインの角丸の半径（辺に対する比率）。
    """
    im = Image.open(path).convert("RGB")
    icon = im.crop(find_icon_box(im))
    w, h = icon.size
    size = max(w, h)
    ox, oy = (size - w) // 2, (size - h) // 2
    src = icon.load()

    # 切り出した範囲の外周から、明るい（背景の）画素を塗りつぶしでたどる
    outside = [[False] * w for _ in range(h)]
    queue = deque()
    for x in range(w):
        queue.extend([(x, 0), (x, h - 1)])
    for y in range(h):
        queue.extend([(0, y), (w - 1, y)])
    while queue:
        x, y = queue.popleft()
        if not (0 <= x < w and 0 <= y < h) or outside[y][x] or sum(src[x, y]) < LIGHT_SUM:
            continue
        outside[y][x] = True
        queue.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])

    # 角丸の半径：左上の角から対角線上にアイコンが始まるまでの距離 t = r(1 - 1/√2)
    t = next(i for i in range(min(w, h)) if not outside[i][i])
    radius_ratio = t / (1 - 1 / math.sqrt(2)) / size

    # 背景から EDGE_INSET 以内の画素は「未確定」として扱う
    unknown = [[outside[y][x] for x in range(w)] for y in range(h)]
    frontier = deque((x, y, 0) for y in range(h) for x in range(w) if outside[y][x])
    while frontier:
        x, y, d = frontier.popleft()
        if d >= EDGE_INSET:
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not unknown[ny][nx]:
                unknown[ny][nx] = True
                frontier.append((nx, ny, d + 1))

    # 確定した画素から外へ向かって、いちばん近い確定画素の色で埋めていく
    out = Image.new("RGB", (size, size))
    dst = out.load()
    filled = [[False] * size for _ in range(size)]
    queue = deque()
    for y in range(h):
        for x in range(w):
            if not unknown[y][x]:
                dst[x + ox, y + oy] = src[x, y]
                filled[y + oy][x + ox] = True
                queue.append((x + ox, y + oy))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < size and 0 <= ny < size and not filled[ny][nx]:
                filled[ny][nx] = True
                dst[nx, ny] = dst[x, y]
                queue.append((nx, ny))

    # 埋めた部分は色を引き伸ばしただけで筋が出るため、ぼかしてなじませる
    known = Image.new("L", (size, size), 0)
    kp = known.load()
    for y in range(h):
        for x in range(w):
            if not unknown[y][x]:
                kp[x + ox, y + oy] = 255
    known = known.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(3))
    blurred = out.filter(ImageFilter.GaussianBlur(10))
    return Image.composite(out, blurred, known), radius_ratio


def rounded(icon, size, radius_ratio):
    """ブラウザのタブ等で使う、角を透明にした角丸版。"""
    big = icon.resize((size * 4, size * 4), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big.width - 1, big.height - 1), radius=round(big.width * radius_ratio), fill=255
    )
    big.putalpha(mask)
    return big.resize((size, size), Image.LANCZOS)


def maskable(icon, size, scale=0.74):
    """Androidの円形などの切り抜きでも文字が欠けないよう、縮小して余白を背景色で埋めた版。"""
    inner = icon.resize((round(size * scale),) * 2, Image.LANCZOS)
    # 余白は、縮小したアイコンの外周のうち暗い（線や丸のない）画素の平均色で塗る
    iw = inner.width
    edge = [inner.getpixel((i, j)) for i in range(iw) for j in (0, iw - 1)]
    edge += [inner.getpixel((j, i)) for i in range(iw) for j in (0, iw - 1)]
    edge = [c for c in edge if sum(c) < 150]
    bg = tuple(sum(c[k] for c in edge) // len(edge) for k in range(3))
    out = Image.new("RGB", (size, size), bg)
    # 境目が見えないよう、外周を少しずつ背景色になじませて重ねる
    feather = round(iw * 0.04)
    mask = Image.new("L", inner.size, 0)
    draw = ImageDraw.Draw(mask)
    for i in range(feather):
        draw.rectangle((i, i, iw - 1 - i, iw - 1 - i), fill=round(255 * (i + 1) / feather))
    off = (size - iw) // 2
    out.paste(inner, (off, off), mask)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app, app_radius = square_icon(DESIGN_DIR / "icon-source-app.webp")
    # iOSのホーム画面（角丸はiOS側でかかるので四角のまま）
    app.resize((180, 180), Image.LANCZOS).save(OUT_DIR / "apple-touch-icon.png", optimize=True)
    # Android / PWA（通常版は元デザインどおりの角丸、maskable版は余白つき）
    for size in (192, 512):
        rounded(app, size, app_radius).save(OUT_DIR / f"icon-{size}.png", optimize=True)
    maskable(app, 512).save(OUT_DIR / "icon-maskable-512.png", optimize=True)

    fav, fav_radius = square_icon(DESIGN_DIR / "icon-source-favicon.webp")
    rounded(fav, 32, fav_radius).save(OUT_DIR / "favicon-32.png", optimize=True)
    rounded(fav, 256, fav_radius).save(
        OUT_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]
    )
    print(f"アイコンを {OUT_DIR} に出力しました")


if __name__ == "__main__":
    main()

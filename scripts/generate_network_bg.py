"""背景装飾用のネットワーク（コネクター）柄SVGを生成するスクリプト。

デザイン要望「情報同士がコネクターでつながっているイメージ」を、
配布不可のストック素材ではなくオリジナルのSVGとして再現するための
一度きりの生成ツール。左上・右下それぞれ独立したSVGとして出力し、
画面の角に固定表示することで、画面の縦横比やスクロール位置によらず
常にコーナーの装飾として見えるようにしている（1枚絵を cover で
引き伸ばすと、縦長のスマホ画面では肝心のクラスタ部分が中央寄せの
クロップで消えてしまうため）。

出力先: templates/assets/network-corner-tl.svg / network-corner-br.svg
build_site.py がそれを docs/assets/ にコピーして使う。

再生成したい場合は: python scripts/generate_network_bg.py
"""
import math
import random

OUT_DIR = "templates/assets"

# ブルー系トーン（ページのアクセントカラーに合わせる）
DARK = "#1d4ed8"
MID = "#3b82f6"
LIGHT = "#93c5fd"
PALE = "#dbeafe"


def cluster(cx, cy, spread, n, rng):
    pts = []
    for _ in range(n):
        ang = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, spread) * rng.uniform(0.3, 1.0)
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return pts


def connections(pts, max_dist, max_links, rng):
    edges = []
    for i, (x1, y1) in enumerate(pts):
        dists = []
        for j, (x2, y2) in enumerate(pts):
            if i == j:
                continue
            d = math.hypot(x1 - x2, y1 - y2)
            if d <= max_dist:
                dists.append((d, j))
        dists.sort()
        for _, j in dists[: rng.randint(1, max_links)]:
            edges.append((i, j))
    return edges


def render(pts, edges, node_color, line_color, node_r, line_opacity, node_opacity, rng):
    parts = []
    for (i, j) in edges:
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{line_color}" stroke-width="1.4" stroke-opacity="{line_opacity}"/>'
        )
    for (x, y) in pts:
        r = node_r * rng.uniform(0.6, 1.6)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            f'fill="{node_color}" fill-opacity="{node_opacity}"/>'
        )
    return "\n".join(parts)


def build_svg(w, h, cx, cy, spread, n, dense) -> str:
    rng = random.Random(7 if not dense else 42)
    parts = []

    main = cluster(cx, cy, spread, n, rng)
    main_edges = connections(main, spread * 0.4, 3 if dense else 2, rng)
    parts.append(render(main, main_edges, DARK, MID, 5 if dense else 4, 0.7, 0.95, rng))

    sub = cluster(cx, cy, spread * 0.75, int(n * 0.4), rng)
    sub_edges = connections(sub, spread * 0.3, 2, rng)
    parts.append(render(sub, sub_edges, MID, LIGHT, 4, 0.5, 0.8, rng))

    scatter = cluster(cx, cy, spread * 1.3, int(n * 0.25), rng)
    parts.append(render(scatter, [], LIGHT, LIGHT, 3, 0, 0.55, rng))

    body = "\n".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}">\n{body}\n</svg>\n'
    )


def main() -> None:
    tl = build_svg(w=620, h=520, cx=110, cy=90, spread=340, n=38, dense=False)
    with open(f"{OUT_DIR}/network-corner-tl.svg", "w", encoding="utf-8") as f:
        f.write(tl)

    br = build_svg(w=760, h=640, cx=620, cy=520, spread=400, n=48, dense=True)
    with open(f"{OUT_DIR}/network-corner-br.svg", "w", encoding="utf-8") as f:
        f.write(br)

    print(f"生成完了: {OUT_DIR}/network-corner-tl.svg, {OUT_DIR}/network-corner-br.svg")


if __name__ == "__main__":
    main()

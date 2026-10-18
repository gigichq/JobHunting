"""纯 Python 七轴雷达图 → inline SVG（02-技术设计 §10）。

网格 #dfe5f2；数据多边形 #ff6b35（22% 透明填充 + 描边 + 顶点圆点）；
4 分线为虚线七边形；待核实轴置灰。无 JS 依赖，打印可用。
"""
import math

CX, CY, R = 210.0, 150.0, 100.0
GRID = "#dfe5f2"
GRID_DASH = "#9fb0d8"
ORANGE = "#ff6b35"
GREY = "#b4bccb"
TEXT = "#1a1a2e"


def _point(axis_index: int, value: float, n: int = 7) -> tuple[float, float]:
    angle = -math.pi / 2 + axis_index * 2 * math.pi / n
    r = R * value / 7.0
    return (round(CX + r * math.cos(angle), 1), round(CY + r * math.sin(angle), 1))


def _ring(value: float, n: int = 7) -> str:
    return " ".join(f"{x},{y}" for x, y in (_point(i, value, n) for i in range(n)))


def _label_anchor(x: float) -> str:
    if abs(x - CX) < 8:
        return "middle"
    return "start" if x > CX else "end"


def render_radar_svg(dims: list[dict]) -> str:
    """dims: [{short, score(int|None), pending(bool)}] 按维度顺序，长度 7。"""
    n = len(dims)
    rings = [
        f'<polygon points="{_ring(7, n)}" fill="none" stroke="{GRID}" stroke-width="1"/>',
        f'<polygon points="{_ring(4, n)}" fill="none" stroke="{GRID_DASH}" stroke-width="1.2" stroke-dasharray="4 3"/>',
        f'<polygon points="{_ring(2, n)}" fill="none" stroke="{GRID}" stroke-width="1"/>',
    ]
    axes = []
    for i, d in enumerate(dims):
        x, y = _point(i, 7, n)
        color = GREY if d.get("pending") else GRID
        axes.append(
            f'<line x1="{CX}" y1="{CY}" x2="{x}" y2="{y}" stroke="{color}" stroke-width="1"/>'
        )

    pts, dots = [], []
    for i, d in enumerate(dims):
        value = 0 if d.get("pending") or d.get("score") is None else d["score"]
        x, y = _point(i, value, n)
        pts.append(f"{x},{y}")
        dot_color = GREY if d.get("pending") else ORANGE
        dots.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{dot_color}"/>')
    polygon = (
        f'<polygon points="{" ".join(pts)}" fill="{ORANGE}" fill-opacity=".22" '
        f'stroke="{ORANGE}" stroke-width="2"/>'
    )

    labels = []
    for i, d in enumerate(dims):
        lx, ly = _point(i, 8.4, n)  # 标签放在外圈外侧
        anchor = _label_anchor(lx)
        if d.get("pending"):
            score_part = f'<tspan fill="{GREY}" font-weight="700">待核实</tspan>'
            fill = GREY
        else:
            score_part = f'<tspan fill="{ORANGE}" font-weight="700">{d.get("score", 0)}</tspan>'
            fill = TEXT
        labels.append(
            f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="12" fill="{fill}">'
            f'{d["short"]} {score_part}</text>'
        )

    return (
        '<svg viewBox="0 0 420 300" width="100%" style="max-width:460px;display:block;'
        'margin:0 auto" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="七维雷达图">'
        + "".join(rings + axes + [polygon] + dots + labels)
        + "</svg>"
    )

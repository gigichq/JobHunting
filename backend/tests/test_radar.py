"""radar：坐标与待核实置灰。"""
from app.report.radar import render_radar_svg


def _dims(scores):
    shorts = ["能力盘点", "找准岗位", "商业素养", "专业技能", "项目实践", "作品集", "投递管理"]
    return [
        {"short": s, "score": sc, "pending": sc is None}
        for s, sc in zip(shorts, scores)
    ]


def test_svg_structure():
    svg = render_radar_svg(_dims([2, 1, 2, 1, 2, 0, 2]))
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<polygon") == 4  # 3 圈网格 + 1 数据多边形
    assert svg.count("<circle") == 7
    assert "#ff6b35" in svg and "#dfe5f2" in svg


def test_pending_axis_grey_and_labelled():
    svg = render_radar_svg(_dims([2, None, 2, 1, 2, 0, 2]))
    assert "待核实" in svg
    assert "#b4bccb" in svg


def test_full_score_vertex_at_top():
    svg = render_radar_svg(_dims([7, 0, 0, 0, 0, 0, 0]))
    # 第一轴朝上：满分顶点应在 (210, 50)
    assert 'cx="210.0" cy="50.0"' in svg or 'cx="210" cy="50"' in svg

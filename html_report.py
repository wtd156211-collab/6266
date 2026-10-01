"""把 StreamStats 的报告渲染成单文件页面 stability.html。

页面全部数值（指标、误差比、柱高）在生成时取自报告对象，页面本身不含任何计算逻辑；
内嵌的 <script id="report" type="application/json"> 与命令 stdout（去首尾空白）逐字节一致。
"""

import html
import json
import math

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       background: #f4f6f8; color: #1f2733; }
main { max-width: 980px; margin: 0 auto; padding: 24px 20px 48px; }
header h1 { font-size: 22px; margin: 8px 0 4px; }
header .sub { color: #5a6675; font-size: 13px; margin: 0 0 16px; }
section { background: #fff; border: 1px solid #e2e7ec; border-radius: 10px;
          padding: 16px 20px; margin: 14px 0; }
h2 { font-size: 16px; margin: 0 0 10px; }
code { background: #eef1f4; border-radius: 4px; padding: 1px 5px; font-size: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #e2e7ec; padding: 6px 10px; text-align: right;
         font-variant-numeric: tabular-nums; }
th { background: #f0f3f6; text-align: center; }
td:first-child, th:first-child { text-align: left; }
.note { color: #5a6675; font-size: 12px; margin: 8px 0 0; }
ul { margin: 6px 0 0; padding-left: 20px; font-size: 13px; line-height: 1.7; }
.pass { color: #1e7e34; font-weight: 600; }
.fail { color: #c0392b; font-weight: 600; }
"""

_ALGO_COLORS = {"naive": "#d9534f", "shifted": "#e8a13c", "stable": "#3d9970"}


def _token(value):
    """与内嵌 JSON 完全一致的数值文本（json.dumps 对同一 float 产出同一 token）。"""
    return json.dumps(value)


def _svg_chart(algorithms):
    width, height = 940, 400
    plot_left, plot_top, plot_w, plot_h = 90, 30, 820, 300
    axis_y = plot_top + plot_h

    pairs = []
    for algo in algorithms:
        pairs.append((algo["name"], "mean", algo["mean_error_ratio"]))
        pairs.append((algo["name"], "variance", algo["variance_error_ratio"]))
    top = max(1.0, max(ratio for _n, _m, ratio in pairs))
    denom = math.log10(top + 1.0)

    def y_of(ratio):
        return plot_top + plot_h * (1.0 - math.log10(ratio + 1.0) / denom)

    parts = []
    parts.append(
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="三种算法 mean 与 variance 的误差比柱状图">')

    # 网格与纵轴刻度（10 的幂，外加 0）
    tick = 1.0
    ticks = [0.0]
    while tick <= top:
        ticks.append(tick)
        tick *= 10.0
    for value in ticks:
        y = y_of(value)
        label = "0" if value == 0.0 else ("%g" % value)
        parts.append(
            f'<line x1="{plot_left}" y1="{y:.2f}" x2="{plot_left + plot_w}" y2="{y:.2f}" '
            f'stroke="#e2e7ec" stroke-width="1"/>')
        parts.append(
            f'<text x="{plot_left - 8}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-size="11" fill="#5a6675">{label}</text>')
    parts.append(
        f'<text x="{plot_left - 8}" y="{plot_top - 10}" text-anchor="end" '
        f'font-size="11" fill="#5a6675">误差比（log 刻度）</text>')

    # 柱子：每个算法一组，mean / variance 两根
    group_w = plot_w / len(algorithms)
    bar_w = 64
    for gi, algo in enumerate(algorithms):
        name = algo["name"]
        color = _ALGO_COLORS.get(name, "#4a90d9")
        center = plot_left + group_w * gi + group_w / 2.0
        for bi, (metric, ratio) in enumerate(
                (("mean", algo["mean_error_ratio"]),
                 ("variance", algo["variance_error_ratio"]))):
            x = center + (bi - 0.5) * (bar_w + 14) - bar_w / 2.0
            y = y_of(ratio)
            h = axis_y - y
            shade = color if metric == "mean" else color + "99"
            parts.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w}" height="{max(h, 0.5):.2f}" '
                f'fill="{shade}"><title>{name} {metric} 误差比 = '
                f'{html.escape(_token(ratio))}</title></rect>')
            parts.append(
                f'<text x="{x + bar_w / 2.0:.2f}" y="{y - 6:.2f}" text-anchor="middle" '
                f'font-size="10" fill="#1f2733">{html.escape(_token(ratio))}</text>')
        parts.append(
            f'<text x="{center:.2f}" y="{axis_y + 18}" text-anchor="middle" '
            f'font-size="13" font-weight="600" fill="#1f2733">{html.escape(name)}</text>')

    # 容差线：误差比 = 1
    ty = y_of(1.0)
    parts.append(
        f'<line x1="{plot_left}" y1="{ty:.2f}" x2="{plot_left + plot_w}" y2="{ty:.2f}" '
        f'stroke="#c0392b" stroke-width="1.6" stroke-dasharray="7 5"/>')
    parts.append(
        f'<text x="{plot_left + plot_w + 6}" y="{ty + 4:.2f}" font-size="11" '
        f'fill="#c0392b">容差线 误差比=1</text>')

    # 图例
    legend_y = height - 14
    parts.append(
        f'<rect x="{plot_left}" y="{legend_y - 10}" width="12" height="12" fill="#7a8694"/>')
    parts.append(
        f'<text x="{plot_left + 18}" y="{legend_y}" font-size="11" fill="#5a6675">'
        f'mean 误差比（每组左柱，深色）</text>')
    parts.append(
        f'<rect x="{plot_left + 220}" y="{legend_y - 10}" width="12" height="12" fill="#7a869499"/>')
    parts.append(
        f'<text x="{plot_left + 238}" y="{legend_y}" font-size="11" fill="#5a6675">'
        f'variance 误差比（每组右柱，浅色）</text>')
    parts.append('</svg>')
    return "".join(parts)


def render_html(report, report_json):
    """report 是报告字典，report_json 是其单行 JSON（与 stdout 逐字节一致）。"""
    quantiles = report["quantiles"]
    algorithms = report["algorithms"]
    reference = report["reference"]
    source = report["source"]

    metric_rows = []
    metric_rows.append(("count", _token(report["count"])))
    metric_rows.append(("min", _token(report["min"])))
    metric_rows.append(("max", _token(report["max"])))
    metric_rows.append(("mean", _token(report["mean"])))
    metric_rows.append(("variance", _token(report["variance"])))
    for name in ("p10", "p50", "p90", "p99"):
        metric_rows.append((name, _token(quantiles[name])))
    metrics_html = "".join(
        f"<tr><td>{name}</td><td>{value}</td></tr>" for name, value in metric_rows)

    algo_rows = []
    for algo in algorithms:
        name = algo["name"]
        mean_ratio = algo["mean_error_ratio"]
        var_ratio = algo["variance_error_ratio"]
        mean_cls = "pass" if mean_ratio <= 1.0 else "fail"
        var_cls = "pass" if var_ratio <= 1.0 else "fail"
        algo_rows.append(
            f"<tr><td>{html.escape(name)}</td>"
            f"<td>{_token(algo['mean'])}</td>"
            f"<td>{_token(algo['variance'])}</td>"
            f'<td class="{mean_cls}">{_token(mean_ratio)}</td>'
            f'<td class="{var_cls}">{_token(var_ratio)}</td></tr>')
    algorithms_html = "".join(algo_rows)

    chart = _svg_chart(algorithms)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>流式统计聚合 · 算法稳定性对比</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<header>
<h1>流式统计聚合 · 算法稳定性对比</h1>
<p class="sub">数据源 <code>{html.escape(source)}</code> · count = {_token(report['count'])} ·
本页全部数值取自页面底部内嵌报告（与命令 stdout 逐字节一致），页面不做任何重算。</p>
</header>
<section>
<h2>三种算法的误差比</h2>
{chart}
<p class="note">误差比 = |算法值 − 高精度参考值| ÷ (1e-9 + 1e-9×|参考值|)；柱高按
log10(误差比 + 1) 映射以便同图对比，柱顶标注为误差比精确值；红色虚线为容差线（误差比 = 1），
柱高不超过容差线即该项进容差。参考值由 decimal 60 位有效数字在同一遍输入中顺带算出。</p>
</section>
<section>
<h2>各算法数值</h2>
<table>
<tr><th>算法</th><th>mean</th><th>variance</th><th>mean 误差比</th><th>variance 误差比</th></tr>
{algorithms_html}
<tr><td>reference（decimal 60 位）</td><td>{_token(reference['mean'])}</td>
<td>{_token(reference['variance'])}</td><td>—</td><td>—</td></tr>
</table>
</section>
<section>
<h2>关键指标（stable 口径）</h2>
<table>
<tr><th>指标</th><th>值</th></tr>
{metrics_html}
</table>
</section>
<section>
<h2>口径说明</h2>
<ul>
<li>分桶：x&gt;0 时取整数 e 使 10^e ≤ x &lt; 10^(e+1)，首位 d = ⌊x / 10^e⌋，桶记作 (+e, d)；
x&lt;0 对 |x| 同样分桶记作 (−e, d)；0 单独一桶。每个桶只维护个数与总和。</li>
<li>分位数：桶代表值 = 桶内元素算术平均；rank r = p×(n−1)，i = ⌊r⌋，f = r−i，
按第 i / i+1 个元素（升序、0 基）所在桶的代表值线性插值，最后夹到 [min, max]。</li>
<li>stable：均值用 Neumaier 补偿求和，总体方差用 Welford 递推并对 M2 补偿累加（除以 n）。</li>
<li>naive：float 直接累加 Σx、Σx²；shifted：以第一个数为平移量累加后换算。</li>
<li>容差：|得到值 − 精确值| ≤ 1e-9 + 1e-9×|精确值|；误差比即左端除以右端。</li>
</ul>
</section>
</main>
<script id="report" type="application/json">{report_json}</script>
</body>
</html>
"""

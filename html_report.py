"""Renderer for the self-contained stability comparison HTML page."""

from __future__ import annotations


def render_html(report_json: str) -> str:
    """Return a standalone HTML page containing ``report_json`` exactly."""

    if "</script" in report_json.lower():
        raise ValueError("report JSON cannot contain a closing script tag")

    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>流式统计算法稳定性对比</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #5c667a;
      --panel: #ffffff;
      --line: #d8deea;
      --naive: #d95757;
      --shifted: #e0a32e;
      --stable: #32855c;
      --tolerance: #263a66;
      --page: #f2f5fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 32px;
      background: var(--page);
      color: var(--ink);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1120px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 0 0 18px; font-size: 20px; }}
    .subtitle {{ margin: 0 0 24px; color: var(--muted); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 22px;
      margin-bottom: 20px;
      box-shadow: 0 1px 3px rgba(23, 32, 51, .06);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px;
      min-width: 0;
    }}
    .label {{ color: var(--muted); font-size: 12px; }}
    .value {{ margin-top: 4px; font-size: 16px; font-weight: 650; overflow-wrap: anywhere; }}
    .charts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
    }}
    .chart-title {{ font-weight: 700; margin-bottom: 10px; }}
    .chart {{
      position: relative;
      height: 280px;
      border-left: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: flex-end;
      gap: 22px;
      padding: 0 20px 0 34px;
      margin-top: 12px;
      margin-bottom: 28px;
      overflow: visible;
    }}
    .tolerance-line {{
      position: absolute;
      left: 0;
      right: 0;
      top: 50%;
      border-top: 2px dashed var(--tolerance);
      z-index: 2;
    }}
    .tolerance-label {{
      position: absolute;
      right: 4px;
      top: calc(50% - 24px);
      color: var(--tolerance);
      font-size: 12px;
      font-weight: 700;
    }}
    .axis-zero {{ position: absolute; left: -28px; bottom: -20px; font-size: 12px; color: var(--muted); }}
    .axis-one {{ position: absolute; left: -28px; top: calc(50% - 8px); font-size: 12px; color: var(--tolerance); font-weight: 700; }}
    .axis-two {{ position: absolute; left: -28px; top: -8px; font-size: 12px; color: var(--muted); }}
    .bar-wrap {{
      position: relative;
      flex: 1;
      height: 100%;
      display: flex;
      align-items: flex-end;
      z-index: 1;
      min-width: 54px;
    }}
    .bar {{
      width: 100%;
      min-height: 3px;
      border-radius: 7px 7px 0 0;
      position: relative;
    }}
    .bar.naive {{ background: var(--naive); }}
    .bar.shifted {{ background: var(--shifted); }}
    .bar.stable {{ background: var(--stable); }}
    .bar.over-scale {{ background: repeating-linear-gradient(45deg, currentColor 0 8px, #fff 8px 14px); }}
    .bar.naive.over-scale {{ color: var(--naive); }}
    .bar.shifted.over-scale {{ color: var(--shifted); }}
    .bar.stable.over-scale {{ color: var(--stable); }}
    .bar-ratio {{
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      bottom: calc(100% + 6px);
      white-space: nowrap;
      font-size: 12px;
      font-weight: 700;
    }}
    .bar-name {{
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      top: calc(100% + 8px);
      color: var(--muted);
      white-space: nowrap;
      font-size: 12px;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; }}
    td {{ overflow-wrap: anywhere; }}
    .note {{ color: var(--muted); margin: 12px 0 0; }}
    code {{
      background: #eef2f8;
      border-radius: 4px;
      padding: 1px 5px;
    }}
  </style>
</head>
<body>
<main>
  <h1>流式统计算法稳定性对比</h1>
  <p class=\"subtitle\">柱状高度直接取自引擎报告中的误差比；页面只负责展示，不重新计算任何统计量。</p>

  <section class=\"panel\">
    <h2>数据与口径</h2>
    <div class=\"cards\" id=\"summary\"></div>
    <p class=\"note\">数据文件：<code id=\"source\"></code>；容差为 <code>1e-9 + 1e-9 × |精确值|</code>，误差比超过 1 即超出容差。</p>
    <p class=\"note\">分位数按十进制首位数字固定分桶；每个桶只维护个数与总和，桶代表值为桶内算术平均，再按 rank 线性插值。</p>
  </section>

  <section class=\"panel\">
    <h2>误差比（参考值：60 位有效数字 Decimal）</h2>
    <div class=\"charts\">
      <div>
        <div class=\"chart-title\">mean</div>
        <div class=\"chart\" id=\"mean-chart\"></div>
      </div>
      <div>
        <div class=\"chart-title\">variance</div>
        <div class=\"chart\" id=\"variance-chart\"></div>
      </div>
    </div>
    <p class=\"note\">柱高视觉范围为 0–2；超过 2 的柱子仍保留原始误差比数值，并以斜纹封顶。</p>
  </section>

  <section class=\"panel\">
    <h2>算法输出</h2>
    <table>
      <thead>
        <tr>
          <th>algorithm</th>
          <th>mean</th>
          <th>mean_error_ratio</th>
          <th>variance</th>
          <th>variance_error_ratio</th>
        </tr>
      </thead>
      <tbody id=\"algorithm-table\"></tbody>
    </table>
  </section>

  <section class=\"panel\">
    <h2>交付口径关键指标（stable）</h2>
    <div class=\"cards\" id=\"metrics\"></div>
  </section>
</main>

<script id=\"report\" type=\"application/json\">{report_json}</script>
<script>
(function () {{
  "use strict";
  const report = JSON.parse(document.getElementById("report").textContent);
  const metricNames = ["count", "min", "max", "mean", "variance", "p10", "p50", "p90", "p99"];

  function text(value) {{
    return String(value);
  }}

  function card(label, value) {{
    const element = document.createElement("div");
    element.className = "card";
    const labelElement = document.createElement("div");
    labelElement.className = "label";
    labelElement.textContent = label;
    const valueElement = document.createElement("div");
    valueElement.className = "value";
    valueElement.textContent = text(value);
    element.append(labelElement, valueElement);
    return element;
  }}

  function renderCards(container, entries) {{
    entries.forEach(([label, value]) => container.append(card(label, value)));
  }}

  renderCards(document.getElementById("summary"), [
    ["source", report.source],
    ["count", report.count],
    ["absolute tolerance", report.tolerance.absolute],
    ["relative tolerance", report.tolerance.relative],
    ["reference mean", report.reference.mean],
    ["reference variance", report.reference.variance]
  ]);

  const metrics = report.quantiles;
  renderCards(document.getElementById("metrics"), metricNames.map(name => [
    name,
    name in metrics ? metrics[name] : report[name]
  ]));

  function renderChart(containerId, ratioKey) {{
    const container = document.getElementById(containerId);
    const line = document.createElement("div");
    line.className = "tolerance-line";
    const lineLabel = document.createElement("div");
    lineLabel.className = "tolerance-label";
    lineLabel.textContent = "容差线 ratio = 1";
    const zero = document.createElement("div");
    zero.className = "axis-zero";
    zero.textContent = "0";
    const one = document.createElement("div");
    one.className = "axis-one";
    one.textContent = "1";
    const two = document.createElement("div");
    two.className = "axis-two";
    two.textContent = "2+";
    container.append(line, lineLabel, zero, one, two);

    report.algorithms.forEach(algorithm => {{
      const ratio = algorithm[ratioKey];
      const wrap = document.createElement("div");
      wrap.className = "bar-wrap";
      const bar = document.createElement("div");
      const overScale = ratio > 2;
      bar.className = "bar " + algorithm.name + (overScale ? " over-scale" : "");
      bar.style.height = (Math.min(ratio, 2) / 2 * 100) + "%";
      const ratioLabel = document.createElement("div");
      ratioLabel.className = "bar-ratio";
      ratioLabel.textContent = text(ratio);
      const nameLabel = document.createElement("div");
      nameLabel.className = "bar-name";
      nameLabel.textContent = algorithm.name;
      bar.append(ratioLabel);
      wrap.append(bar, nameLabel);
      container.append(wrap);
    }});
  }}

  renderChart("mean-chart", "mean_error_ratio");
  renderChart("variance-chart", "variance_error_ratio");

  const table = document.getElementById("algorithm-table");
  report.algorithms.forEach(algorithm => {{
    const row = document.createElement("tr");
    ["name", "mean", "mean_error_ratio", "variance", "variance_error_ratio"].forEach(field => {{
      const cell = document.createElement("td");
      cell.textContent = text(algorithm[field]);
      row.append(cell);
    }});
    table.append(row);
  }});
}})());
</script>
</body>
</html>
"""

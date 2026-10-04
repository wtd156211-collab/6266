# 使用与验收

## 公开接口

库接口在 `stats_engine.py`：

- `StreamingStats(include_algorithms=False, include_reference=False)`：创建单遍聚合器。
- `consume(lines)`：顺序消费一个文本行迭代器；空行忽略，输入只遍历一次。
- `add_text(line)` / `add(value)`：追加单行文本或一个有限 `float`。
- `report()`：返回可 JSON 序列化的 `count`、`mean`、`variance`、`min`、`max`、
  `quantiles` 和 `tolerance`。
- `quantiles()`：返回固定桶口径的 `p10`、`p50`、`p90`、`p99`。
- `algorithm_results()` / `reference_moments()`：页面误差对比使用的三种 float 口径和
  60 位有效数字 `Decimal` 参考值；需要创建聚合器时打开对应开关。

稳定口径：均值使用 Neumaier 补偿求和；方差以第一个数为平移量，对平移后的值及其平方分别做
补偿求和，再换算总体方差。分位数严格使用 README 规定的十进制首位数字固定桶、桶内算术平均
代表值和 rank 线性插值。

## 命令行

```bash
python stream_stats.py samples/data/02-big-small-step.txt
python stream_stats.py samples/data/02-big-small-step.txt --html stability.html
```

stdout 是单行、键按字母序排列的 JSON。带 `--html` 时，同一次输入遍历会顺带维护
`naive`、`shifted`、`stable` 三种口径和 `Decimal` 参考值；生成的 `stability.html`
是单文件页面，内嵌 JSON 与 stdout 去掉首尾空白后逐字节相同。

## 测试

```bash
python -m unittest discover -s tests
```

## 精度与确定性验收

逐份样例对比 `samples/expected/`：

```bash
for f in samples/data/*.txt; do
  python stream_stats.py "$f" > "/tmp/$(basename "$f").json"
done
python -m unittest discover -s tests -v
```

同一输入连续运行两次，stdout 必须逐字节相同：

```bash
python stream_stats.py samples/data/03-outlier.txt > /tmp/stats-a.json
python stream_stats.py samples/data/03-outlier.txt > /tmp/stats-b.json
cmp /tmp/stats-a.json /tmp/stats-b.json
```

## 时间与内存验收

千万行默认报告：

```bash
/usr/bin/time -f 'elapsed=%e maxrss_kb=%M' \
  python stream_stats.py samples/data/07-scale-1e7.txt > /tmp/report07.json
```

统计阶段的 `tracemalloc` 峰值：

```bash
python - <<'PY'
import tracemalloc
from stats_engine import StreamingStats

for name in ("03-outlier", "07-scale-1e7"):
    engine = StreamingStats()
    tracemalloc.start()
    with open(f"samples/data/{name}.txt", encoding="utf-8") as rows:
        engine.consume(rows)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(name, "current=", current, "peak=", peak)
PY
```

本实现只保存计数、极值、补偿累加量、固定桶 `[个数, 总和]` 和可选对比算法状态；不保存输入行，
不回读文件，也不把元素收集到列表中。

## 页面检查

```bash
python stream_stats.py samples/data/02-big-small-step.txt --html stability.html > /tmp/report.json
```

检查点：

- 直接双击 `stability.html` 可打开，无外部脚本、样式、图片或网络资源。
- 页面包含 `<script id="report" type="application/json">…</script>`。
- 内嵌 JSON 与 `/tmp/report.json` 去掉首尾空白后逐字节相同。
- 柱高来自报告中的 `mean_error_ratio` / `variance_error_ratio`，虚线为误差比 1 的容差线。
- 页面列出文件名、count、容差公式、桶口径、关键指标和三种算法输出。

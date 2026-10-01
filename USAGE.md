# 使用说明与验收复现

口径（分桶、插值、容差、三种算法定义）的权威描述在 `README.md` 第二节；
本文件只说明接口怎么用、验收怎么复现。口径若要改动，先改 `README.md` 再动实现，
保证每一处实现都能追回到该文件。

## 命令行

```bash
python stream_stats.py <数据文件>                        # 单行 JSON 报告到 stdout
python stream_stats.py <数据文件> --html stability.html   # 额外生成单文件对比页面
```

输入为 UTF-8 文本，一行一个十进制数（可带符号、小数点、e/E 指数），空行忽略；
输入只顺序读一遍，不缓存元素。非数字行直接报错退出（exit 2），空输入同样报错。

## 库接口（`streamstats.py`）

```python
from streamstats import StreamStats, bucket_key

stats = StreamStats(compare_algorithms=False, with_reference=False)
for line in f:                      # 任意可迭代来源，不要求文件
    text = line.strip()
    if text:
        stats.add(float(text), text)   # 第二个参数（字面量）仅 with_reference=True 时需要
report = stats.report(source=None)  # dict，键与 stdout JSON 一致；空输入抛 ValueError
```

- `StreamStats(compare_algorithms=…, with_reference=…)`：两个开关只在生成页面时打开，
  分别额外维护 naive / shifted 两套 float 口径和 decimal 60 位参考值；默认报告只走
  stable 口径（均值 Neumaier 补偿求和，总体方差 Welford 递推 + M2 补偿累加）。
- `add(value, literal=None)`：喂一个数；`report(source=None)`：出报告字典。
- `bucket_key(x)`：固定分桶口径，返回 `(符号, e, d)`，零为 `(0, 0, 0)`。
- 常量 `TOLERANCE_ABSOLUTE` / `TOLERANCE_RELATIVE`（均为 1e-9）、`QUANTILE_POINTS`。
- 内存：除固定数量的累加量与固定桶表（键数只随量级种类，不随 n）外不留任何元素。

## 页面 `stability.html`

双击即开，无外部资源。页面标注数据源文件名、count、容差公式、桶口径与三种算法定义；
柱状图为三种算法 mean / variance 的误差比（柱高按 log10(误差比+1) 映射，柱顶标精确值），
红色虚线为容差线（误差比 = 1）。所有数值取自内嵌的
`<script id="report" type="application/json">`（与 stdout 逐字节一致），页面不重算。

## 验收复现

```bash
# 1. 精度 / 分位数口径 / 确定性 / 页面 / 内存（unittest，只用标准库）
python -m unittest discover -s tests

# 2. 确定性：同一文件两次运行逐字节相同
python stream_stats.py samples/data/07-scale-1e7.txt > a.json
python stream_stats.py samples/data/07-scale-1e7.txt > b.json
cmp a.json b.json

# 3. 时间（07 号默认报告，预算 45 秒）
time python stream_stats.py samples/data/07-scale-1e7.txt

# 4. 内存（tracemalloc 峰值：07 比 03 高不超过 8 MB，且 07 峰值不超过 64 MB）
python - <<'PY'
import tracemalloc
from streamstats import StreamStats
def run(path):
    s = StreamStats()
    with open(path, encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if t:
                s.add(float(t))
    s.report()
for name in ("03-outlier", "07-scale-1e7"):
    tracemalloc.start()
    run(f"samples/data/{name}.txt")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(name, "peak =", peak / 1024 / 1024, "MB")
PY

# 5. 页面：内嵌 JSON 与 stdout 一致、无外部引用
python stream_stats.py samples/data/02-big-small-step.txt --html stability.html
python - <<'PY'
import re, subprocess, sys
page = open("stability.html", encoding="utf-8").read()
out = subprocess.run([sys.executable, "stream_stats.py",
                      "samples/data/02-big-small-step.txt"],
                     capture_output=True, text=True).stdout.strip()
embedded = re.search(r'<script id="report" type="application/json">(.*?)</script>',
                     page, re.S).group(1)
assert embedded == out
assert "http://" not in page and "https://" not in page
print("page OK")
PY
```

本机实测：07 号默认报告约 4.5 秒、tracemalloc 峰值 07 比 03 高约 7.6 KB。

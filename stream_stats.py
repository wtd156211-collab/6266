#!/usr/bin/env python3
"""命令行入口：流式统计聚合。

    python stream_stats.py <数据文件>                        # 报告 JSON 写到 stdout
    python stream_stats.py <数据文件> --html stability.html   # 额外写单文件页面

输入只顺序读一遍（逐行），不缓存元素；库接口见 streamstats.py，口径见 README.md。
"""

import argparse
import json
import sys

from html_report import render_html
from streamstats import StreamStats


def build_report(datafile, with_html):
    stats = StreamStats(compare_algorithms=with_html, with_reference=with_html)
    with open(datafile, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                value = float(text)
            except ValueError:
                raise SystemExit(
                    f"error: {datafile}:{lineno}: not a number: {text!r}")
            stats.add(value, text)
    return stats.report(source=datafile if with_html else None)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="流式统计聚合：一次遍历输出 count/mean/variance/min/max/分位数")
    parser.add_argument("datafile", help="一行一个十进制数的 UTF-8 文本文件")
    parser.add_argument("--html", metavar="PATH",
                        help="额外生成单文件对比页面（含三种算法误差柱状图）")
    args = parser.parse_args(argv)

    try:
        report = build_report(args.datafile, with_html=bool(args.html))
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")

    out = json.dumps(report, sort_keys=True, separators=(",", ":"))
    print(out)

    if args.html:
        with open(args.html, "w", encoding="utf-8") as handle:
            handle.write(render_html(report, out))


if __name__ == "__main__":
    sys.exit(main())

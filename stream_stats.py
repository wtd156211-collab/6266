#!/usr/bin/env python3
"""Command-line entry point for the streaming statistics engine.

Usage:
    python stream_stats.py DATA_FILE
    python stream_stats.py DATA_FILE --html stability.html

The module can also be used as a library through ``StreamingStats`` and
``parse_number``.  Both the CLI and library consume input exactly once and
keep only bounded aggregate state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from html_report import render_html
from stats_engine import StreamingStats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute deterministic single-pass streaming statistics."
    )
    parser.add_argument("data_file", help="UTF-8 text file containing one decimal number per line")
    parser.add_argument(
        "--html",
        metavar="HTML_FILE",
        help="also write a self-contained algorithm stability report",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    include_comparison = args.html is not None

    engine = StreamingStats(
        include_algorithms=include_comparison,
        include_reference=include_comparison,
    )
    try:
        with open(args.data_file, "r", encoding="utf-8", newline=None) as data:
            engine.consume(data)
        report = engine.report(include_comparison=include_comparison, source=args.data_file)
        report_json = json.dumps(
            report,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if args.html is not None:
            Path(args.html).write_text(render_html(report_json), encoding="utf-8")
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"stream_stats: error: {exc}\n")

    sys.stdout.write(report_json + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

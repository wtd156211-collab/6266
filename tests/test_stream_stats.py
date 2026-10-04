from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from stats_engine import StreamingStats, parse_number


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "stream_stats.py"
DATA_DIR = ROOT / "samples" / "data"
EXPECTED_DIR = ROOT / "samples" / "expected"


def exact_fraction(text: str) -> Fraction:
    if "/" in text:
        return Fraction(text)
    return Fraction(Decimal(text))


def expected_metrics(path: Path):
    metrics = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, rest = line.split("=", 1)
        name = name.strip()
        if "|" in rest:
            exact_text, interval_text = rest.split("|", 1)
            bounds_text = interval_text.strip().strip("[]")
            lower_text, upper_text = bounds_text.split(",", 1)
            metrics[name] = (
                exact_fraction(exact_text.strip()),
                Decimal(lower_text.strip()),
                Decimal(upper_text.strip()),
            )
        else:
            metrics[name] = exact_fraction(rest.strip())
    return metrics


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class SampleAcceptanceTests(unittest.TestCase):
    def test_all_sample_reports_match_expected_ranges(self) -> None:
        for expected_path in sorted(EXPECTED_DIR.glob("*.txt")):
            with self.subTest(sample=expected_path.name):
                data_path = DATA_DIR / expected_path.name
                completed = run_cli(str(data_path))
                self.assertEqual(completed.stdout.count(b"\n"), 1)
                report = json.loads(completed.stdout)
                expected = expected_metrics(expected_path)

                self.assertEqual(report["count"], int(expected["count"]))
                for name in ("min", "max"):
                    expected_float = float(expected[name])
                    self.assertEqual(report[name], expected_float)
                    self.assertEqual(math.copysign(1.0, report[name]), math.copysign(1.0, expected_float))

                for name in ("mean", "variance"):
                    _exact, lower, upper = expected[name]
                    observed = Decimal(repr(report[name]))
                    self.assertLessEqual(lower, observed, name)
                    self.assertLessEqual(observed, upper, name)

                for name in ("p10", "p50", "p90", "p99"):
                    _exact, lower, upper = expected[name]
                    observed = Decimal(repr(report["quantiles"][name]))
                    self.assertLessEqual(lower, observed, name)
                    self.assertLessEqual(observed, upper, name)

    def test_cli_output_is_deterministic_and_sorted(self) -> None:
        data_path = str(DATA_DIR / "03-outlier.txt")
        first = run_cli(data_path).stdout
        second = run_cli(data_path).stdout
        self.assertEqual(first, second)

        report = json.loads(first)
        self.assertEqual(list(report), sorted(report))
        self.assertEqual(list(report["quantiles"]), sorted(report["quantiles"]))

    def test_html_embeds_exact_stdout_and_algorithm_errors(self) -> None:
        for sample_name, naive_field in (
            ("01-spread-sign.txt", "mean_error_ratio"),
            ("02-big-small-step.txt", "variance_error_ratio"),
        ):
            with self.subTest(sample=sample_name), tempfile.TemporaryDirectory() as directory:
                html_path = Path(directory) / "stability.html"
                data_path = str(DATA_DIR / sample_name)
                completed = run_cli(data_path, "--html", str(html_path))
                stdout_json = completed.stdout.decode("utf-8").strip()
                html = html_path.read_text(encoding="utf-8")

                match = re.search(
                    r'<script id="report" type="application/json">(.*?)</script>',
                    html,
                    flags=re.DOTALL,
                )
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), stdout_json)
                self.assertIsNone(re.search(r"https?://|\bsrc=|\bhref=", html, flags=re.IGNORECASE))

                report = json.loads(stdout_json)
                self.assertEqual(report["source"], data_path)
                self.assertIn("reference", report)
                algorithms = {item["name"]: item for item in report["algorithms"]}
                self.assertEqual(set(algorithms), {"naive", "shifted", "stable"})
                self.assertGreater(algorithms["naive"][naive_field], 1.0)
                self.assertLessEqual(algorithms["stable"]["mean_error_ratio"], 1.0)
                self.assertLessEqual(algorithms["stable"]["variance_error_ratio"], 1.0)
                self.assertEqual(report["mean"], algorithms["stable"]["mean"])
                self.assertEqual(report["variance"], algorithms["stable"]["variance"])


class StreamingEngineTests(unittest.TestCase):
    def test_consume_skips_blank_lines_and_accepts_crlf(self) -> None:
        engine = StreamingStats().consume(["\n", " 1.5\r\n", "\t2.5E0  \n", "   \n"])
        report = engine.report()
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["mean"], 2.0)
        self.assertEqual(report["variance"], 0.25)

    def test_consume_uses_one_iterator_pass(self) -> None:
        class OneWayInput:
            def __init__(self) -> None:
                self.iterations = 0

            def __iter__(self):
                self.iterations += 1
                return iter(["4", "8", "16"])

        lines = OneWayInput()
        engine = StreamingStats().consume(lines)
        self.assertEqual(lines.iterations, 1)
        self.assertEqual(engine.count, 3)
        self.assertEqual(engine.report()["mean"], 28 / 3)

    def test_add_matches_text_consumption(self) -> None:
        added = StreamingStats()
        consumed = StreamingStats()
        for value in (1.25, -2.5, 3.75):
            added.add(value)
            consumed.add_text(repr(value))
        self.assertEqual(added.report(), consumed.report())

    def test_invalid_and_empty_input_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StreamingStats().consume(["1", "not-a-number"])
        with self.assertRaises(ValueError):
            StreamingStats().consume(["1_000"])
        with self.assertRaises(ValueError):
            StreamingStats().consume(["nan"])
        with self.assertRaises(ValueError):
            StreamingStats().consume(["1e9999"])
        with self.assertRaises(ValueError):
            StreamingStats().consume(["", "  "]).report()
        with self.assertRaises(ValueError):
            parse_number("")

    def test_quantile_bucket_edges(self) -> None:
        engine = StreamingStats().consume(
            ["0", "0.5", "0.0009765625", "1", "9.5", "10", "99", "1000", "-0.125", "-2", "-1000"]
        )
        quantiles = engine.quantiles()
        self.assertEqual(quantiles["p10"], -2.0)
        self.assertEqual(quantiles["p50"], 0.5)
        self.assertEqual(quantiles["p90"], 99.0)
        self.assertAlmostEqual(quantiles["p99"], 909.9, places=12)

    def test_smallest_positive_float_has_a_valid_bucket(self) -> None:
        engine = StreamingStats().consume(["5e-324", "1e-323"])
        report = engine.report()
        self.assertEqual(report["min"], 5e-324)
        self.assertEqual(report["max"], 1e-323)
        self.assertEqual(report["quantiles"]["p10"], 5e-324)
        self.assertEqual(report["quantiles"]["p90"], 1e-323)


if __name__ == "__main__":
    unittest.main()

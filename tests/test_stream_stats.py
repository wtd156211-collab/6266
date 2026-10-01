import json
import os
import re
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import stream_stats  # noqa: E402
from streamstats import StreamStats, bucket_key  # noqa: E402

DATA_DIR = os.path.join(ROOT, "samples", "data")
EXPECTED_DIR = os.path.join(ROOT, "samples", "expected")
SAMPLES = (
    "01-spread-sign",
    "02-big-small-step",
    "03-outlier",
    "04-all-equal",
    "05-single",
    "06-bucket-edges",
    "07-scale-1e7",
)
METRICS = ("mean", "variance", "p10", "p50", "p90", "p99")


def parse_expected(path):
    exact = {}
    intervals = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            key, rest = text.split("=", 1)
            key = key.strip()
            if "|" in rest:
                value_text, interval = rest.split("|", 1)
                lo_text, hi_text = interval.strip().strip("[]").split(",")
                intervals[key] = (float(lo_text), float(hi_text))
            else:
                value_text = rest
            exact[key] = Fraction(value_text.strip())
    return exact, intervals


def run_engine(datafile, with_html=False):
    stats = StreamStats(compare_algorithms=with_html, with_reference=with_html)
    with open(datafile, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            stats.add(float(text), text)
    return stats.report(source=datafile if with_html else None)


def metric_value(report, key):
    if key.startswith("p"):
        return report["quantiles"][key]
    return report[key]


class BucketKeyTests(unittest.TestCase):
    def test_positive_powers_and_digits(self):
        self.assertEqual(bucket_key(1.0), (1, 0, 1))
        self.assertEqual(bucket_key(10.0), (1, 1, 1))
        self.assertEqual(bucket_key(1000.0), (1, 3, 1))
        self.assertEqual(bucket_key(9.5), (1, 0, 9))
        self.assertEqual(bucket_key(99.0), (1, 1, 9))
        self.assertEqual(bucket_key(0.5), (1, -1, 5))
        self.assertEqual(bucket_key(0.0009765625), (1, -4, 9))

    def test_negative_and_zero(self):
        self.assertEqual(bucket_key(-0.125), (-1, -1, 1))
        self.assertEqual(bucket_key(-2.0), (-1, 0, 2))
        self.assertEqual(bucket_key(-1000.0), (-1, 3, 1))
        self.assertEqual(bucket_key(0.0), (0, 0, 0))
        self.assertEqual(bucket_key(-0.0), (0, 0, 0))


class SampleAccuracyTests(unittest.TestCase):
    def test_all_samples_against_expected(self):
        for name in SAMPLES:
            with self.subTest(sample=name):
                report = run_engine(os.path.join(DATA_DIR, name + ".txt"))
                exact, intervals = parse_expected(
                    os.path.join(EXPECTED_DIR, name + ".txt"))

                self.assertEqual(report["count"], int(exact["count"]))
                self.assertEqual(report["min"], float(exact["min"]))
                self.assertEqual(report["max"], float(exact["max"]))

                for key in METRICS:
                    value = metric_value(report, key)
                    lo, hi = intervals[key]
                    self.assertGreaterEqual(
                        value, lo, msg=f"{key}={value!r} below [{lo}, {hi}]")
                    self.assertLessEqual(
                        value, hi, msg=f"{key}={value!r} above [{lo}, {hi}]")

    def test_all_equal_variance_is_exactly_zero(self):
        report = run_engine(os.path.join(DATA_DIR, "04-all-equal.txt"))
        self.assertEqual(report["variance"], 0.0)

    def test_single_element(self):
        report = run_engine(os.path.join(DATA_DIR, "05-single.txt"))
        self.assertEqual(report["variance"], 0.0)
        for value in report["quantiles"].values():
            self.assertEqual(value, 1000.0)

    def test_stable_is_top_level_output(self):
        report = run_engine(os.path.join(DATA_DIR, "01-spread-sign.txt"),
                            with_html=True)
        stable = next(a for a in report["algorithms"] if a["name"] == "stable")
        self.assertEqual(stable["mean"], report["mean"])
        self.assertEqual(stable["variance"], report["variance"])

    def test_naive_fails_while_stable_passes(self):
        for name in ("01-spread-sign", "02-big-small-step"):
            with self.subTest(sample=name):
                report = run_engine(os.path.join(DATA_DIR, name + ".txt"),
                                    with_html=True)
                by_name = {a["name"]: a for a in report["algorithms"]}
                naive = by_name["naive"]
                self.assertGreater(
                    max(naive["mean_error_ratio"],
                        naive["variance_error_ratio"]), 1.0)
                stable = by_name["stable"]
                self.assertLessEqual(stable["mean_error_ratio"], 1.0)
                self.assertLessEqual(stable["variance_error_ratio"], 1.0)

    def test_reference_matches_exact(self):
        for name in ("01-spread-sign", "02-big-small-step", "06-bucket-edges"):
            with self.subTest(sample=name):
                exact, _ = parse_expected(
                    os.path.join(EXPECTED_DIR, name + ".txt"))
                report = run_engine(os.path.join(DATA_DIR, name + ".txt"),
                                    with_html=True)
                for key in ("mean", "variance"):
                    ref = Fraction(repr(report["reference"][key]))
                    tol = Fraction(1, 10**9) * (1 + abs(exact[key]))
                    self.assertLess(abs(ref - exact[key]), tol / 1000)


class DeterminismTests(unittest.TestCase):
    def test_two_runs_byte_identical(self):
        datafile = os.path.join(DATA_DIR, "03-outlier.txt")
        outs = []
        for _ in range(2):
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "stream_stats.py"), datafile],
                check=True, capture_output=True, text=True)
            outs.append(proc.stdout)
        self.assertEqual(outs[0], outs[1])

    def test_json_single_line_sorted_keys(self):
        datafile = os.path.join(DATA_DIR, "04-all-equal.txt")
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "stream_stats.py"), datafile],
            check=True, capture_output=True, text=True)
        stdout = proc.stdout
        self.assertEqual(stdout.count("\n"), 1)
        report = json.loads(stdout)
        self.assertEqual(
            list(report), sorted(report))
        self.assertEqual(
            list(report["quantiles"]), ["p10", "p50", "p90", "p99"])


class HtmlPageTests(unittest.TestCase):
    def test_page_embeds_exact_stdout_and_no_external_refs(self):
        datafile = os.path.join(DATA_DIR, "02-big-small-step.txt")
        with tempfile.TemporaryDirectory() as tmp:
            html_path = os.path.join(tmp, "stability.html")
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "stream_stats.py"),
                 datafile, "--html", html_path],
                check=True, capture_output=True, text=True)
            stdout_json = proc.stdout.strip()
            with open(html_path, encoding="utf-8") as handle:
                page = handle.read()

        match = re.search(
            r'<script id="report" type="application/json">(.*?)</script>',
            page, re.S)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), stdout_json)

        lowered = page.lower()
        for needle in ("http://", "https://", "src=", "@import"):
            self.assertNotIn(needle, lowered)

        report = json.loads(stdout_json)
        for key in ("source", "reference", "algorithms"):
            self.assertIn(key, report)
        self.assertEqual(report["source"], datafile)
        names = [a["name"] for a in report["algorithms"]]
        self.assertEqual(names, ["naive", "shifted", "stable"])

        for value in (report["count"], report["min"], report["max"],
                      report["mean"], report["variance"],
                      *report["quantiles"].values(),
                      *[a["mean_error_ratio"] for a in report["algorithms"]],
                      *[a["variance_error_ratio"] for a in report["algorithms"]]):
            self.assertIn(json.dumps(value), page)
        self.assertIn("容差线", page)
        self.assertIn("误差比 = 1", page)


class MemoryTests(unittest.TestCase):
    def _feed(self, n):
        stats = StreamStats()
        for i in range(n):
            stats.add(float(i % 10))
        return stats.report()

    def test_peak_does_not_grow_with_n(self):
        tracemalloc.start()
        self._feed(1000)
        _, peak_small = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        report = self._feed(1_000_000)
        _, peak_large = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertLess(peak_large - peak_small, 8 * 1024 * 1024)
        self.assertEqual(report["count"], 1_000_000)


if __name__ == "__main__":
    unittest.main()

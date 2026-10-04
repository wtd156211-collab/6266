"""Single-pass streaming statistics with deterministic, bounded-memory state.

Public API:
    StreamingStats: incrementally consumes one decimal number per input line.
    parse_number: parses one input line according to the supported grammar.

The aggregator stores only counters, moments, extrema, and fixed-granularity
bucket summaries.  It never stores input elements, so peak memory does not
grow with the number of consumed rows.
"""

from __future__ import annotations

import math
from decimal import Context, Decimal
from typing import Dict, Iterable, List, Optional, Tuple, Union


TOLERANCE_ABSOLUTE = 1e-9
TOLERANCE_RELATIVE = 1e-9
REFERENCE_PRECISION = 60

BucketKey = Tuple[int, int, int]
BucketValue = List[Union[int, float]]
InputLine = Union[str, bytes]


def parse_number(line: InputLine) -> float:
    """Parse one non-empty input line as a finite Python float.

    Surrounding whitespace is ignored; blank lines are skipped by
    ``StreamingStats.consume`` and rejected by this lower-level parser.
    Python's float parser is intentionally used after rejecting underscores
    and non-finite tokens so the accepted decimal grammar remains the one
    required by the CLI contract.
    """

    if isinstance(line, bytes):
        text = line.decode("utf-8")
    elif isinstance(line, str):
        text = line
    else:
        raise TypeError("input lines must be str or bytes")

    token = text.strip()
    if not token:
        raise ValueError("blank input line")
    if "_" in token:
        raise ValueError(f"invalid numeric literal: {token!r}")

    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric literal: {token!r}")
    return value


class StreamingStats:
    """Aggregate count, moments, extrema, and fixed buckets in one pass.

    Args:
        include_algorithms: also maintain the naive and shifted comparison
            algorithms used by the HTML stability report.
        include_reference: also maintain a 60-significant-digit Decimal sum
            and sum of squares for the report reference values.

    The stable mean uses Neumaier compensated summation.  The stable variance
    uses compensated sums of values and squared values shifted by the first
    input value, avoiding the catastrophic cancellation of the naive raw
    moment formula on large-base/small-increment data.
    """

    def __init__(self, include_algorithms: bool = False, include_reference: bool = False) -> None:
        self.include_algorithms = include_algorithms
        self.include_reference = include_reference

        self.count = 0
        self.minimum: Optional[float] = None
        self.maximum: Optional[float] = None

        self._sum = 0.0
        self._sum_compensation = 0.0
        self._first: Optional[float] = None
        self._shifted_sum = 0.0
        self._shifted_sum_compensation = 0.0
        self._shifted_square_sum = 0.0
        self._shifted_square_compensation = 0.0

        self._naive_sum = 0.0
        self._naive_square_sum = 0.0
        self._algorithm_shifted_sum = 0.0
        self._algorithm_shifted_square_sum = 0.0

        self._decimal_context = Context(prec=REFERENCE_PRECISION)
        self._decimal_sum = Decimal(0)
        self._decimal_square_sum = Decimal(0)

        self._buckets: Dict[BucketKey, BucketValue] = {}

    def add(self, value: float) -> None:
        """Add one already-parsed finite float."""

        if not math.isfinite(value):
            raise ValueError("value must be finite")
        self.add_text(repr(value))

    def add_text(self, line: InputLine) -> None:
        """Parse and add one input line."""

        self.consume((line,))

    def consume(self, lines: Iterable[InputLine]) -> "StreamingStats":
        """Consume an input iterator once and return this aggregator.

        Empty lines are skipped.  The iterator is never rewound and no lines
        are retained after their per-row state updates complete.
        """

        count = self.count
        minimum = self.minimum
        maximum = self.maximum

        total = self._sum
        total_compensation = self._sum_compensation
        first = self._first
        shifted_total = self._shifted_sum
        shifted_compensation = self._shifted_sum_compensation
        square_total = self._shifted_square_sum
        square_compensation = self._shifted_square_compensation

        naive_total = self._naive_sum
        naive_square_total = self._naive_square_sum
        algorithm_shifted_total = self._algorithm_shifted_sum
        algorithm_shifted_square_total = self._algorithm_shifted_square_sum

        decimal_context = self._decimal_context
        decimal_total = self._decimal_sum
        decimal_square_total = self._decimal_square_sum

        buckets = self._buckets
        include_algorithms = self.include_algorithms
        include_reference = self.include_reference

        for line in lines:
            if isinstance(line, bytes):
                token = line.decode("utf-8").strip()
            elif isinstance(line, str):
                token = line.strip()
            else:
                raise TypeError("input lines must be str or bytes")
            if not token:
                continue
            if "_" in token:
                raise ValueError(f"invalid numeric literal: {token!r}")

            value = float(token)
            if not math.isfinite(value):
                raise ValueError(f"non-finite numeric literal: {token!r}")

            count += 1
            if minimum is None or value < minimum:
                minimum = value
            if maximum is None or value > maximum:
                maximum = value

            new_total = total + value
            if abs(total) >= abs(value):
                total_compensation += (total - new_total) + value
            else:
                total_compensation += (value - new_total) + total
            total = new_total

            if first is None:
                first = value
            shifted = value - first

            new_shifted_total = shifted_total + shifted
            if abs(shifted_total) >= abs(shifted):
                shifted_compensation += (shifted_total - new_shifted_total) + shifted
            else:
                shifted_compensation += (shifted - new_shifted_total) + shifted_total
            shifted_total = new_shifted_total

            shifted_square = shifted * shifted
            new_square_total = square_total + shifted_square
            if abs(square_total) >= abs(shifted_square):
                square_compensation += (square_total - new_square_total) + shifted_square
            else:
                square_compensation += (shifted_square - new_square_total) + square_total
            square_total = new_square_total

            if include_algorithms:
                naive_total += value
                naive_square_total += value * value
                algorithm_shifted_total += shifted
                algorithm_shifted_square_total += shifted_square

            if include_reference:
                decimal_value = Decimal(token)
                decimal_total = decimal_context.add(decimal_total, decimal_value)
                decimal_square_total = decimal_context.add(
                    decimal_square_total,
                    decimal_context.multiply(decimal_value, decimal_value),
                )

            if value > 0.0:
                bucket_key = _positive_bucket_key(value)
            elif value < 0.0:
                bucket_key = _negative_bucket_key(value)
            else:
                bucket_key = (0, 0, 0)

            bucket = buckets.get(bucket_key)
            if bucket is None:
                buckets[bucket_key] = [1, value]
            else:
                bucket[0] += 1
                bucket[1] += value

        self.count = count
        self.minimum = minimum
        self.maximum = maximum
        self._sum = total
        self._sum_compensation = total_compensation
        self._first = first
        self._shifted_sum = shifted_total
        self._shifted_sum_compensation = shifted_compensation
        self._shifted_square_sum = square_total
        self._shifted_square_compensation = square_compensation
        self._naive_sum = naive_total
        self._naive_square_sum = naive_square_total
        self._algorithm_shifted_sum = algorithm_shifted_total
        self._algorithm_shifted_square_sum = algorithm_shifted_square_total
        self._decimal_sum = decimal_total
        self._decimal_square_sum = decimal_square_total
        return self

    def stable_mean(self) -> float:
        self._require_data()
        return (self._sum + self._sum_compensation) / self.count

    def stable_variance(self) -> float:
        self._require_data()
        shifted_sum = self._shifted_sum + self._shifted_sum_compensation
        square_sum = self._shifted_square_sum + self._shifted_square_compensation
        variance = (square_sum - (shifted_sum * shifted_sum) / self.count) / self.count
        if variance < 0.0:
            return 0.0
        return variance

    def algorithm_results(self) -> List[Dict[str, float]]:
        """Return naive, shifted, and stable mean/variance results."""

        self._require_data()
        if not self.include_algorithms:
            raise RuntimeError("algorithm comparison state was not enabled")

        naive_mean = self._naive_sum / self.count
        naive_variance = self._naive_square_sum / self.count - naive_mean * naive_mean

        shifted_mean_offset = self._algorithm_shifted_sum / self.count
        shifted_mean = self._first + shifted_mean_offset  # type: ignore[operator]
        shifted_variance = (
            self._algorithm_shifted_square_sum / self.count
            - shifted_mean_offset * shifted_mean_offset
        )

        stable_mean = self.stable_mean()
        stable_variance = self.stable_variance()
        return [
            {"name": "naive", "mean": naive_mean, "variance": naive_variance},
            {"name": "shifted", "mean": shifted_mean, "variance": shifted_variance},
            {"name": "stable", "mean": stable_mean, "variance": stable_variance},
        ]

    def reference_moments(self) -> Tuple[Decimal, Decimal]:
        """Return high-precision Decimal reference mean and variance."""

        self._require_data()
        if not self.include_reference:
            raise RuntimeError("Decimal reference state was not enabled")

        context = self._decimal_context
        count = Decimal(self.count)
        mean = context.divide(self._decimal_sum, count)
        variance = context.subtract(
            context.divide(self._decimal_square_sum, count),
            context.multiply(mean, mean),
        )
        square_scale = abs(context.divide(self._decimal_square_sum, count))
        if variance < 0 and abs(variance) < Decimal("1e-50") * max(Decimal(1), square_scale):
            variance = Decimal(0)
        return mean, variance

    def quantiles(self) -> Dict[str, float]:
        """Return p10, p50, p90, and p99 using the fixed bucket contract."""

        self._require_data()
        ordered_buckets = sorted(self._buckets.items(), key=lambda item: _bucket_sort_key(item[0]))
        result: Dict[str, float] = {}
        for name, probability in (("p10", 0.10), ("p50", 0.50), ("p90", 0.90), ("p99", 0.99)):
            rank = probability * (self.count - 1)
            index = math.floor(rank)
            fraction = rank - index
            lower = _bucket_representative_at(ordered_buckets, index)
            if index + 1 >= self.count:
                upper = lower
            else:
                upper = _bucket_representative_at(ordered_buckets, index + 1)
            value = (1.0 - fraction) * lower + fraction * upper
            if value < self.minimum:  # type: ignore[operator]
                value = self.minimum  # type: ignore[assignment]
            elif value > self.maximum:  # type: ignore[operator]
                value = self.maximum  # type: ignore[assignment]
            result[name] = value
        return result

    def report(self, include_comparison: bool = False, source: Optional[str] = None) -> Dict[str, object]:
        """Build the JSON-serializable statistics report."""

        self._require_data()
        stable_mean = self.stable_mean()
        stable_variance = self.stable_variance()
        report: Dict[str, object] = {
            "count": self.count,
            "max": self.maximum,
            "mean": stable_mean,
            "min": self.minimum,
            "quantiles": self.quantiles(),
            "tolerance": {
                "absolute": TOLERANCE_ABSOLUTE,
                "relative": TOLERANCE_RELATIVE,
            },
            "variance": stable_variance,
        }

        if include_comparison:
            reference_mean, reference_variance = self.reference_moments()
            algorithms = []
            for algorithm in self.algorithm_results():
                algorithms.append(
                    {
                        "name": algorithm["name"],
                        "mean": algorithm["mean"],
                        "variance": algorithm["variance"],
                        "mean_error_ratio": _error_ratio(algorithm["mean"], reference_mean, self._decimal_context),
                        "variance_error_ratio": _error_ratio(
                            algorithm["variance"], reference_variance, self._decimal_context
                        ),
                    }
                )
            report["algorithms"] = algorithms
            report["reference"] = {
                "mean": float(reference_mean),
                "variance": float(reference_variance),
            }
            report["source"] = source
        return report

    def _require_data(self) -> None:
        if self.count == 0:
            raise ValueError("at least one numeric input row is required")


def _positive_bucket_key(value: float) -> BucketKey:
    exponent, digit = _bucket_exponent_digit(value)
    return (1, exponent, digit)


def _negative_bucket_key(value: float) -> BucketKey:
    exponent, digit = _bucket_exponent_digit(-value)
    return (-1, exponent, digit)


def _bucket_exponent_digit(value: float) -> Tuple[int, int]:
    exponent = math.floor(math.log10(value))
    if exponent < -323:
        if value >= 10.0 ** -323:
            exponent = -323
        else:
            return (-324, 1)
    scaled = value / (10.0 ** exponent)
    if scaled < 1.0:
        exponent -= 1
        scaled = value / (10.0 ** exponent)
    elif scaled >= 10.0:
        exponent += 1
        scaled = value / (10.0 ** exponent)
    digit = int(scaled)
    if digit < 1:
        digit = 1
    elif digit > 9:
        digit = 9
    return exponent, digit


def _bucket_sort_key(key: BucketKey) -> Tuple[int, int, int]:
    sign, exponent, digit = key
    if sign < 0:
        return (0, -exponent, -digit)
    if sign == 0:
        return (1, 0, 0)
    return (2, exponent, digit)


def _bucket_representative_at(
    ordered_buckets: List[Tuple[BucketKey, BucketValue]], index: int
) -> float:
    covered = 0
    for _key, (bucket_count, bucket_total) in ordered_buckets:
        covered += int(bucket_count)
        if index < covered:
            return bucket_total / bucket_count
    raise IndexError("quantile index is outside the bucket summary")


def _error_ratio(value: float, reference: Decimal, context: Context) -> float:
    observed = Decimal(repr(value))
    error = abs(context.subtract(observed, reference))
    tolerance = context.add(
        Decimal("1e-9"),
        context.multiply(Decimal("1e-9"), abs(reference)),
    )
    return float(context.divide(error, tolerance))

"""流式统计聚合引擎（只用标准库）。

公开接口
--------
- ``StreamStats``：一次遍历的聚合器。逐行喂数 ``add(value, literal=None)``，
  最后取报告 ``report(source=None)``；除固定数量的累加量和固定桶表外不留任何元素。
- ``bucket_key(x)``：README 第二节写死的分桶口径，返回 ``(符号, e, d)``，零为 ``(0, 0, 0)``。
- ``QUANTILE_POINTS``、``TOLERANCE_ABSOLUTE``、``TOLERANCE_RELATIVE``：口径常量。

交付口径（stable）：均值用 Neumaier 补偿求和，总体方差用 Welford 递推并对 M2 补偿累加。
对比口径 naive / shifted 只在需要时（生成页面）一起维护，定义见 README 第四节。
口径的权威描述与容差见 README.md 第二节；复现验收的命令见 USAGE.md。
"""

import math
from bisect import bisect_right
from decimal import Context, Decimal

TOLERANCE_ABSOLUTE = 1e-9
TOLERANCE_RELATIVE = 1e-9

QUANTILE_POINTS = (("p10", 0.10), ("p50", 0.50), ("p90", 0.90), ("p99", 0.99))

_REFERENCE_PRECISION = 60


def bucket_key(x):
    """按 README 第二节把一个 float 分进固定桶。

    正数取整数 e 使 10^e <= x < 10^(e+1)，首位 d = floor(x / 10^e)，键 (1, e, d)；
    负数对 |x| 同样分桶，键 (-1, e, d)；零单独一桶 (0, 0, 0)。
    10^e 由 float 重算时可能落在真实边界另一侧一档，故分桶后做一次边界校正。
    """
    if x == 0.0:
        return (0, 0, 0)
    if x > 0.0:
        sign = 1
        a = x
    else:
        sign = -1
        a = -x
    e = int(math.floor(math.log10(a)))
    low = 10.0 ** e
    if a < low:
        e -= 1
        low = 10.0 ** e
    elif a >= low * 10.0:
        e += 1
        low = 10.0 ** e
    d = int(a / low)
    if d < 1:
        d = 1
    elif d > 9:
        d = 9
    return (sign, e, d)


def _bucket_sort_key(key):
    """桶按代表值升序：负桶在前、零居中、正桶在后；同符号按 (e, d) 排。"""
    sign, e, d = key
    return (sign, sign * e, sign * d)


class _NeumaierSum:
    """Neumaier（Kahan-Babuska）补偿求和：常量内存，一次遍历。"""

    __slots__ = ("sum", "comp")

    def __init__(self):
        self.sum = 0.0
        self.comp = 0.0

    def add(self, x):
        s = self.sum
        t = s + x
        if abs(s) >= abs(x):
            self.comp += (s - t) + x
        else:
            self.comp += (x - t) + s
        self.sum = t

    def value(self):
        return self.sum + self.comp


class _NaiveAcc:
    """naive 口径：按输入顺序 float 直接累加 Σx 与 Σx²。"""

    __slots__ = ("n", "s", "s2")

    def __init__(self):
        self.n = 0
        self.s = 0.0
        self.s2 = 0.0

    def add(self, x):
        self.n += 1
        self.s += x
        self.s2 += x * x

    def mean(self):
        return self.s / self.n

    def variance(self):
        m = self.s / self.n
        return self.s2 / self.n - m * m


class _ShiftedAcc:
    """shifted 口径：以第一个数为平移量 k，累加 Σ(x−k) 与 Σ(x−k)²。"""

    __slots__ = ("n", "k", "s", "s2")

    def __init__(self):
        self.n = 0
        self.k = 0.0
        self.s = 0.0
        self.s2 = 0.0

    def add(self, x):
        if self.n == 0:
            self.k = x
        self.n += 1
        d = x - self.k
        self.s += d
        self.s2 += d * d

    def mean(self):
        return self.k + self.s / self.n

    def variance(self):
        center = self.s / self.n
        return self.s2 / self.n - center * center


class _StableAcc:
    """stable 口径：Neumaier 补偿求和给均值，Welford + M2 补偿累加给总体方差。"""

    __slots__ = ("n", "sum", "sum_comp", "wmean", "m2", "m2_comp")

    def __init__(self):
        self.n = 0
        self.sum = 0.0
        self.sum_comp = 0.0
        self.wmean = 0.0
        self.m2 = 0.0
        self.m2_comp = 0.0

    def add(self, x):
        self.n += 1

        s = self.sum
        t = s + x
        if abs(s) >= abs(x):
            self.sum_comp += (s - t) + x
        else:
            self.sum_comp += (x - t) + s
        self.sum = t

        delta = x - self.wmean
        self.wmean += delta / self.n
        term = delta * (x - self.wmean)
        m = self.m2
        t2 = m + term
        if abs(m) >= abs(term):
            self.m2_comp += (m - t2) + term
        else:
            self.m2_comp += (term - t2) + m
        self.m2 = t2

    def mean(self):
        return (self.sum + self.sum_comp) / self.n

    def variance(self):
        return (self.m2 + self.m2_comp) / self.n


class _ReferenceAcc:
    """用 decimal 60 位精度在同一遍输入里累加的高精度参考值。"""

    __slots__ = ("n", "s", "s2", "ctx", "one_e_minus_9")

    def __init__(self):
        self.n = 0
        self.ctx = Context(prec=_REFERENCE_PRECISION)
        self.s = Decimal(0)
        self.s2 = Decimal(0)
        self.one_e_minus_9 = Decimal("1e-9")

    def add_literal(self, literal):
        ctx = self.ctx
        d = Decimal(literal)
        self.s = ctx.add(self.s, d)
        self.s2 = ctx.add(self.s2, ctx.multiply(d, d))
        self.n += 1

    def values(self):
        ctx = self.ctx
        n = Decimal(self.n)
        mean = ctx.divide(self.s, n)
        variance = ctx.subtract(ctx.divide(self.s2, n),
                                ctx.multiply(mean, mean))
        return mean, variance

    def error_ratio(self, algo_value, ref):
        ctx = self.ctx
        diff = abs(Decimal(repr(float(algo_value))) - ref)
        denom = ctx.add(self.one_e_minus_9,
                        ctx.multiply(self.one_e_minus_9, abs(ref)))
        return float(ctx.divide(diff, denom))


class BucketTable:
    """固定桶表：键 (符号, e, d) -> [个数, 总和, 补偿量]，桶数与 n 无关。"""

    __slots__ = ("_buckets",)

    def __init__(self):
        self._buckets = {}

    def add(self, x):
        key = bucket_key(x)
        entry = self._buckets.get(key)
        if entry is None:
            self._buckets[key] = [1, x, 0.0]
            return
        entry[0] += 1
        s = entry[1]
        t = s + x
        if abs(s) >= abs(x):
            entry[2] += (s - t) + x
        else:
            entry[2] += (x - t) + s
        entry[1] = t

    def quantiles(self, n, minimum, maximum):
        ordered = sorted(self._buckets.items(), key=lambda item: _bucket_sort_key(item[0]))
        cumulative = []
        representatives = []
        total = 0
        for _key, entry in ordered:
            count, total_sum, comp = entry
            total += count
            cumulative.append(total)
            representatives.append((total_sum + comp) / count)

        result = {}
        for name, p in QUANTILE_POINTS:
            rank = p * (n - 1)
            i = int(math.floor(rank))
            f = rank - i
            a = representatives[bisect_right(cumulative, i)]
            if i + 1 >= n:
                b = a
            else:
                b = representatives[bisect_right(cumulative, i + 1)]
            q = (1.0 - f) * a + f * b
            if q < minimum:
                q = minimum
            elif q > maximum:
                q = maximum
            result[name] = q
        return result


class StreamStats:
    """一次遍历的流式统计聚合器。

    用法（典型：逐行读文件，不收集元素）::

        stats = StreamStats(compare_algorithms=False, with_reference=False)
        for line in f:
            stats.add(float(line.strip()), line.strip())  # 第二个参数仅参考值需要
        report = stats.report()

    - ``compare_algorithms``：额外维护 naive / shifted 两套 float 口径；
    - ``with_reference``：用 decimal 60 位精度顺带累加参考值（add 时给字面量）。
      两个开关只在生成 stability.html 时打开；默认报告走纯 float 的 stable 口径。
    """

    def __init__(self, compare_algorithms=False, with_reference=False):
        self.count = 0
        self.min = None
        self.max = None
        self._stable = _StableAcc()
        self._buckets = BucketTable()
        self._compare = compare_algorithms
        self._naive = _NaiveAcc() if compare_algorithms else None
        self._shifted = _ShiftedAcc() if compare_algorithms else None
        self._reference = _ReferenceAcc() if with_reference else None

    def add(self, value, literal=None):
        if type(value) is not float:
            value = float(value)
        self.count += 1
        if self.count == 1:
            self.min = value
            self.max = value
        else:
            if value < self.min:
                self.min = value
            if value > self.max:
                self.max = value
        self._stable.add(value)
        self._buckets.add(value)
        if self._compare:
            self._naive.add(value)
            self._shifted.add(value)
        if self._reference is not None:
            self._reference.add_literal(literal if literal is not None else repr(value))

    def report(self, source=None):
        n = self.count
        if n == 0:
            raise ValueError("stream is empty: no numbers to aggregate")
        mean = self._stable.mean()
        variance = self._stable.variance()
        if n == 1:
            variance = 0.0
        report = {
            "count": n,
            "min": self.min,
            "max": self.max,
            "mean": mean,
            "variance": variance,
            "quantiles": self._buckets.quantiles(n, self.min, self.max),
            "tolerance": {
                "absolute": TOLERANCE_ABSOLUTE,
                "relative": TOLERANCE_RELATIVE,
            },
        }
        if self._compare:
            ref_mean = ref_variance = None
            if self._reference is not None:
                ref_mean, ref_variance = self._reference.values()
                report["reference"] = {
                    "mean": float(ref_mean),
                    "variance": float(ref_variance),
                }

            def algorithm(name, acc):
                algo_mean = acc.mean()
                algo_variance = acc.variance()
                entry = {"name": name, "mean": algo_mean, "variance": algo_variance}
                if self._reference is not None:
                    entry["mean_error_ratio"] = self._reference.error_ratio(
                        algo_mean, ref_mean)
                    entry["variance_error_ratio"] = self._reference.error_ratio(
                        algo_variance, ref_variance)
                else:
                    entry["mean_error_ratio"] = 0.0
                    entry["variance_error_ratio"] = 0.0
                return entry

            report["algorithms"] = [
                algorithm("naive", self._naive),
                algorithm("shifted", self._shifted),
                algorithm("stable", self._stable),
            ]
        if source is not None:
            report["source"] = source
        return report

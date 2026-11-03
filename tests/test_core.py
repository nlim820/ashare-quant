"""核心逻辑单元测试（标准库 unittest，零额外依赖）。

运行：
    python -m unittest discover -s tests -v
    python -m unittest tests.test_core -v

为什么一个学生项目也要写测试：
- 这个项目最怕的不是"策略不赚钱"，而是"某天改了个小地方，论文里的数字悄悄变了"。
  测试锁住的是**口径**：夏普怎么算、印花税什么时候 0.1%、整手怎么取整、
  相关系数怎么折算。这些一旦漂移，结论就不可复现。
- 顺带的好处：答辩被问"你怎么保证代码是对的"，可以直接跑测试给对方看。
"""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# 允许从仓库根目录运行，也允许从 tests/ 运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import backtrader as bt

from data_utils import check_quality, is_fund, add_ma, _write_meta, _read_meta, _is_stale
from phase2_backtest import (compute_metrics, _ols_alpha, RealisticCommInfo,
                             STAMP_TAX_CUT, STAMP_TAX_OLD, STAMP_TAX_NEW, run)
from robust_stats import (paired_t, effective_sample_size, max_drawdown, perf,
                          block_bootstrap_delta)


class TestMetrics(unittest.TestCase):
    def test_zero_returns(self):
        """全 0 收益：年化 0、回撤 0（夏普因标准差为 0 应返回 0 而非 NaN）。"""
        r = pd.Series([0.0] * 252)
        m = compute_metrics(r)
        self.assertAlmostEqual(m["ann"], 0.0, places=10)
        self.assertAlmostEqual(m["max_dd"], 0.0, places=10)
        self.assertEqual(m["sharpe"], 0.0)

    def test_known_annualization(self):
        """25 天每日 +1% → 复利年化应为 1.01^252 - 1，而不是 ×252 的近似。"""
        r = pd.Series([0.01] * 25)
        m = compute_metrics(r)
        expect = 1.01 ** 252 - 1
        self.assertAlmostEqual(m["ann"], expect, places=8)

    def test_sharpe_rf(self):
        """rf>0 时夏普必须下降；下降量 = rf_daily/std*sqrt(252)。"""
        rng = np.random.default_rng(0)
        r = pd.Series(rng.normal(0.001, 0.01, 500))
        s0 = compute_metrics(r, rf_annual=0.0)["sharpe"]
        s1 = compute_metrics(r, rf_annual=0.02)["sharpe"]
        expect_drop = (0.02 / 252.0) / r.std() * math.sqrt(252.0)
        self.assertGreater(s0, s1)
        self.assertAlmostEqual(s0 - s1, expect_drop, places=8)

    def test_max_drawdown(self):
        """净值 1 → 1.2 → 0.6：回撤应为 0.6/1.2 - 1 = -50%。"""
        r = pd.Series([0.2, -0.5])
        self.assertAlmostEqual(compute_metrics(r)["max_dd"], -0.5, places=10)


class TestMA(unittest.TestCase):
    def test_rolling_and_nan_prefix(self):
        df = pd.DataFrame({"收盘": list(range(1, 11))})
        out = add_ma(df, windows=(3,))
        # 前 2 个必为 NaN，第 3 个是 (1+2+3)/3 = 2
        self.assertTrue(out["MA3"].iloc[:2].isna().all())
        self.assertAlmostEqual(out["MA3"].iloc[2], 2.0)
        self.assertAlmostEqual(out["MA3"].iloc[-1], 9.0)


class TestFundDetection(unittest.TestCase):
    def test_codes(self):
        for c in ("510300", "159915", "501050", "588000"):
            self.assertTrue(is_fund(c), c)
        for c in ("600519", "000001", "300750", "688981"):
            self.assertFalse(is_fund(c), c)
        # 非 6 位数字一律不认作基金
        self.assertFalse(is_fund("sh510300"))
        self.assertFalse(is_fund("51030"))


class TestStatistics(unittest.TestCase):
    def test_paired_t_known(self):
        """差值恒为 2、无波动 → t 发散（方差 0），函数应安全返回 p=1 而非崩溃。"""
        m, t, p = paired_t([2.0] * 10)
        self.assertAlmostEqual(m, 2.0)
        self.assertEqual(p, 1.0)

    def test_paired_t_direction(self):
        m, t, p = paired_t([1, 2, 3, 4, 5, 6, 7, 8])
        self.assertGreater(t, 0)
        self.assertLess(p, 0.01)

    def test_effective_n_perfectly_correlated(self):
        """完全线性相关的 5 条序列，等效独立样本应约为 1。"""
        rng = np.random.default_rng(1)
        base = rng.normal(0, 0.01, 300)
        df = pd.DataFrame({f"s{i}": base * (i + 1) for i in range(5)})
        rho, n_eff, n = effective_sample_size(df)
        self.assertEqual(n, 5)
        self.assertGreater(rho, 0.99)
        self.assertLess(n_eff, 1.05)

    def test_effective_n_independent(self):
        """独立序列的 ρ̄≈0，n_eff 应接近 n。"""
        rng = np.random.default_rng(2)
        df = pd.DataFrame({f"s{i}": rng.normal(0, 0.01, 2000) for i in range(6)})
        rho, n_eff, n = effective_sample_size(df)
        self.assertLess(abs(rho), 0.1)
        self.assertGreater(n_eff, 0.8 * n)

    def test_bootstrap_identical_series(self):
        """两条完全相同的序列：Δ 点估计必为 0，bootstrap 也应基本为 0。"""
        rng = np.random.default_rng(3)
        s = pd.Series(rng.normal(0.0005, 0.01, 400))
        df = pd.DataFrame({"base": s, "filter": s})
        out = block_bootstrap_delta(df, n_boot=200, block=20, seed=1)
        self.assertAlmostEqual(out["dd"]["obs"], 0.0, places=12)
        self.assertAlmostEqual(out["ann"]["obs"], 0.0, places=12)
        # 同样的序列，Δ 不可能"显著改善"
        self.assertGreater(out["dd"]["p_one"], 0.4)

    def test_perf_and_drawdown_consistency(self):
        rng = np.random.default_rng(4)
        s = pd.Series(rng.normal(0.0002, 0.012, 500))
        p = perf(s)
        self.assertAlmostEqual(p["maxdd"], max_drawdown(s), places=12)
        self.assertLessEqual(p["maxdd"], 0.0)


class TestStampTax(unittest.TestCase):
    """印花税跨期：2023-08-28 前卖出 0.1%，之后 0.05%。"""

    def setUp(self):
        self.ci = RealisticCommInfo(commtype=bt.CommInfoBase.COMM_PERC)

    def test_before_cut(self):
        self.ci.set_date(pd.Timestamp("2020-06-01").date())
        self.assertAlmostEqual(self.ci._stamp_tax(), STAMP_TAX_OLD)

    def test_after_cut(self):
        self.ci.set_date(pd.Timestamp("2023-09-01").date())
        self.assertAlmostEqual(self.ci._stamp_tax(), STAMP_TAX_NEW)

    def test_boundary_is_inclusive_new(self):
        """分界日当天即执行新税率（政策 2023-08-28 起实施）。"""
        self.ci.set_date(STAMP_TAX_CUT)
        self.assertAlmostEqual(self.ci._stamp_tax(), STAMP_TAX_NEW)

    def test_unknown_date_falls_back_and_counts(self):
        self.assertAlmostEqual(self.ci._stamp_tax(), STAMP_TAX_NEW)
        self.assertEqual(self.ci.unknown_date_calls, 1)

    def test_sell_costs_more_than_buy(self):
        """卖出多一笔印花税，佣金必须更高；且金额与 size*price 成正比。"""
        self.ci.set_date(pd.Timestamp("2023-09-01").date())
        buy = self.ci._getcommission(100, 10.0, False)
        sell = self.ci._getcommission(-100, 10.0, False)
        self.assertGreater(sell, buy)
        self.assertAlmostEqual(sell, 100 * 10.0 * (0.0005 + 0.001 + 0.00001 + 0.0005))


class TestQualityCheck(unittest.TestCase):
    def _df(self, dates, close=10.0):
        return pd.DataFrame({
            "日期": dates, "开盘": close, "最高": close, "最低": close,
            "收盘": close, "成交量": 1000,
        })

    def test_clean_passes(self):
        df = self._df(pd.bdate_range("2023-01-02", periods=40))
        self.assertEqual(check_quality(df, "TEST"), [])

    def test_duplicate_dates(self):
        d = list(pd.bdate_range("2023-01-02", periods=40))
        d[5] = d[4]
        issues = check_quality(self._df(d), "TEST")
        self.assertTrue(any("重复" in x for x in issues), issues)

    def test_non_positive_price(self):
        df = self._df(pd.bdate_range("2023-01-02", periods=40))
        df.loc[3, "收盘"] = 0.0
        issues = check_quality(df, "TEST")
        self.assertTrue(any("非正价格" in x for x in issues), issues)

    def test_ohlc_contradiction(self):
        df = self._df(pd.bdate_range("2023-01-02", periods=40))
        df.loc[7, "最高"] = 5.0     # 最高 < 收盘
        issues = check_quality(df, "TEST")
        self.assertTrue(any("OHLC" in x for x in issues), issues)

    def test_spring_festival_not_flagged(self):
        """春节休市约 11 天，不应被误报为数据缺口（阈值 15 天）。"""
        d = list(pd.bdate_range("2020-01-02", periods=20)) + \
            list(pd.bdate_range("2020-02-10", periods=20))
        issues = check_quality(self._df(pd.to_datetime(d)), "TEST")
        self.assertFalse(any("缺口" in x for x in issues), issues)

    def test_too_few_rows(self):
        issues = check_quality(self._df(pd.bdate_range("2023-01-02", periods=5)), "TEST")
        self.assertTrue(any("样本过少" in x for x in issues), issues)


class TestCacheMeta(unittest.TestCase):
    def test_roundtrip_and_staleness(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.csv"
            df = pd.DataFrame({"日期": pd.bdate_range("2023-01-02", periods=5),
                               "开盘": 1.0, "最高": 1.0, "最低": 1.0,
                               "收盘": 1.0, "成交量": 1})
            df.attrs["adjust"] = "qfq"
            df.attrs["source_used"] = "em"
            df.to_csv(path, index=False)
            meta = _write_meta(path, df, "auto", "TEST")
            self.assertEqual(meta["rows"], 5)
            back = _read_meta(path)
            self.assertEqual(back["symbol"], "TEST")
            self.assertFalse(_is_stale(back, 30))          # 刚写入 → 新鲜
            self.assertTrue(_is_stale(back, -1))           # 负 TTL → 一律过期
            self.assertFalse(_is_stale(None, 30))          # 无元数据 = 种子快照，不算过期

    def test_missing_meta_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(_read_meta(Path(td) / "nope.csv"))


class TestOLSAlpha(unittest.TestCase):
    def test_recovers_known_alpha_and_beta(self):
        """构造 y = 0.001 + 0.5x + 小噪声，应能还原 α≈0.001、β≈0.5。"""
        rng = np.random.default_rng(7)
        x = pd.Series(rng.normal(0.0002, 0.01, 1500))
        y = 0.001 + 0.5 * x + pd.Series(rng.normal(0, 0.0005, 1500))
        out = _ols_alpha(y, x)
        self.assertAlmostEqual(out["beta"], 0.5, places=1)
        self.assertAlmostEqual(out["alpha_d"], 0.001, places=3)
        self.assertGreater(out["t"], 3)
        self.assertLess(out["p"], 0.01)

    def test_short_sample_returns_none(self):
        out = _ols_alpha(pd.Series([0.01] * 10), pd.Series([0.01] * 10))
        self.assertIsNone(out["alpha_ann"])


@unittest.skipUnless(
    (Path(__file__).resolve().parents[1] / "data/raw/600519_20200101_20231231_qfq.csv").exists(),
    "缺少种子缓存数据，跳过整手约束集成测试")
class TestLotSizerIntegration(unittest.TestCase):
    """整手约束的端到端行为（依赖仓库内种子数据，不联网）。"""

    def test_high_price_stock_blocked_by_lot(self):
        """茅台 ~1000-2000 元/股，10 万本金仅够在 2020-03 暴跌时勉强买 1 手。

        期望：入场次数被压到 ≤1（基准 28 次），年化≈0（几乎全程空仓）。
        这条测试锁的是"整手约束真的生效"，而不是"一定能买/一定买不到"——
        具体能不能买到取决于当日价格，写死 0 会随数据快照漂移。
        """
        r = run("600519", "20200101", "20231231", 5, 20, verbose=False,
                lot_size=100, cash=100000.0)
        self.assertIsNotNone(r)
        self.assertLessEqual(r["n_trades"], 1)
        self.assertLess(abs(r["strat_ann"]), 0.02)

    def test_large_cash_restores_trading(self):
        r = run("600519", "20200101", "20231231", 5, 20, verbose=False,
                lot_size=100, cash=1000000.0)
        self.assertGreater(r["n_trades"], 0)

    def test_default_unchanged(self):
        """默认（不传 lot_size）必须仍允许小数股，且与历史数字一致。"""
        r = run("600519", "20200101", "20231231", 5, 20, verbose=False)
        self.assertEqual(r["n_trades"], 28)
        self.assertAlmostEqual(r["strat_ann"], 0.1541, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

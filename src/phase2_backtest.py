"""Phase 2：双均线（MA5/MA20）金叉死叉策略回测。

做什么：
- 用 backtrader 框架，把均线信号变成可执行的交易：
    金叉（MA5 上穿 MA20）→ 买入；死叉（MA5 下穿 MA20）→ 清仓。
- 回测一段时间，输出三个量化核心指标：年化收益、夏普比率、最大回撤。
- 与"买入持有（buy & hold）"对比，判断策略是否真有超额价值。

指标公式（面试被问到要能脱口而出）：
- 年化收益 = (1+总收益)^(252/交易日数) - 1
- 夏普比率 = 日均收益 / 日收益波动 * √252   （无风险利率取 0，A股常用近似）
- 最大回撤 = max( 区间内 峰值到谷值 的最大跌幅 )，衡量最惨会亏多少

用法：
    python src/phase2_backtest.py --symbol 600519 --start 20200101 --end 20231231
"""
import argparse
import math
import pandas as pd
import backtrader as bt
from data_utils import get_price, add_ma


class DualMA(bt.Strategy):
    """双均线交叉策略：金叉买入、死叉清仓。"""
    params = dict(fast=5, slow=20)

    def __init__(self):
        self.ma_fast = bt.ind.SMA(self.data.close, period=self.p.fast)
        self.ma_slow = bt.ind.SMA(self.data.close, period=self.p.slow)
        # CrossOver > 0 表示快线上穿慢线（金叉）；< 0 表示下穿（死叉）
        self.crossover = bt.ind.CrossOver(self.ma_fast, self.ma_slow)
        self.order = None

    def notify_order(self, order):
        # 订单完成/取消后才允许下一次下单，避免重复发单
        if order.status in (order.Completed, order.Canceled, order.Margin):
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()        # 金叉：满仓买入
        else:
            if self.crossover < 0:
                self.order = self.close()      # 死叉：清仓


def compute_metrics(daily_ret: pd.Series) -> dict:
    """从日收益序列计算年化收益、夏普、最大回撤。"""
    equity = (1.0 + daily_ret).cumprod()          # 资金曲线
    total = equity.iloc[-1] - 1.0
    n = len(daily_ret)
    ann = equity.iloc[-1] ** (252.0 / n) - 1.0
    sharpe = daily_ret.mean() / daily_ret.std() * math.sqrt(252.0)
    max_dd = ((equity / equity.cummax()) - 1.0).min()
    return dict(total=total, ann=ann, sharpe=sharpe, max_dd=max_dd)


def run(symbol: str, start: str, end: str, fast: int = 5, slow: int = 20,
        verbose: bool = True) -> dict | None:
    """对单只股票跑回测；verbose=False 时只返回结果字典（供批量调用）。"""
    try:
        df = get_price(symbol, start, end, "qfq")
    except Exception as e:
        if verbose:
            print(f"   ⚠️ {symbol} 获取行情失败，跳过：{e}")
        return None

    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").set_index("日期")
    df = add_ma(df, windows=(fast, slow)).dropna(subset=[f"MA{fast}", f"MA{slow}"])
    if verbose:
        print(f"   有效交易日：{len(df)} 天")

    data = bt.feeds.PandasData(
        dataname=df, open="开盘", high="最高", low="最低",
        close="收盘", volume="成交量", openinterest=-1,
    )
    cerebro = bt.Cerebro()
    cerebro.addstrategy(DualMA, fast=fast, slow=slow)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0005)   # 单边万 5 手续费
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)

    result = cerebro.run()
    tr = pd.Series(result[0].analyzers.tr.get_analysis())
    strat = compute_metrics(tr)

    close = df["收盘"]
    bh = compute_metrics(close.pct_change().dropna())
    bh_total = close.iloc[-1] / close.iloc[0] - 1.0

    if verbose:
        print("\n" + "=" * 56)
        print(f"回测标的：{symbol} ｜ 策略：MA{fast}/{slow} 双均线交叉")
        print("=" * 56)
        print(f"{'指标':<10}{'双均线策略':>16}{'买入持有':>16}")
        print("-" * 56)
        print(f"{'总收益':<10}{strat['total']*100:>15.2f}%{bh_total*100:>15.2f}%")
        print(f"{'年化收益':<10}{strat['ann']*100:>15.2f}%{bh['ann']*100:>15.2f}%")
        print(f"{'夏普比率':<10}{strat['sharpe']:>16.2f}{bh['sharpe']:>16.2f}")
        print(f"{'最大回撤':<10}{strat['max_dd']*100:>15.2f}%{bh['max_dd']*100:>15.2f}%")
        print("-" * 56)
        verdict = "策略跑赢买入持有 ✅" if strat["ann"] > bh["ann"] else "策略未跑赢买入持有 ⚠️"
        print(verdict)

    return dict(
        symbol=symbol, n=len(df),
        strat_total=strat["total"], strat_ann=strat["ann"],
        strat_sharpe=strat["sharpe"], strat_maxdd=strat["max_dd"],
        bh_total=bh_total, bh_ann=bh["ann"],
        bh_sharpe=bh["sharpe"], bh_maxdd=bh["max_dd"],
        beat=strat["ann"] > bh["ann"],
    )


def main() -> None:
    p = argparse.ArgumentParser(description="双均线策略回测（单标的）")
    p.add_argument("--symbol", default="600519")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20231231")
    p.add_argument("--fast", type=int, default=5)
    p.add_argument("--slow", type=int, default=20)
    args = p.parse_args()
    run(args.symbol, args.start, args.end, args.fast, args.slow, verbose=True)


if __name__ == "__main__":
    main()

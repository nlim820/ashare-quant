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
from data_utils import get_price, add_ma, get_index


class DualMA(bt.Strategy):
    """双均线交叉策略：金叉买入、死叉清仓。

    可选趋势过滤（filter_ma）：仅在「收盘价 > 长期均线」时允许金叉买入，
    相当于给入场加一道"安检"，过滤掉长期下行趋势中的假金叉。
    死叉清仓规则不变（门控式过滤，只改入场、不改出场）。
    filter_ma 默认 None = 不启用，行为与旧版完全一致（向后兼容）。
    """
    params = dict(fast=5, slow=20, filter_ma=None)

    def __init__(self):
        self.ma_fast = bt.ind.SMA(self.data.close, period=self.p.fast)
        self.ma_slow = bt.ind.SMA(self.data.close, period=self.p.slow)
        # CrossOver > 0 表示快线上穿慢线（金叉）；< 0 表示下穿（死叉）
        self.crossover = bt.ind.CrossOver(self.ma_fast, self.ma_slow)
        # 趋势过滤线：None 表示不启用；否则是一条更慢的长期均线（如 240 日）
        self.ma_filter = (bt.ind.SMA(self.data.close, period=self.p.filter_ma)
                          if self.p.filter_ma else None)
        self.order = None
        self.trade_count = 0   # 统计实际买入（入场）次数

    def notify_order(self, order):
        # 订单完成/取消后才允许下一次下单，避免重复发单
        if order.status in (order.Completed, order.Canceled, order.Margin):
            self.order = None

    def next(self):
        if self.order:
            return
        if not self.position:
            # 入场：金叉 + 趋势过滤（收盘价在长期趋势线上方才视为"可买"）
            if self.crossover > 0 and self._trend_ok():
                self.order = self.buy()        # 金叉且趋势向上：满仓买入
                self.trade_count += 1
        else:
            if self.crossover < 0:
                self.order = self.close()      # 死叉：清仓（出场规则不变）

    def _trend_ok(self) -> bool:
        """趋势过滤闸门：未启用过滤时恒真；启用时要求收盘价在长期均线上方。"""
        if self.ma_filter is None:
            return True
        return self.data.close[0] > self.ma_filter[0]


class InMarket(bt.Analyzer):
    """统计「持仓天数占比」：评估窗口内有多少比例的交易日处于持仓状态。

    用途：趋势过滤可能让回撤变小——但这可能是因为"在场时间变短"
    （少交易、多空仓），而非策略变聪明。必须同时看持仓占比，才能
    区分"风险真降低"还是"只是少冒了险"。
    """
    params = dict(start_bar=0)

    def start(self):
        self.bar = -1
        self.in_market = 0
        self.total = 0

    def next(self):
        self.bar += 1
        if self.bar < self.p.start_bar:
            return
        self.total += 1
        if self.strategy.position:
            self.in_market += 1

    def get_analysis(self):
        return dict(
            ratio=self.in_market / self.total if self.total else 0.0,
            in_market=self.in_market,
            total=self.total,
        )


class RealisticCommInfo(bt.CommissionInfo):
    """真实成本模型（可选，仅在 run(cost_model='realistic') 时启用）。

    默认 run(cost_model='simple') 行为【完全不变】（仅单边万5佣金，与旧版一致）。
    本类把 A 股真实摩擦成本显式计入，用于论文「成本稳健性」检验：
      - 佣金：双边 万5        (0.0005)
      - 滑点：双边 0.1%       (0.001)，以「比例交易成本」近似建模（非价格冲击）
      - 印花税：单边卖出 0.05% (0.0005)
      - 过户费：双边 约万0.1  (0.00001)，沪市；此处对所有标的近似计入
    实现要点（踩坑记录，避免后人重蹈）：
      - backtrader 实际算佣金的方法是 ``_getcommission``（返回【绝对金额】），
        而非 ``getcommission``；必须覆盖前者，并在内部乘上 abs(size)*price。
      - 费率直接写死在此方法内（不依赖基类 params 合并，避免被默认 0 覆盖）。
    """
    def _getcommission(self, size, price, pseudoexec):
        # 双边固定摩擦 = 佣金万5 + 滑点0.1% + 过户费万0.1
        c = 0.0005 + 0.001 + 0.00001
        if size < 0:          # 印花税 0.05%（仅卖出）
            c += 0.0005
        return abs(size) * c * price   # 返回绝对佣金金额


def compute_metrics(daily_ret: pd.Series) -> dict:
    """从日收益序列计算年化收益、夏普、最大回撤。"""
    equity = (1.0 + daily_ret).cumprod()          # 资金曲线
    total = equity.iloc[-1] - 1.0
    n = len(daily_ret)
    ann = equity.iloc[-1] ** (252.0 / n) - 1.0
    std = daily_ret.std()
    sharpe = daily_ret.mean() / std * math.sqrt(252.0) if std and std > 0 else 0.0
    max_dd = ((equity / equity.cummax()) - 1.0).min()
    return dict(total=total, ann=ann, sharpe=sharpe, max_dd=max_dd)


def run(symbol: str, start: str, end: str, fast: int = 5, slow: int = 20,
        verbose: bool = True, warmup: int = None, adjust: str = "qfq",
        source: str = "auto", filter_ma: int = None,
        eval_start: str = None, cost_model: str = "simple") -> dict | None:
    """对单只股票跑回测；verbose=False 时只返回结果字典（供批量调用）。

    warmup：对齐参数。传入时，策略日收益与买入持有都截到「第 warmup 个交易
    日」为统一评估起点，使不同参数组在【完全相同】的窗口上比较（否则慢线越
    大、策略可交易起点越后移，买入持有基准口径会漂移，导致跨参数不可比）。

    filter_ma：趋势过滤线周期（如 240）。启用时评估窗口会自动后移到
    max(warmup, filter_ma)，保证过滤线就绪后才开始比较，否则窗口不一致。

    eval_start：样本外检验专用。传入具体日期（如 "20240101"）时，数据仍从
    start 拉取（提供历史均线预热），但【评估窗口与指数基准】都从该日期起算。
    这样可用 2020-2023 作历史预热、2024 起作样本外，模拟"带训练期参数直接
    应用到新数据"的真实场景。eval_start 与 warmup 互斥：传 eval_start 时以它为准。
    """
    try:
        raw = get_price(symbol, start, end, adjust, source)
    except Exception as e:
        if verbose:
            print(f"   ⚠️ {symbol} 获取行情失败，跳过：{e}")
        return None

    raw["日期"] = pd.to_datetime(raw["日期"])
    raw = raw.sort_values("日期").set_index("日期")
    raw = add_ma(raw, windows=(fast, slow))   # 加均线列（前导为 NaN）

    # 统一评估起点：既支持 warmup（第 N 个交易日），也支持 eval_start（具体日期）。
    # 两者互斥：传 eval_start 时以它为准（用于样本外检验）。
    if eval_start is not None:
        # 样本外：数据从 start 拉全量（历史预热），评估从 eval_start 起
        es_dt = pd.Timestamp(eval_start)
        if es_dt in raw.index:
            start_bar = raw.index.get_loc(es_dt)
        else:
            after = raw.index[raw.index >= es_dt]
            start_bar = raw.index.get_loc(after[0]) if len(after) else len(raw) - 1
        # 过滤线比评估起点还长时，须进一步后移，保证过滤线就绪
        if filter_ma and filter_ma > start_bar:
            start_bar = filter_ma
    else:
        eff_warmup = warmup
        if filter_ma:
            eff_warmup = max(eff_warmup if eff_warmup is not None else 0, filter_ma)
        start_bar = eff_warmup if eff_warmup is not None else 0
    eval_start_date = raw.index[start_bar] if start_bar > 0 else raw.index[0]

    # 用完整数据喂回测：策略会等自己的均线就绪后才交易（前段自动空仓）
    data = bt.feeds.PandasData(
        dataname=raw, open="开盘", high="最高", low="最低",
        close="收盘", volume="成交量", openinterest=-1,
    )
    cerebro = bt.Cerebro()
    cerebro.addstrategy(DualMA, fast=fast, slow=slow, filter_ma=filter_ma)
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    # 成本模型：默认 'simple' = 仅单边万5佣金（与旧版完全一致，简历数字不受影响）；
    # 'realistic' = 佣金+滑点+印花税+过户费（论文成本稳健性检验用，需显式指定）。
    if cost_model == "realistic":
        # 显式传 commtype=COMM_PERC（按比例计）。CommInfoBase 默认 commtype=None
        # 时若 margin 为空会按 stocklike 判定，本类 stocklike 默认 False 会落到
        # COMM_FIXED，把返回的费率误当作「每股固定金额」→ 成本被算成近似 0。
        cerebro.broker.addcommissioninfo(
            RealisticCommInfo(commtype=bt.CommInfoBase.COMM_PERC))
    else:
        cerebro.broker.setcommission(commission=0.0005)   # 单边万 5 手续费
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(InMarket, _name="im", start_bar=start_bar)  # 持仓天数占比

    result = cerebro.run()
    tr_full = pd.Series(result[0].analyzers.tr.get_analysis())   # 全周期日收益

    # —— 统一评估窗口（基于上面算出的 eval_start_date）——
    tr = tr_full.loc[eval_start_date:].dropna()
    close_eval = raw["收盘"].loc[eval_start_date:]
    n = len(tr)
    if verbose:
        es_note = f" ｜ 评估起点 {eval_start_date.date()}" if eval_start else ""
        print(f"   评估窗口交易日：{n} 天{es_note}")

    strat = compute_metrics(tr)
    bh_tr = close_eval.pct_change().dropna()
    bh = compute_metrics(bh_tr)
    bh_total = close_eval.iloc[-1] / close_eval.iloc[0] - 1.0

    # 持仓天数占比 + 入场次数（趋势过滤后这两项会变，必须一并看）
    im = result[0].analyzers.im.get_analysis()
    hold_ratio = im["ratio"]
    n_trades = result[0].trade_count

    # —— 沪深300 指数基准：判断策略是否真有「市场 alpha」——
    # 仅仅跑赢「同标的买入持有」不够，必须跑赢「市场」才算有 alpha。
    # 用 CAPM 近似：alpha ≈ 策略年化 − Beta × 指数年化（无风险利率取 0）。
    idx_ann = idx_beta = idx_alpha = None
    try:
        idx_df = get_index("sh000300", eval_start_date.strftime("%Y%m%d"), end)
        idx_close = idx_df.set_index("日期")["收盘"]
        idx_eval = idx_close.reindex(tr.index).dropna()
        common = tr.index.intersection(idx_eval.index)
        s_ret = tr.loc[common]
        i_ret = idx_eval.loc[common].pct_change().dropna()
        s_ret = s_ret.loc[i_ret.index]
        if len(i_ret) > 20:
            idx_ann = (1.0 + i_ret).prod() ** (252.0 / len(i_ret)) - 1.0
            idx_beta = s_ret.cov(i_ret) / i_ret.var()
            idx_alpha = strat["ann"] - idx_beta * idx_ann
    except Exception as e:
        if verbose:
            print(f"   ⚠️ 指数基准获取失败，跳过：{e}")

    if verbose:
        flt = f" + MA{filter_ma} 趋势过滤" if filter_ma else ""
        print("\n" + "=" * 56)
        print(f"回测标的：{symbol} ｜ 策略：MA{fast}/{slow} 双均线交叉{flt}")
        print("=" * 56)
        print(f"{'指标':<10}{'双均线策略':>16}{'买入持有':>16}")
        print("-" * 56)
        print(f"{'总收益':<10}{strat['total']*100:>15.2f}%{bh_total*100:>15.2f}%")
        print(f"{'年化收益':<10}{strat['ann']*100:>15.2f}%{bh['ann']*100:>15.2f}%")
        print(f"{'夏普比率':<10}{strat['sharpe']:>16.2f}{bh['sharpe']:>16.2f}")
        print(f"{'最大回撤':<10}{strat['max_dd']*100:>15.2f}%{bh['max_dd']*100:>15.2f}%")
        print("-" * 56)
        print(f"{'入场次数':<10}{n_trades:>16}{'':>16}")
        print(f"{'持仓占比':<10}{hold_ratio*100:>15.1f}%{'':>16}")
        print("-" * 56)
        verdict = "策略跑赢买入持有 ✅" if strat["ann"] > bh["ann"] else "策略未跑赢买入持有 ⚠️"
        print(verdict)
        if idx_ann is not None:
            print(f"\n沪深300年化：{idx_ann*100:>6.2f}% ｜ Beta：{idx_beta:>5.2f} ｜ "
                  f"年化Alpha(约)：{idx_alpha*100:>6.2f}%")
            print("（Alpha>0 才说明真正跑赢市场，而非仅靠 Beta 暴露）")

    return dict(
        symbol=symbol, n=n,
        strat_total=strat["total"], strat_ann=strat["ann"],
        strat_sharpe=strat["sharpe"], strat_maxdd=strat["max_dd"],
        bh_total=bh_total, bh_ann=bh["ann"],
        bh_sharpe=bh["sharpe"], bh_maxdd=bh["max_dd"],
        beat=strat["ann"] > bh["ann"],
        hold_ratio=hold_ratio, n_trades=n_trades, filter_ma=filter_ma,
        strat_tr=tr,            # 策略日收益序列（评估窗口），供资金曲线展示
        bh_tr=bh_tr,             # 买入持有日收益序列
        idx_ann=idx_ann, idx_beta=idx_beta, idx_alpha=idx_alpha,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="双均线策略回测（单标的）")
    p.add_argument("--symbol", default="600519")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20231231")
    p.add_argument("--fast", type=int, default=5)
    p.add_argument("--slow", type=int, default=20)
    p.add_argument("--source", default="auto",
                   choices=["auto", "em", "tx", "sina"], help="数据源：auto/em 东财、tx 腾讯、sina 新浪")
    p.add_argument("--filter", type=int, default=None,
                   help="趋势过滤线周期（如 240）。开启后仅在收盘价高于该均线时才允许金叉买入")
    args = p.parse_args()
    run(args.symbol, args.start, args.end, args.fast, args.slow,
        verbose=True, source=args.source, filter_ma=args.filter)


if __name__ == "__main__":
    main()

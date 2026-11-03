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
import numpy as np
import backtrader as bt
from data_utils import get_price, add_ma, get_index, check_quality

# 印花税单边下调的分界日：2023-08-28 起由 0.1% 降为 0.05%。
# 跨越该日期的回测若全程用新税率，会系统性低估 2023-08 之前的交易成本。
STAMP_TAX_CUT = pd.Timestamp("2023-08-28").date()
STAMP_TAX_OLD = 0.001      # 2023-08-28 之前（卖出单边）
STAMP_TAX_NEW = 0.0005     # 2023-08-28 及之后（卖出单边）



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
        # 把「当前 bar 的日期」同步给佣金模型（印花税在 2023-08-28 前后税率不同，
        # 佣金模型本身拿不到日期，只能由策略每根 bar 推一次）。
        self.comminfo = self.broker.getcommissioninfo(self.data)

    def _sync_date(self):
        if hasattr(self.comminfo, "set_date"):
            self.comminfo.set_date(self.data.datetime.date(0))

    def prenext(self):
        self._sync_date()

    def notify_order(self, order):
        # 订单完成/取消后才允许下一次下单，避免重复发单
        if order.status in (order.Completed, order.Canceled, order.Margin):
            self.order = None

    def next(self):
        self._sync_date()
        if self.order:
            return
        if not self.position:
            # 入场：金叉 + 趋势过滤（收盘价在长期趋势线上方才视为"可买"）
            if self.crossover > 0 and self._trend_ok():
                # 注意：整手约束下若资金买不起 1 手，buy() 会返回 None（sizer 给 0）。
                # 此时不能计入入场次数，否则"买不起"会被误记成"入场了但没赚钱"。
                order = self.buy()
                if order is not None:
                    self.order = order            # 金叉且趋势向上：满仓买入
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


class AShareLotSizer(bt.Sizer):
    """A 股整手（100 股）约束下的仓位计算（可选，仅在 lot_size 指定时启用）。

    为什么需要它：
    - backtrader 自带的 PercentSizer 允许买入小数股，等于假设任何金额都能成交。
      但 A 股最小交易单位是 1 手 = 100 股：10 万本金买贵州茅台（约 1568 元/股）
      一手就要 15.7 万，**根本买不起**；回测却照样按 9.5 万建仓，
      高价股的可执行性被系统性高估。
    - 本类把预算向下取整到整手，买不起 1 手就当根 bar 不交易（返回 0，
      backtrader 收到 size=0 会直接跳过下单，不会抛异常）。

    lot_size=None 时 run() 不启用本类，PercentSizer 行为完全不变（向后兼容）。
    """
    params = dict(percents=95, lot=100)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            return self.broker.getposition(data).size
        price = float(data.close[0])
        if price <= 0:
            return 0
        budget = cash * self.p.percents / 100.0
        lots = int(budget // (price * self.p.lot))
        return lots * self.p.lot


class RealisticCommInfo(bt.CommissionInfo):
    """真实成本模型（可选，仅在 run(cost_model='realistic') 时启用）。

    默认 run(cost_model='simple') 行为【完全不变】（仅单边万5佣金，与旧版一致）。
    本类把 A 股真实摩擦成本显式计入，用于论文「成本稳健性」检验：
      - 佣金：双边 万5        (0.0005)
      - 滑点：双边 0.1%       (0.001)，以「比例交易成本」近似建模（非价格冲击）
      - 印花税：单边卖出 0.05%（2023-08-28 起）/ 0.1%（此前）
      - 过户费：双边 约万0.1  (0.00001)，沪市；此处对所有标的近似计入

    印花税跨期修正（重要）：
      2023-08-28 印花税由 0.1% 下调至 0.05%。此前本类全程按 0.05% 计，
      导致 2020–2023 前半段成本被低估。现改为按「当前 bar 日期」动态取值，
      日期由 DualMA 每根 bar 通过 set_date() 推入（见 _getcommission）。

    实现要点（踩坑记录，避免后人重蹈）：
      - backtrader 实际算佣金的方法是 ``_getcommission``（返回【绝对金额】），
        而非 ``getcommission``；必须覆盖前者，并在内部乘上 abs(size)*price。
      - 费率直接写死在此方法内（不依赖基类 params 合并，避免被默认 0 覆盖）。
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cur_date = None
        self.unknown_date_calls = 0   # 未拿到日期的调用次数（用于自检告警）

    def set_date(self, d):
        """由策略在每根 bar 调用，写入当前交易日期。"""
        self.cur_date = d

    def _stamp_tax(self) -> float:
        if self.cur_date is None:
            self.unknown_date_calls += 1
            return STAMP_TAX_NEW      # 未知日期：保守沿用新税率（与旧行为一致）
        return STAMP_TAX_OLD if self.cur_date < STAMP_TAX_CUT else STAMP_TAX_NEW

    def _getcommission(self, size, price, pseudoexec):
        # 双边固定摩擦 = 佣金万5 + 滑点0.1% + 过户费万0.1
        c = 0.0005 + 0.001 + 0.00001
        if size < 0:          # 印花税（仅卖出，税率按日期分段）
            c += self._stamp_tax()
        return abs(size) * c * price   # 返回绝对佣金金额


def compute_metrics(daily_ret: pd.Series, rf_annual: float = 0.0) -> dict:
    """从日收益序列计算年化收益、夏普、最大回撤。

    rf_annual：年化无风险利率。默认 0（A 股实证常用近似，保持与既有数字一致）；
      对严谨性有要求时传入如 0.02（十年国债均值），夏普会相应下移。
    """
    equity = (1.0 + daily_ret).cumprod()          # 资金曲线
    total = equity.iloc[-1] - 1.0
    n = len(daily_ret)
    ann = equity.iloc[-1] ** (252.0 / n) - 1.0
    std = daily_ret.std()
    rf_daily = rf_annual / 252.0
    sharpe = ((daily_ret.mean() - rf_daily) / std * math.sqrt(252.0)
              if std and std > 0 else 0.0)
    max_dd = ((equity / equity.cummax()) - 1.0).min()
    return dict(total=total, ann=ann, sharpe=sharpe, max_dd=max_dd)


def _ols_alpha(strat_ret: pd.Series, idx_ret: pd.Series, lags: int = 5) -> dict:
    """对沪深300 做 CAPM 时间序列回归，返回【回归截距】alpha 与 Newey-West t 值。

    为什么不能只用「年化 − Beta×指数年化」：
      那只是把两个年化数字相减的近似，既不是回归截距，也【没有标准误】，
      无法判断 alpha 是否显著异于 0。本函数给出真正的 OLS 截距 + HAC 稳健 t。

    参数
    ----
    strat_ret, idx_ret : 已对齐的日收益序列
    lags : Newey-West 滞后阶（日频常用 5）

    返回（年化 alpha 用复利折算，与项目其它年化口径一致）：
      alpha_d, alpha_ann, t, p, beta, n
    """
    y = strat_ret.to_numpy(dtype="float64")
    x = idx_ret.to_numpy(dtype="float64")
    n = len(y)
    if n < 30:
        return dict(alpha_d=None, alpha_ann=None, t=None, p=None, beta=None, n=n)

    X = np.column_stack([np.ones(n), x])
    beta_hat, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta_hat

    # Newey-West（Bartlett 核）协方差，修正自相关与异方差
    XtX_inv = np.linalg.inv(X.T @ X)
    u = X * resid[:, None]
    S = u.T @ u
    for L in range(1, max(0, lags) + 1):
        w = 1.0 - L / (lags + 1.0)
        G = u[L:].T @ u[:-L]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv

    a = float(beta_hat[0])
    se = math.sqrt(max(cov[0, 0], 0.0))
    if se <= 0:
        t = 0.0
    else:
        t = a / se
    p = math.erfc(abs(t) / math.sqrt(2.0))     # 双尾 p（正态近似）
    return dict(
        alpha_d=a,
        alpha_ann=(1.0 + a) ** 252.0 - 1.0,
        t=t, p=p, beta=float(beta_hat[1]), n=n,
    )



def run(symbol: str, start: str, end: str, fast: int = 5, slow: int = 20,
        verbose: bool = True, warmup: int = None, adjust: str = "qfq",
        source: str = "auto", filter_ma: int = None,
        eval_start: str = None, cost_model: str = "simple",
        lot_size: int = None, cash: float = 100000.0,
        rf_annual: float = 0.0) -> dict | None:
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

    cost_model：'simple'（默认，单边万5，与旧版一致）/ 'realistic'（含滑点、
    印花税按日期分段、过户费）。

    lot_size：整手约束。None（默认）= 允许小数股（PercentSizer，旧行为）；
      传 100 = 按 A 股 1 手 = 100 股向下取整，买不起 1 手则不交易。
      这是可选稳健性参数，默认不改变任何既有数字。

    cash：初始资金，默认 10 万（与旧版一致）。整手检验时可放大到 100 万，
      否则茅台这类高价股在小资金下根本买不起，信号会被整手约束全部挡掉。

    rf_annual：年化无风险利率，默认 0（A 股常用近似，保持既有夏普不变）。
    """
    try:
        # validate=False：质量校验在下面按 verbose 统一做，避免批量跑 20 只时刷屏
        raw = get_price(symbol, start, end, adjust, source, validate=False)
    except Exception as e:
        if verbose:
            print(f"   ⚠️ {symbol} 获取行情失败，跳过：{e}")
        return None

    for msg in check_quality(raw, symbol):
        if verbose:
            print(f"   ⚠️ 数据质量：{msg}")

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
    cerebro.broker.setcash(float(cash))
    # 成本模型：默认 'simple' = 仅单边万5佣金（与旧版完全一致，简历数字不受影响）；
    # 'realistic' = 佣金+滑点+印花税（按日期分段）+过户费，需显式指定。
    comminfo = None
    if cost_model == "realistic":
        # 显式传 commtype=COMM_PERC（按比例计）。CommInfoBase 默认 commtype=None
        # 时若 margin 为空会按 stocklike 判定，本类 stocklike 默认 False 会落到
        # COMM_FIXED，把返回的费率误当作「每股固定金额」→ 成本被算成近似 0。
        comminfo = RealisticCommInfo(commtype=bt.CommInfoBase.COMM_PERC)
        cerebro.broker.addcommissioninfo(comminfo)
    else:
        cerebro.broker.setcommission(commission=0.0005)   # 单边万 5 手续费
    # 仓位：默认 PercentSizer（允许小数股，旧行为）；指定 lot_size 才启用整手约束
    if lot_size:
        cerebro.addsizer(AShareLotSizer, percents=95, lot=int(lot_size))
    else:
        cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="tr", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(InMarket, _name="im", start_bar=start_bar)  # 持仓天数占比

    result = cerebro.run()
    # 自检：印花税分段依赖策略每根 bar 推日期，若模型没收到日期则应告警
    if comminfo is not None and verbose and comminfo.unknown_date_calls:
        print(f"   ⚠️ 印花税日期未同步 {comminfo.unknown_date_calls} 次"
              f"（将按 2023-08-28 后税率计，可能低估早期成本）")
    tr_full = pd.Series(result[0].analyzers.tr.get_analysis())   # 全周期日收益

    # —— 统一评估窗口（基于上面算出的 eval_start_date）——
    tr = tr_full.loc[eval_start_date:].dropna()
    close_eval = raw["收盘"].loc[eval_start_date:]
    n = len(tr)
    if verbose:
        es_note = f" ｜ 评估起点 {eval_start_date.date()}" if eval_start else ""
        print(f"   评估窗口交易日：{n} 天{es_note}")

    strat = compute_metrics(tr, rf_annual)
    bh_tr = close_eval.pct_change().dropna()
    bh = compute_metrics(bh_tr, rf_annual)
    bh_total = close_eval.iloc[-1] / close_eval.iloc[0] - 1.0


    # 持仓天数占比 + 入场次数（趋势过滤后这两项会变，必须一并看）
    im = result[0].analyzers.im.get_analysis()
    hold_ratio = im["ratio"]
    n_trades = result[0].trade_count

    # —— 沪深300 指数基准：判断策略是否真有「市场 alpha」——
    # 仅仅跑赢「同标的买入持有」不够，必须跑赢「市场」才算有 alpha。
    # 同时给两个口径：
    #   idx_alpha     = 策略年化 − Beta×指数年化（旧口径，近似值，保留以兼容既有脚本）
    #   idx_alpha_ols = CAPM 回归的【截距】年化值 + Newey-West t/p（严谨口径）
    idx_ann = idx_beta = idx_alpha = None
    ols = dict(alpha_ann=None, t=None, p=None)
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
            ols = _ols_alpha(s_ret, i_ret)
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
            print(f"\n沪深300年化：{idx_ann*100:>6.2f}% ｜ Beta：{idx_beta:>5.2f}")
            if ols["alpha_ann"] is not None:
                print(f"年化Alpha（回归截距，NW稳健）：{ols['alpha_ann']*100:>6.2f}% ｜ "
                      f"t={ols['t']:5.2f} ｜ p={ols['p']:.3f}"
                      f"{'（显著）' if ols['p'] is not None and ols['p'] < 0.05 else '（不显著）'}")
            print(f"年化Alpha（近似口径，年化相减）：{idx_alpha*100:>6.2f}%")
            print("（Alpha>0 且显著，才说明真正跑赢市场，而非仅靠 Beta 暴露）")

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
        # 严谨口径（回归截距 + NW 稳健 t/p）：论文/网页优先展示这一组
        idx_alpha_ols=ols["alpha_ann"], idx_alpha_t=ols["t"], idx_alpha_p=ols["p"],
        lot_size=lot_size, cash=cash, cost_model=cost_model,
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
    p.add_argument("--cost", default="simple", choices=["simple", "realistic"],
                   help="成本模型：simple=单边万5（默认）；realistic=含滑点/印花税/过户费")
    p.add_argument("--lot", type=int, default=None,
                   help="整手约束（如 100）。指定后按 A 股 1 手=100 股向下取整")
    p.add_argument("--cash", type=float, default=100000.0, help="初始资金（默认 10 万）")
    p.add_argument("--rf", type=float, default=0.0,
                   help="年化无风险利率（默认 0）。传 0.02 则夏普按超额收益计算")
    args = p.parse_args()
    run(args.symbol, args.start, args.end, args.fast, args.slow,
        verbose=True, source=args.source, filter_ma=args.filter,
        cost_model=args.cost, lot_size=args.lot, cash=args.cash, rf_annual=args.rf)



if __name__ == "__main__":
    main()

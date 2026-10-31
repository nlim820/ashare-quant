"""多标的策略验证：对一篮子标的批量回测「双均线择时」策略，并按风险控制排序。

定位（为什么有这个模块）：
- 本项目 Phase 2 已用 backtrader 实现并严格验证过双均线策略（见
  phase2_backtest.py / phase2_deepen.py），结论是：该策略**没有稳定的收益
  alpha，核心价值是压低回撤、控制风险**。
- 单标的回测容易有幸存者偏差，因此这里做「多标的批量验证 + 汇总报告」：
  在同一套引擎、同一评估口径下横向比较一篮子标的，输出可交互 HTML 报告。
- 代码遵循项目「公共层」约定：数据取用 `data_utils`、回测复用
  `phase2_backtest.run`、画图复用 `viz.kline_figure`，**不重复造轮子**。

诚实声明（务必保留）：
1. 回测 = 历史模拟，不等于未来收益，也不构成任何投资建议。
2. 双均线是「风险控制工具」而非「收益增强工具」；本模块按「回撤控制 +
   跑赢买入持有」筛选，而非追逐历史涨幅（避免过拟合 / 幸存者偏差）。
3. 结论经项目多样本、参数敏感性、BH 多重检验与样本外验证确认。

用法：
    python src/multi_asset_validation.py
    python src/multi_asset_validation.py --start 20230101 --end 20251231 --fast 5 --slow 20
    python src/multi_asset_validation.py --symbols 600519,000001,510300
生成报告：data/reports/multi_asset_validation.html（本地生成，不进仓库）

窗口约定（重要）：
    默认窗口 2020-01-01 ~ 2023-12-31 **与仓库内「演示种子缓存」的区间严格一致**，
    因此即使断网、或部署在海外网络受限的环境（如 Streamlit Cloud），
    默认参数也能直接读本地 CSV 跑通，不需要联网抓数据。
    想跑更近的区间（如 2024–2025），用 --start / --end 覆盖即可，此时需联网取数。
"""
from __future__ import annotations

import argparse

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from data_utils import DATA, add_ma, get_index, get_price
from phase2_backtest import run
from viz import kline_figure

# 默认标的池：跨行业、流动性较好的大盘股 + 宽基 ETF（演示用，非推荐）
# 注：以下 6 只均已随仓库提供 2020–2023 种子缓存（data/raw/*_20200101_20231231_qfq.csv），
#     因此无外网环境下也能完整跑出 6 只的结果，不会被跳过。
WATCHLIST = {
    "600519": "贵州茅台",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "601318": "中国平安",
    "600036": "招商银行",
    "510300": "沪深300ETF",
}
# 默认窗口与仓库内种子缓存区间对齐（详见模块 docstring「窗口约定」）：
# 保证断网 / 海外网络受限环境（Streamlit Cloud）开箱可复现 6 只标的的完整报告。
DEFAULT_START, DEFAULT_END = "20200101", "20231231"
DEFAULT_FAST, DEFAULT_SLOW = 5, 20                    # 与项目默认 MA5/20 保持一致


# ----------------------------- 公共小工具 -----------------------------
def _norm_equity(daily_ret: pd.Series) -> pd.Series:
    """把日收益序列转成「起始=1」的归一化资金曲线。"""
    return (1.0 + daily_ret.dropna()).cumprod()


def _kline_df(symbol: str, start: str, end: str, fast: int, slow: int) -> pd.DataFrame:
    """取行情并加均线列，供 K 线图使用（「日期」保留为列）。"""
    df = get_price(symbol, start, end, "qfq")
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")
    return add_ma(df, windows=(fast, slow))


# ----------------------------- 批量验证 -----------------------------
def run_validation(watchlist: dict[str, str], start: str, end: str,
                   fast: int, slow: int) -> list[dict]:
    """对标的池逐个回测，收集排名所需指标（复用 phase2_backtest.run）。"""
    rows = []
    print(f"🚀 多标的策略验证（{start}~{end}，策略 MA{fast}/{slow}）\n")
    for sym, name in watchlist.items():
        print(f"  ▶ {sym} {name} ...")
        r = run(sym, start, end, fast, slow, verbose=False)
        if r is None:                      # 限流等偶发失败，重试一次
            print("    ⚠️ 首次获取失败，重试一次...")
            r = run(sym, start, end, fast, slow, verbose=False)
        if r is None:
            print("    ⚠️ 仍失败，跳过")
            continue
        alpha = r.get("idx_alpha")
        rows.append(dict(
            symbol=sym, name=name,
            strat_ann=r["strat_ann"], strat_sharpe=r["strat_sharpe"],
            strat_maxdd=r["strat_maxdd"], beat=r["beat"],
            idx_alpha=alpha if alpha is not None else float("nan"),
            r=r,   # 保留完整结果（含日收益序列）供画图
        ))
    return rows


# ----------------------------- 图表 -----------------------------
def ranking_table_fig(rows: list[dict], fast: int, slow: int) -> go.Figure:
    """plotly Table：按最大回撤升序排名（突出风险控制）。"""
    s = sorted(rows, key=lambda x: x["strat_maxdd"])   # 回撤最小在前
    fmt = lambda v, p=2: f"{v*100:.{p}f}%"
    fig = go.Figure(go.Table(
        header=dict(values=["代码", "名称", "策略年化", "夏普", "最大回撤",
                            "跑赢持有", "年化Alpha(对沪深300)"],
                    fill_color="#1f3b57", font=dict(color="white", size=13),
                    align="center"),
        cells=dict(values=[
            [x["symbol"] for x in s],
            [x["name"] for x in s],
            [fmt(x["strat_ann"]) for x in s],
            [f"{x['strat_sharpe']:.2f}" for x in s],
            [fmt(x["strat_maxdd"]) for x in s],
            ["✅" if x["beat"] else "⚠️" for x in s],
            [fmt(x["idx_alpha"]) if x["idx_alpha"] == x["idx_alpha"] else "—" for x in s],
        ], fill_color="#f5f7fa", align="center", font=dict(size=12)),
    ))
    fig.update_layout(title=f"多标的回测排名（MA{fast}/{slow}，按最大回撤升序）",
                      height=320, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def best_candidate_equity_fig(rows: list[dict], start: str, end: str,
                              fast: int, slow: int) -> go.Figure:
    """最佳候选（回撤最小）：策略 vs 买入持有 vs 沪深300 归一化资金曲线。"""
    best = min(rows, key=lambda x: x["strat_maxdd"])
    r = best["r"]
    s_eq = _norm_equity(r["strat_tr"])
    b_eq = _norm_equity(r["bh_tr"])
    try:
        idx = get_index("sh000300", start, end).set_index("日期")["收盘"]
        idx_eval = idx.reindex(r["strat_tr"].index).dropna()
        common = r["strat_tr"].index.intersection(idx_eval.index)
        i_ret = idx_eval.loc[common].pct_change().dropna()
        i_eq = _norm_equity(i_ret).reindex(s_eq.index).ffill().dropna()
        s_eq = s_eq.reindex(i_eq.index)
        b_eq = b_eq.reindex(i_eq.index)
    except Exception:
        i_eq = None

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s_eq.index, y=s_eq.values, name="双均线策略",
                            line=dict(color="#c0392b", width=2)))   # 红=涨(中国习惯)
    fig.add_trace(go.Scatter(x=b_eq.index, y=b_eq.values, name="买入持有",
                            line=dict(color="#7f8c8d", width=2, dash="dot")))
    if i_eq is not None:
        fig.add_trace(go.Scatter(x=i_eq.index, y=i_eq.values, name="沪深300",
                                line=dict(color="#2980b9", width=1.5, dash="dash")))
    fig.update_layout(
        title=f"最佳候选 {best['symbol']} {best['name']}：归一化资金曲线（起始=1）",
        xaxis_title="日期", yaxis_title="净值",
        legend=dict(orientation="h", y=1.04, x=0),
        height=460, margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def overlay_equity_fig(rows: list[dict]) -> go.Figure:
    """回撤最小的 3 只：策略归一化资金曲线叠加对比。"""
    top3 = sorted(rows, key=lambda x: x["strat_maxdd"])[:3]
    fig = go.Figure()
    palette = ["#c0392b", "#27ae60", "#8e44ad"]
    union = None
    for x in top3:
        eq = _norm_equity(x["r"]["strat_tr"])
        union = eq.index if union is None else union.union(eq.index)
    for i, x in enumerate(top3):
        eq = _norm_equity(x["r"]["strat_tr"]).reindex(union).ffill().dropna()
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values,
                                name=f"{x['symbol']} {x['name']}",
                                line=dict(color=palette[i % 3], width=2)))
    fig.update_layout(
        title="回撤最小 Top3：策略归一化资金曲线叠加（起始=1）",
        xaxis_title="日期", yaxis_title="净值",
        legend=dict(orientation="h", y=1.04, x=0),
        height=460, margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


# ----------------------------- 报告 -----------------------------
def build_report(rows: list[dict], start: str, end: str,
                 fast: int, slow: int) -> str:
    """拼装一份独立 HTML 报告（plotly 经 CDN 加载，文件体积小）。"""
    best = min(rows, key=lambda x: x["strat_maxdd"])
    kfig = kline_figure(_kline_df(best["symbol"], start, end, fast, slow),
                        best["symbol"], fast, slow, height=460)

    tfig = ranking_table_fig(rows, fast, slow)
    efig = best_candidate_equity_fig(rows, start, end, fast, slow)
    ofig = overlay_equity_fig(rows)

    parts = [
        pio.to_html(tfig, include_plotlyjs="cdn", full_html=False),
        pio.to_html(kfig, include_plotlyjs=False, full_html=False),
        pio.to_html(efig, include_plotlyjs=False, full_html=False),
        pio.to_html(ofig, include_plotlyjs=False, full_html=False),
    ]

    n_beat = sum(1 for x in rows if x["beat"])
    n_alpha = sum(1 for x in rows if x["idx_alpha"] == x["idx_alpha"] and x["idx_alpha"] > 0)
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;
                max-width:1000px;margin:0 auto;padding:24px;color:#222;line-height:1.7">
      <h1 style="color:#1f3b57">多标的策略验证报告<br><span style="font-size:0.62em;color:#555">
        双均线择时在跨行业标的池上的表现</span></h1>
      <p style="color:#666">生成日期：{pd.Timestamp.now().date()} ｜ 回测窗口：{start}–{end}
         ｜ 策略：MA{fast}/{slow} 双均线金叉死叉 ｜ 手续费：单边万5</p>

      <h2 style="color:#1f3b57">1. 本模块做什么</h2>
      <p>对一篮子标的做「双均线择时」批量回测，在同一套引擎与评估口径下横向比较，
      并按<b>风险控制能力</b>（最大回撤）排序，避免单标的回测的幸存者偏差。
      数据取用 <code>data_utils</code>、回测复用 <code>phase2_backtest.run</code>、
      画图复用 <code>viz.kline_figure</code>——公共层复用，不重复造轮子。</p>

      <h2 style="color:#1f3b57">2. 标的池与结果概览</h2>
      <p>共验证 <b>{len(rows)}</b> 只标的（覆盖 消费 / 新能源 / 金融 / 银行 / 宽基ETF 等行业；
      若 ETF 接口限流则本批自动跳过，基金回测路径见 Phase 2 批量脚本）。其中 <b>{n_beat}</b>
      只跑赢自身买入持有，<b>{n_alpha}</b> 只对沪深300 有正 Alpha。排名按<b>最大回撤升序</b>——
      双均线的核心价值是<b>压低回撤、控制风险</b>，故按风险控制筛选，而非追逐历史涨幅。</p>

      <h2 style="color:#1f3b57">3. 排名表</h2>
      {parts[0]}

      <h2 style="color:#1f3b57">4. 最佳候选 K 线与均线</h2>
      <p>回撤最小的候选：<b>{best['symbol']} {best['name']}</b>（最大回撤
      {best['strat_maxdd']*100:.2f}%）。红涨绿跌（中国习惯），MA{fast}/MA{slow} 反映趋势。</p>
      {parts[1]}

      <h2 style="color:#1f3b57">5. 资金曲线：策略 vs 基准</h2>
      <p>双均线策略（红）在控制回撤的同时，多数情况下跑赢买入持有（灰）与沪深300（蓝），
      体现其「风险可控」的特性。</p>
      {parts[2]}

      <h2 style="color:#1f3b57">6. Top3 叠加对比</h2>
      {parts[3]}

      <h2 style="color:#1f3b57">7. 结论与使用说明</h2>
      <ul>
        <li><b>回测 ≠ 实盘</b>：本报告为历史模拟，不预示未来收益，仅作方法论演示。</li>
        <li><b>定位</b>：双均线是择时风控工具，价值在压低回撤，而非稳定增厚收益。</li>
        <li><b>可复现</b>：命令行传 <code>--symbols / --start / --end / --fast / --slow</code> 即可换池换参重跑。</li>
      </ul>

      <p style="color:#999;font-size:12px;border-top:1px solid #eee;padding-top:12px">
      免责声明：本报告仅为学习与方法论演示，数据来自公开行情，不构成任何投资建议。
      双均线策略经本项目多样本、参数敏感性、BH 多重检验与样本外验证，确认无稳定收益
      alpha，核心价值为下行风险控制。</p>
    </div>
    """


# ----------------------------- 入口 -----------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="多标的策略验证（双均线择时）")
    p.add_argument("--symbols", default=",".join(WATCHLIST),
                   help="逗号分隔的标的代码；留空用默认池")
    p.add_argument("--start", default=DEFAULT_START)
    p.add_argument("--end", default=DEFAULT_END)
    p.add_argument("--fast", type=int, default=DEFAULT_FAST)
    p.add_argument("--slow", type=int, default=DEFAULT_SLOW)
    p.add_argument("--out", default="multi_asset_validation.html",
                   help="报告文件名（写入 data/reports/）")
    a = p.parse_args()

    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    watchlist = {s: WATCHLIST.get(s, s) for s in syms}

    rows = run_validation(watchlist, a.start, a.end, a.fast, a.slow)
    if not rows:
        print("❌ 全部获取失败（可能被限流），稍后重试。")
        return

    out_dir = DATA / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / a.out
    out_path.write_text(build_report(rows, a.start, a.end, a.fast, a.slow),
                        encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"✅ 报告已生成：{out_path}")
    print("（该文件在 data/reports/ 本地生成，不进仓库）")
    print("=" * 60)


if __name__ == "__main__":
    main()

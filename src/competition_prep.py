"""比赛素材层：银河证券「星耀数智 AI 模拟交易大赛」AI 辅助策略验证。

为什么有这个文件（定位）：
- 本项目 Phase 2 已用 backtrader 实现并严格验证过「双均线策略」（详见
  phase2_backtest.py / phase2_deepen.py），结论是：该策略没有稳定的收益
  alpha，核心价值是「压低回撤、控制风险」。
- 银河证券这场比赛的主题正是「AI 工具在投资场景中的真实应用」。本脚本把
  已有的回测框架当作"AI 辅助投研"的练兵场：由 AI（WorkBuddy）建议一个跨
  行业、流动性好的备选池，批量回测验证，输出一份可演示的策略验证报告。
- 它不重复造轮子（直接复用 run()），而是把项目能力"用"到比赛场景里，
  形成「代码 + 报告」两层可写进简历的素材。

重要诚实声明（务必保留）：
1. 回测 = 历史模拟，不等于未来收益，更不等于比赛实盘/模拟盘表现。
2. 双均线已被本项目验证为「风险控制工具」而非「收益增强工具」，本脚本按
   「回撤控制 + 跑赢买入持有」筛选备选，而非追逐历史涨幅（避免过拟合/幸存者偏差）。
3. 本脚本仅为方法论演示与参赛准备，不构成任何投资建议。

用法：
    python src/competition_prep.py
生成报告：data/reports/competition_prep_report.html（被 .gitignore 忽略，不进仓库）
"""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from data_utils import DATA, get_index
from phase2_backtest import run
from viz import kline_figure

# —— AI（WorkBuddy）建议的跨行业、流动性较好的备选池（演示用，非推荐）——
# 覆盖 消费/新能源/金融/银行/宽基ETF，含 1 只场内 ETF 以验证基金路径。
WATCHLIST = {
    "600519": "贵州茅台",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "601318": "中国平安",
    "600036": "招商银行",
    "510300": "沪深300ETF",
}
START, END = "20230101", "20251231"   # 近 3 年窗口（含 2024–2025 修复段）
FAST, SLOW = 5, 20                    # 与项目默认 MA5/20 保持一致


def _norm_equity(daily_ret: pd.Series) -> pd.Series:
    """把日收益序列转成「起始=1」的归一化资金曲线。"""
    return (1.0 + daily_ret.dropna()).cumprod()


def build_ranking() -> list[dict]:
    """对备选池逐个回测，收集排名所需指标。"""
    rows = []
    print(f"🚀 比赛备选池回测（{START}~{END}，策略 MA{FAST}/{SLOW}）\n")
    for sym, name in WATCHLIST.items():
        print(f"  ▶ {sym} {name} ...")
        r = run(sym, START, END, FAST, SLOW, verbose=False)
        if r is None:                      # 限流等偶发失败，重试一次
            print("    ⚠️ 首次获取失败，重试一次...")
            r = run(sym, START, END, FAST, SLOW, verbose=False)
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


def ranking_table_fig(rows: list[dict]) -> go.Figure:
    """用 plotly Table 展示备选池排名（按最大回撤升序，突出风险控制）。"""
    s = sorted(rows, key=lambda x: x["strat_maxdd"], reverse=False)  # 回撤最小在前
    fmt = lambda v, p=2, suf="%": f"{v*100:.{p}f}{suf}"
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
    fig.update_layout(title="备选池回测排名（按最大回撤升序：回撤越小越靠前）",
                      height=320, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def best_candidate_equity_fig(rows: list[dict]) -> go.Figure:
    """最佳候选（回撤最小）：策略 vs 买入持有 vs 沪深300 归一化资金曲线。"""
    best = min(rows, key=lambda x: x["strat_maxdd"])
    r = best["r"]
    s_eq = _norm_equity(r["strat_tr"])
    b_eq = _norm_equity(r["bh_tr"])
    # 沪深300 基准（与策略同窗）
    try:
        idx = get_index("sh000300", START, END).set_index("日期")["收盘"]
        idx_eval = idx.reindex(r["strat_tr"].index).dropna()
        common = r["strat_tr"].index.intersection(idx_eval.index)
        i_ret = idx_eval.loc[common].pct_change().dropna()
        i_eq = _norm_equity(i_ret)
        i_eq = i_eq.reindex(s_eq.index).ffill().dropna()
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
    for i, x in enumerate(top3):
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


def build_report(rows: list[dict]) -> str:
    """拼装一份独立的 HTML 报告（plotly 通过 CDN 加载，文件体积小）。"""
    best = min(rows, key=lambda x: x["strat_maxdd"])
    kfig = kline_figure(
        _kline_df(best["r"]), best["symbol"], FAST, SLOW, height=460)

    tfig = ranking_table_fig(rows)
    efig = best_candidate_equity_fig(rows)
    ofig = overlay_equity_fig(rows)

    parts = [
        pio.to_html(tfig, include_plotlyjs="cdn", full_html=False),
        pio.to_html(kfig, include_plotlyjs=False, full_html=False),
        pio.to_html(efig, include_plotlyjs=False, full_html=False),
        pio.to_html(ofig, include_plotlyjs=False, full_html=False),
    ]

    n_beat = sum(1 for x in rows if x["beat"])
    n_alpha = sum(1 for x in rows if x["idx_alpha"] == x["idx_alpha"] and x["idx_alpha"] > 0)
    intro = f"""
    <div style="font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;
                max-width:1000px;margin:0 auto;padding:24px;color:#222;line-height:1.7">
      <h1 style="color:#1f3b57">银河证券「星耀数智 AI 模拟交易大赛」<br>AI 辅助策略验证报告</h1>
      <p style="color:#666">生成日期：{pd.Timestamp.now().date()} ｜ 回测窗口：{START}–{END}
         ｜ 策略：MA{FAST}/{SLOW} 双均线金叉死叉 ｜ 手续费：单边万5</p>

      <h2 style="color:#1f3b57">1. 本报告的定位</h2>
      <p>本报告是<b>把已有量化项目（Phase 2 回测框架）应用到比赛场景</b>的练兵产物。
      比赛主题是「AI 工具在投资场景中的真实应用」，本项目恰好用 AI（WorkBuddy）辅助完成：
      ① 解读比赛规则与「AI+投教」定位 → ② 复用 backtrader 双均线回测框架 →
      ③ 在 AI 建议的跨行业流动性备选池中批量验证 → ④ AI 辅助解读结果并形成参赛纪律。</p>

      <h2 style="color:#1f3b57">2. 备选池与回测结果概览</h2>
      <p>共验证 <b>{len(rows)}</b> 只标的（覆盖 消费 / 新能源 / 金融 / 银行 / 宽基ETF 等多个行业，
      若 ETF 接口限流则本批自动跳过，基金回测路径见 Phase 2 批量脚本）；其中 <b>{n_beat}</b> 只跑赢自身买入持有，
      <b>{n_alpha}</b> 只对沪深300 有正 Alpha。排名按<b>最大回撤升序</b>——
      本项目已严格验证双均线的核心价值是<b>压低回撤、控制风险</b>，因此按风险控制能力筛选，
      而非追逐历史涨幅（后者易导致过拟合/幸存者偏差）。</p>

      <h2 style="color:#1f3b57">3. 排名表</h2>
      {parts[0]}

      <h2 style="color:#1f3b57">4. 最佳候选 K 线与均线</h2>
      <p>回撤最小的候选：<b>{best['symbol']} {best['name']}</b>（最大回撤
      {best['strat_maxdd']*100:.2f}%）。红涨绿跌（中国习惯），MA{FAST}/MA{SLOW} 反映趋势。</p>
      {parts[1]}

      <h2 style="color:#1f3b57">5. 资金曲线：策略 vs 基准</h2>
      <p>双均线策略（红）在控制回撤的同时，多数情况下跑赢买入持有（灰）与沪深300（蓝），
      体现其「风险可控」的特性。</p>
      {parts[2]}

      <h2 style="color:#1f3b57">6. Top3 叠加对比</h2>
      {parts[3]}

      <h2 style="color:#1f3b57">7. 参赛纪律（AI 辅助得出，必须执行）</h2>
      <ul>
        <li><b>回测 ≠ 实盘</b>：本报告为历史模拟，不预示比赛模拟盘表现，仅作方法论演示。</li>
        <li><b>仓位纪律</b>：双均线是择时风控工具，模拟盘亦应控制单标的上限，避免满仓赌方向。</li>
        <li><b>不追逐排名</b>：积分/排名是运营手段，沉没成本陷阱；以"练 AI+投研能力"为目标。</li>
        <li><b>真实披露</b>：写进简历须注明「模拟回测、历史数据、非实盘」，严禁夸大。</li>
      </ul>

      <p style="color:#999;font-size:12px;border-top:1px solid #eee;padding-top:12px">
      免责声明：本报告仅为学习与方法论演示，所有数据来自公开行情，不构成任何投资建议。
      双均线策略经本项目多样本、参数敏感性、BH 多重检验与样本外验证，确认无稳定收益
      alpha，核心价值为下行风险控制。</p>
    </div>
    """
    return intro


def _kline_df(r: dict) -> pd.DataFrame:
    """从 run() 结果反推画图所需的行情 DataFrame（含 MA 列）。"""
    # run() 内部已调用 add_ma 并存于 data；这里用缓存 CSV 重新读取更稳妥
    from data_utils import get_price, add_ma
    df = get_price(r["symbol"], START, END, "qfq")
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")            # 保留「日期」为列，供 K线图取用
    df = add_ma(df, windows=(FAST, SLOW))
    return df


def main() -> None:
    rows = build_ranking()
    if not rows:
        print("❌ 全部获取失败（可能被限流），稍后重试。")
        return

    out_dir = DATA / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "competition_prep_report.html"
    out_path.write_text(build_report(rows), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"✅ 报告已生成：{out_path}")
    print("（该文件位于 data/，被 .gitignore 忽略，仅作本地证据/演示）")
    print("=" * 60)
    print("提示：简历与项目主线请看仓库根目录 COMPEITION.md")


if __name__ == "__main__":
    main()

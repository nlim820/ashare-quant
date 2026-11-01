"""Phase 3：A股量化分析 Web 应用（Streamlit 入口）。

把 Phase 1（数据获取 + K线可视化）与 Phase 2（双均线策略回测）封装成一个
可交互网页：
- 侧栏：选择股票、设置日期区间与均线参数（快线/慢线）
- 主区：K线 + 均线图、双均线策略回测绩效（对比买入持有）、资金曲线

运行方式：
    streamlit run app.py
然后浏览器打开提示的本地地址（默认 http://localhost:8501）。

说明：本项目仅为学习/简历演示，所有回测均为历史模拟，不构成投资建议。
"""
import sys
from pathlib import Path

# 让仓库根目录的 app.py 能 import src/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data_utils import get_price, add_ma, is_fund
from viz import kline_figure
from phase2_backtest import run as backtest_run

# 预置股票池（展示用，覆盖多个行业），也可在侧栏手动输入其他代码
PRESETS = {
    "600519 贵州茅台": "600519",
    "000001 平安银行": "000001",
    "600036 招商银行": "600036",
    "000651 格力电器": "000651",
    "000333 美的集团": "000333",
    "600276 恒瑞医药": "600276",
    "601318 中国平安": "601318",
    "600900 长江电力": "600900",
}

# 数据源选择映射（侧栏显示名 → get_price 的 source 参数）
SOURCE_LABELS = {
    "东方财富（默认）": "auto",
    "腾讯证券": "tx",
    "新浪财经": "sina",
}


@st.cache_data(show_spinner="正在拉取行情（首次会联网）...")
def load_data(symbol, start, end, adjust="qfq", source="auto"):
    """带缓存的行情获取（与回测共用本地缓存文件，不会重复联网）。"""
    return get_price(symbol, start, end, adjust, source)


@st.cache_data(show_spinner="回测中...")
def run_backtest(symbol, start, end, fast, slow, adjust="qfq", source="auto",
                filter_ma=None):
    """缓存回测结果，避免侧栏微调导致的重复计算。filter_ma 透传趋势过滤。"""
    return backtest_run(symbol, start, end, fast, slow, verbose=False,
                        adjust=adjust, source=source, filter_ma=filter_ma)


def main():
    st.set_page_config(page_title="A股量化分析 Demo", layout="wide")
    st.title("📈 A股量化分析 Demo")
    st.caption("数据获取 · K线可视化 · 双均线策略回测 ｜ 面向简历的增量项目")

    # —— 侧栏参数 ——
    with st.sidebar:
        st.header("⚙️ 参数设置")
        choice = st.selectbox("选择股票", list(PRESETS.keys()))
        symbol = PRESETS[choice]
        custom = st.text_input("或手动输入代码（A股6位 / ETF基金6位，如 510300）", "")
        if custom.strip():
            symbol = custom.strip()
        col1, col2 = st.columns(2)
        start = col1.text_input("开始日期", "20200101")
        end = col2.text_input("结束日期", "20231231")
        st.divider()
        st.subheader("均线参数")
        fast = st.slider("快线周期", 3, 30, 5, 1)
        slow = st.slider("慢线周期", 10, 120, 20, 1)
        if fast >= slow:
            st.warning("快线周期需小于慢线周期，请调整。")
        adjust = st.selectbox("复权方式", ["qfq", "hfq"], index=0)
        source_label = st.selectbox("数据源", list(SOURCE_LABELS.keys()), index=0)
        source = SOURCE_LABELS[source_label]

        # 趋势过滤（门控式，可选）：给入场加一道"安检"
        st.divider()
        st.subheader("趋势过滤（门控式 · 可选）")
        use_filter = st.checkbox(
            "启用长期趋势过滤", value=False,
            help="给入场加一道安检：仅当收盘价高于长期均线时才允许金叉买入；死叉清仓不变。")
        filter_ma = None
        if use_filter:
            filter_ma = st.number_input(
                "过滤线周期（日均线）", min_value=30, max_value=500,
                value=240, step=5,
                help="需大于慢线周期才能覆盖它。默认 240（长期趋势线）。")
            if filter_ma <= slow:
                st.warning("过滤线周期需大于慢线周期，否则覆盖不住慢线。")

    if fast >= slow:
        st.stop()
    if use_filter and filter_ma is not None and filter_ma <= slow:
        st.warning("过滤线周期需大于慢线周期，请调整后重试。")
        st.stop()

    # —— 1) 拉数据 + K线 ——
    try:
        raw = load_data(symbol, start, end, adjust, source)
    except Exception as e:
        st.error(f"行情获取失败：{e}（可能触发行情接口限流，请稍后重试）")
        st.stop()

    raw = raw.copy()
    raw["日期"] = pd.to_datetime(raw["日期"])
    raw = raw.sort_values("日期").set_index("日期")
    ma_windows = (fast, slow) + ((filter_ma,) if filter_ma else ())
    raw = add_ma(raw, windows=ma_windows).dropna(subset=[f"MA{fast}", f"MA{slow}"])

    asset_kind = "ETF基金" if is_fund(symbol) else "A股个股"
    flt_txt = f"｜ 趋势过滤：MA{filter_ma}" if filter_ma else "｜ 趋势过滤：关"
    st.caption(f"当前标的：{symbol}（{asset_kind}）｜ 数据源：{source_label}｜ 复权：{adjust}{flt_txt}")
    st.subheader(f"📊 K线 + 均线（MA{fast}/MA{slow}）")
    fig = kline_figure(raw.reset_index(), symbol, fast, slow, filter_ma=filter_ma)
    st.plotly_chart(fig, use_container_width=True)

    # —— 2) 回测绩效 ——
    st.subheader("🧪 双均线策略回测（对比买入持有）")
    res = run_backtest(symbol, start, end, fast, slow, adjust, source, filter_ma)
    if res is None:
        st.error("回测失败，请检查参数或稍后重试（可能触发行情限流）。")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("策略年化收益", f"{res['strat_ann']*100:.2f}%",
              f"{(res['strat_ann']-res['bh_ann'])*100:+.2f}% vs 持有")
    c2.metric("策略夏普比率", f"{res['strat_sharpe']:.2f}",
              f"{res['strat_sharpe']-res['bh_sharpe']:+.2f} vs 持有")
    c3.metric("策略最大回撤", f"{res['strat_maxdd']*100:.2f}%",
              f"{(res['strat_maxdd']-res['bh_maxdd'])*100:+.2f}% vs 持有")

    cmp = pd.DataFrame({
        "指标": ["总收益", "年化收益", "夏普比率", "最大回撤"],
        "双均线策略": [res["strat_total"]*100, res["strat_ann"]*100,
                     res["strat_sharpe"], res["strat_maxdd"]*100],
        "买入持有": [res["bh_total"]*100, res["bh_ann"]*100,
                    res["bh_sharpe"], res["bh_maxdd"]*100],
    })
    cmp_disp = cmp.copy()
    for c in ["双均线策略", "买入持有"]:
        cmp_disp[c] = cmp_disp[c].map(lambda x: f"{x:.2f}%")
    st.table(cmp_disp)

    verdict = "✅ 策略跑赢买入持有（年化）" if res["beat"] else "⚠️ 策略未跑赢买入持有（年化）"
    st.info(verdict + "　注：单标的单周期结果，不构成投资建议。")

    # 趋势过滤开启时，额外展示"持仓占比/入场次数"并给出诚实解读
    if res.get("filter_ma"):
        hc1, hc2 = st.columns(2)
        hc1.metric("持仓占比", f"{res['hold_ratio']*100:.1f}%")
        hc2.metric("入场次数", f"{res['n_trades']}")
        st.caption(
            f"🔍 已启用 MA{res['filter_ma']} 趋势过滤（门控式）：仅当收盘价高于该长期均线时才允许金叉买入。"
            "回撤下降可能部分来自「在场时间变短」（持仓占比已给出），夏普未必改善——"
            "属风控增强而非收益增强，与多标的统计结论一致。")

    # —— 2.5) 沪深300 指数基准（判断是否有真正的市场 alpha）——
    if res.get("idx_ann") is not None:
        st.subheader("🏛️ 沪深300 指数基准（是否有真 alpha）")
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("沪深300 年化", f"{res['idx_ann']*100:.2f}%")
        ic2.metric("Beta（对沪深300）", f"{res['idx_beta']:.2f}")
        ic3.metric("年化 Alpha（约）", f"{res['idx_alpha']*100:.2f}%")
        st.caption("Alpha ≈ 策略年化 − Beta×指数年化（无风险利率取 0）。"
                   "仅跑赢「同标的买入持有」不够，Alpha>0 才说明真正跑赢市场、而非靠 Beta 暴露。")

    # —— 3) 资金曲线 ——
    if "strat_tr" in res and "bh_tr" in res and len(res["strat_tr"]) > 1:
        st.subheader("📈 资金曲线（策略 vs 买入持有）")
        strat_eq = (1 + res["strat_tr"]).cumprod()
        bh_eq = (1 + res["bh_tr"]).cumprod()
        eq_fig = go.Figure()
        eq_fig.add_trace(go.Scatter(x=strat_eq.index, y=strat_eq.values,
                                   name="双均线策略", mode="lines"))
        eq_fig.add_trace(go.Scatter(x=bh_eq.index, y=bh_eq.values,
                                   name="买入持有", mode="lines"))
        eq_fig.update_layout(height=400, yaxis_title="净值（初始=1）",
                            legend=dict(orientation="h", y=1.02, x=0),
                            margin=dict(l=40, r=20, t=30, b=40))
        st.plotly_chart(eq_fig, use_container_width=True)

    st.divider()
    st.caption("数据来源：akshare（东方财富/新浪）｜ 回测框架：backtrader ｜ 仅用于学习演示")


if __name__ == "__main__":
    main()

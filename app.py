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

from data_utils import get_price, add_ma
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


@st.cache_data(show_spinner="正在拉取行情（首次会联网）...")
def load_data(symbol, start, end, adjust="qfq"):
    """带缓存的行情获取（与回测共用本地缓存文件，不会重复联网）。"""
    return get_price(symbol, start, end, adjust)


@st.cache_data(show_spinner="回测中...")
def run_backtest(symbol, start, end, fast, slow, adjust="qfq"):
    """缓存回测结果，避免侧栏微调导致的重复计算。"""
    return backtest_run(symbol, start, end, fast, slow, verbose=False)


def main():
    st.set_page_config(page_title="A股量化分析 Demo", layout="wide")
    st.title("📈 A股量化分析 Demo")
    st.caption("数据获取 · K线可视化 · 双均线策略回测 ｜ 面向简历的增量项目")

    # —— 侧栏参数 ——
    with st.sidebar:
        st.header("⚙️ 参数设置")
        choice = st.selectbox("选择股票", list(PRESETS.keys()))
        symbol = PRESETS[choice]
        custom = st.text_input("或手动输入代码（覆盖上方）", "")
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

    if fast >= slow:
        st.stop()

    # —— 1) 拉数据 + K线 ——
    try:
        raw = load_data(symbol, start, end, adjust)
    except Exception as e:
        st.error(f"行情获取失败：{e}（可能触发行情接口限流，请稍后重试）")
        st.stop()

    raw = raw.copy()
    raw["日期"] = pd.to_datetime(raw["日期"])
    raw = raw.sort_values("日期").set_index("日期")
    raw = add_ma(raw, windows=(fast, slow)).dropna(subset=[f"MA{fast}", f"MA{slow}"])

    st.subheader(f"📊 K线 + 均线（MA{fast}/MA{slow}）")
    fig = kline_figure(raw.reset_index(), symbol, fast, slow)
    st.plotly_chart(fig, use_container_width=True)

    # —— 2) 回测绩效 ——
    st.subheader("🧪 双均线策略回测（对比买入持有）")
    res = run_backtest(symbol, start, end, fast, slow, adjust)
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

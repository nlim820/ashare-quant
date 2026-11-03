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
import re
import sys
from datetime import datetime
from pathlib import Path

# 让仓库根目录的 app.py 能 import src/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data_utils import get_price, add_ma, is_fund, get_meta
from viz import kline_figure
from phase2_backtest import run as backtest_run
from anim_demo import render as render_anim

# —— 署名信息：只在这里定义，页面三处（标题下 / 侧栏底部 / 页脚）统一引用 ——
# 换真名或换账号时只改这一段，避免改漏导致前后不一致。
AUTHOR = "小陆"
GITHUB_USER = "nlim820"
GITHUB_PROFILE = f"https://github.com/{GITHUB_USER}"
GITHUB_REPO = f"{GITHUB_PROFILE}/ashare-quant"

# 预置标的池：个股 + 场内 ETF 分组维护，侧栏按「个股在前、基金在后」展示。
# ETF 的种子缓存是**腾讯源前复权**快照（data/raw/{code}_20200101_20231231_qfq.csv）；
# 不要用东财限流后的新浪回退数据当种子——那是不复权的，收益率会少掉分红部分。
PRESET_STOCKS = {
    "600519 贵州茅台": "600519",
    "000001 平安银行": "000001",
    "600036 招商银行": "600036",
    "000651 格力电器": "000651",
    "000333 美的集团": "000333",
    "600276 恒瑞医药": "600276",
    "601318 中国平安": "601318",
    "600900 长江电力": "600900",
}

PRESET_FUNDS = {
    "510300 沪深300ETF（基金）": "510300",
    "510500 中证500ETF（基金）": "510500",
    "159915 创业板ETF（基金）": "159915",
}

PRESETS = {**PRESET_STOCKS, **PRESET_FUNDS}

# 数据源选择映射（侧栏显示名 → get_price 的 source 参数）
SOURCE_LABELS = {
    "东方财富（默认）": "auto",
    "腾讯证券": "tx",
    "新浪财经": "sina",
}

DATE_FMT = "%Y%m%d"


def _parse_date(s: str):
    """严格解析 YYYYMMDD；非法返回 None（不抛异常，交给调用方提示）。"""
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner="正在拉取行情（首次会联网）...")
def load_data(symbol, start, end, adjust="qfq", source="auto"):
    """带缓存的行情获取（与回测共用本地缓存文件，不会重复联网）。

    ttl=3600：网页缓存 1 小时后自动失效，配合 data_utils 的 30 天磁盘 TTL，
    避免"永久缓存导致数据看起来永不更新"。返回的 DataFrame 带 attrs
    （fetched_at / adjust_note），用于在页面上标注数据快照日。
    """
    return get_price(symbol, start, end, adjust, source)


@st.cache_data(ttl=3600, show_spinner="回测中...")
def run_backtest(symbol, start, end, fast, slow, adjust="qfq", source="auto",
                 filter_ma=None, lot_size=None, cash=100000.0, cost_model="simple"):
    """缓存回测结果，避免侧栏微调导致的重复计算。"""
    return backtest_run(symbol, start, end, fast, slow, verbose=False,
                        adjust=adjust, source=source, filter_ma=filter_ma,
                        lot_size=lot_size, cash=cash, cost_model=cost_model)


def main():
    # page_title 会显示在浏览器标签页与分享卡片上，带上作者名便于他人转发时识别
    st.set_page_config(page_title=f"A股/基金量化分析 Demo ｜ {AUTHOR}", layout="wide")
    st.title("📈 A股/基金量化分析 Demo")
    st.caption("数据获取 · K线可视化 · 双均线策略回测 ｜ 支持 A股个股与场内 ETF")
    # 作者署名放在正文第一屏：手机端侧栏默认折叠，只放侧栏等于没有
    st.caption(f"👤 作者：{AUTHOR}　｜　GitHub [@{GITHUB_USER}]({GITHUB_PROFILE})"
               f"　｜　源码 [{GITHUB_USER}/ashare-quant]({GITHUB_REPO})")

    # —— 侧栏参数 ——
    with st.sidebar:
        st.header("⚙️ 参数设置")
        choice = st.selectbox("选择标的", list(PRESETS.keys()))
        symbol = PRESETS[choice]
        st.caption(f"已预置 {len(PRESET_STOCKS)} 只个股 + {len(PRESET_FUNDS)} 只场内 ETF"
                   "（ETF 为前复权种子快照，含分红调整）")
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

        # 动画演示（自包含渲染，不依赖任何外部网址）
        st.divider()
        st.subheader("🎬 动画演示")
        show_anim = st.checkbox(
            "在页面内播放双均线动画", value=False,
            help="把当前标的的真实行情做成动画：金叉买入、死叉清仓，以及长期均线"
                 "「安检门」如何拦掉下跌段的假金叉。动画由本页现场渲染（纯本地 "
                 "HTML/Canvas），不请求任何外部网址，也可暂停/重播。")
        if show_anim:
            st.caption("跟随当前标的与快慢线；安检门用长期均线（默认 240 日）。")

        # 可执行性（默认关闭 = 与论文/简历口径一致）
        st.divider()
        with st.expander("可执行性设置（默认关闭）"):
            st.caption("默认允许小数股、初始资金 10 万，与论文口径一致。"
                       "开启整手约束可看真实可执行性——高价股（如茅台）"
                       "在小资金下可能一手都买不起。")
            use_lot = st.checkbox("按 A 股整手（100 股）约束", value=False)
            cash = st.number_input("初始资金（元）", min_value=10000, max_value=100000000,
                                   value=100000, step=10000)
            use_real_cost = st.checkbox("计入真实成本（滑点+印花税+过户费）", value=False)
        lot_size = 100 if use_lot else None
        cost_model = "realistic" if use_real_cost else "simple"

        # 侧栏底部再放一次署名（桌面端常驻可见；手机端折叠，故正文另有署名）
        st.divider()
        st.caption(f"👤 {AUTHOR}　｜　GitHub [@{GITHUB_USER}]({GITHUB_PROFILE})")

    # —— 输入校验（早失败、给明确提示，而不是抛未捕获异常）——
    if not re.fullmatch(r"\d{6}", symbol):
        st.error(f"代码格式不正确：`{symbol}`。请输入 6 位数字（A股如 600519，ETF 如 510300）。")
        st.stop()
    d0, d1 = _parse_date(start), _parse_date(end)
    if d0 is None or d1 is None:
        st.error("日期格式不正确，请使用 YYYYMMDD（例如 20200101）。")
        st.stop()
    if d0 >= d1:
        st.error("开始日期必须早于结束日期。")
        st.stop()
    if (d1 - d0).days < 60:
        st.warning("区间不足 60 天，均线与回测结果可能不具参考性。")
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

    if raw is None or len(raw) == 0:
        st.error("未取到任何行情数据，请检查代码或日期区间。")
        st.stop()
    if len(raw) < 30:
        st.warning(f"仅取到 {len(raw)} 行数据，样本过少，回测结果不可靠。")

    raw = raw.copy()
    raw["日期"] = pd.to_datetime(raw["日期"])
    raw = raw.sort_values("日期").set_index("日期")
    # 动画要用完整序列（含长均线预热段），所以留一份 dropna 之前的
    raw_for_anim = raw.reset_index().copy()
    ma_windows = (fast, slow) + ((filter_ma,) if filter_ma else ())
    raw = add_ma(raw, windows=ma_windows).dropna(subset=[f"MA{fast}", f"MA{slow}"])
    if len(raw) < 30:
        st.error("扣除均线预热后数据不足 30 个交易日，请把区间拉长。")
        st.stop()

    asset_kind = "ETF基金" if is_fund(symbol) else "A股个股"
    flt_txt = f"｜ 趋势过滤：MA{filter_ma}" if filter_ma else "｜ 趋势过滤：关"
    st.caption(f"当前标的：{symbol}（{asset_kind}）｜ 数据源：{source_label}｜ 复权：{adjust}{flt_txt}")

    # 数据快照日 + 复权口径提示（前复权会随最新价漂移，必须标出来）
    meta = get_meta(symbol, start, end, adjust, source)
    snap = meta.get("fetched_at") or raw.attrs.get("fetched_at") or "仓库内种子快照（无拉取时间）"
    st.caption(f"🗓️ 数据快照：{snap}　｜　区间 {raw.index[0].date()} ~ {raw.index[-1].date()}"
               f"（{len(raw)} 个交易日）")
    if meta.get("adjust_note") == "sina_noadj" or raw.attrs.get("adjust_note") == "sina_noadj":
        st.warning("⚠️ 本次数据来自新浪备用源，该源**不复权**：历史价格未做过除权调整，"
                   "收益与回撤会与复权口径存在偏差。")
    elif raw.attrs.get("adjust_note") == "stale_cache":
        st.info("ℹ️ 本次使用本地旧缓存（刷新失败），数据可能不是最新。")

    # —— 1.5) 双均线动画（可选）——
    # 放在 K 线之前：先让人看懂"策略在做什么"，再看原始数据。
    if show_anim:
        # 手动输入代码时，下拉框的标的简称就与 symbol 不符了，此时不要带上名字
        _name = ""
        if PRESETS.get(choice) == symbol and " " in choice:
            _name = choice.split(" ", 1)[1].replace("（基金）", "")
        with st.expander("🎬 双均线「安检门」动画 · 可暂停/重播", expanded=True):
            st.caption("画面由本页**现场渲染**（纯本地 HTML/Canvas，零外部请求），"
                       "所以不会因为临时托管过期而变成死链；标的与快慢线跟随左侧设置。")
            try:
                _html = render_anim(raw_for_anim, symbol, name=_name,
                                    fast=fast, slow=slow,
                                    filter_ma=filter_ma or 240, adjust=adjust)
                # st.iframe 取代已弃用的 st.components.v1.html
                #（后者官方标注 2026-06-01 后移除，而本项目线上跑的是新版 Streamlit）。
                # 高度按实测内容给足：不够的话底部说明会被裁掉。
                st.iframe(_html, height=990)
            except Exception as _e:  # 动画坏了不能拖垮主流程
                st.info(f"动画渲染失败（{type(_e).__name__}）：{_e}。不影响下面的 K 线与回测。")

    st.subheader(f"📊 K线 + 均线（MA{fast}/MA{slow}）")
    fig = kline_figure(raw.reset_index(), symbol, fast, slow, filter_ma=filter_ma)
    # 用 width="stretch" 而不是 use_container_width=True：
    # 后者已被 Streamlit 标记为 2025-12-31 后移除，长期部署会突然失效。
    st.plotly_chart(fig, width="stretch")

    # —— 2) 回测绩效 ——
    st.subheader("🧪 双均线策略回测（对比买入持有）")
    res = run_backtest(symbol, start, end, fast, slow, adjust, source, filter_ma,
                       lot_size, cash, cost_model)
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

    # 可执行性/成本口径提示：让"这组数字是在什么假设下算的"永远可见
    if lot_size or cost_model == "realistic":
        bits = []
        if lot_size:
            bits.append(f"整手约束 {lot_size} 股、初始资金 {cash:,.0f} 元")
        if cost_model == "realistic":
            bits.append("含滑点0.1%+印花税0.1%/0.05%+过户费")
        st.info("本结果口径：" + "；".join(bits)
                + (f"　｜　实际入场 {res['n_trades']} 次，持仓占比 {res['hold_ratio']*100:.1f}%"
                   if lot_size else ""))
        if lot_size and res["n_trades"] == 0:
            st.warning("整手约束下**一次都没买进**：该标的一手价格已超过账户可用资金。"
                       "这正是高价股在小资金下的真实约束。")

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
            "属风控增强而非收益增强。")

    # —— 2.5) 沪深300 指数基准（判断是否有真正的市场 alpha）——
    if res.get("idx_ann") is not None:
        st.subheader("🏛️ 沪深300 指数基准（是否有真 alpha）")
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("沪深300 年化", f"{res['idx_ann']*100:.2f}%")
        ic2.metric("Beta（对沪深300）", f"{res['idx_beta']:.2f}")
        if res.get("idx_alpha_ols") is not None:
            ic3.metric("年化 Alpha（回归截距）", f"{res['idx_alpha_ols']*100:.2f}%",
                       f"t={res['idx_alpha_t']:.2f}")
        else:
            ic3.metric("年化 Alpha（近似）", f"{res['idx_alpha']*100:.2f}%")
        if res.get("idx_alpha_p") is not None:
            sig = "显著" if res["idx_alpha_p"] < 0.05 else "不显著"
            st.caption(
                f"Alpha 为 CAPM 回归截距（Newey-West 稳健标准误，p={res['idx_alpha_p']:.3f}，{sig}）。"
                f"近似口径（年化相减）为 {res['idx_alpha']*100:.2f}%，仅作对照、不宜单独引用。"
                "仅跑赢「同标的买入持有」不够，Alpha>0 且显著才说明真正跑赢市场。")
        else:
            st.caption("Alpha ≈ 策略年化 − Beta×指数年化（无风险利率取 0）。"
                       "仅跑赢「同标的买入持有」不够，Alpha>0 才说明真正跑赢市场。")

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
        st.plotly_chart(eq_fig, width="stretch")

    st.divider()
    st.caption("数据来源：akshare（东方财富/新浪/腾讯）｜ 回测框架：backtrader ｜ 仅用于学习演示，不构成投资建议")
    st.caption(f"作者：{AUTHOR}（GitHub [@{GITHUB_USER}]({GITHUB_PROFILE})）"
               f"　｜　源码：[{GITHUB_USER}/ashare-quant]({GITHUB_REPO})"
               f"　｜　如发现口径错误或数字无法复现，欢迎在仓库提 Issue。")


if __name__ == "__main__":
    main()

"""双均线「安检门」动画：把当前标的的真实行情渲染成自包含 HTML。

背景（为什么要自己渲染，而不是挂个外链）：
    动画最初是独立页面（`anim/单文件演示_茅台.html` + `anim/` 本地服务版），
    曾托管在临时域名上。临时托管会过期，现已返回 403，外链等于死链。
    所以改成**把动画内嵌进网页**：用页面当前加载的行情 + 当前均线参数现场渲染，
    产物是纯 HTML/CSS/Canvas，零外部请求、零后端依赖，离线也能播。

模板来源：
    `assets/anim_template.html` 由 `anim/单文件演示_茅台.html` 改造而来——把写死的
    茅台数据与茅台专属文案（2020–2026、持仓 44%→19% 等）抽成 `{{...}}` 占位符，
    本模块负责填值。模板里只有 price / dates 两个数组和 FAST/SLOW/FILTER 三个常量
    是变量，其余是纯展示。改模板后记得同步跑 `tests/test_core.py::TestAnimDemo`。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "anim_template.html"

# 播放时长（秒）≈ 每 50 个交易日 1 秒；夹在 10–45 秒之间，长区间不至于看睡着
_SECONDS_PER_BAR = 50.0
_DUR_MIN, _DUR_MAX = 10, 45


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(raw_df: pd.DataFrame, symbol: str, name: str = "",
           fast: int = 5, slow: int = 20, filter_ma: int | None = 240,
           adjust: str = "qfq") -> str:
    """渲染动画 HTML。

    参数
    ----
    raw_df : 含「日期」「收盘」两列的行情（不要提前 dropna 均线列，长均线需要预热段）
    symbol : 6 位代码
    name   : 标的简称，可为空
    fast/slow : 快慢线周期
    filter_ma : 趋势过滤线周期；None 时退回 240（动画里的开关仍可自行关掉）
    adjust : 复权口径，仅用于文案

    返回
    ----
    完整的自包含 HTML 字符串，可直接交给 st.components.v1.html 渲染。
    """
    if raw_df is None or len(raw_df) < max(slow, 5) + 2:
        raise ValueError(f"行情太短（{0 if raw_df is None else len(raw_df)} 行），无法渲染动画")

    df = raw_df.copy()
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")
    price = [round(float(v), 3) for v in df["收盘"].tolist()]
    dates = df["日期"].dt.strftime("%Y-%m-%d").tolist()
    n = len(price)

    filt = int(filter_ma or 240)
    duration = int(min(_DUR_MAX, max(_DUR_MIN, round(n / _SECONDS_PER_BAR))))

    label = f"{symbol} {name}".strip()
    kind = "ETF 基金" if str(symbol).startswith(("5", "15", "16", "18")) else "个股"
    adj_txt = "前复权" if adjust == "qfq" else ("后复权" if adjust == "hfq" else "不复权")

    title = f"双均线 · {label} · 趋势过滤「安检门」"
    h1 = f"双均线策略 · {label} · {dates[0]} 至 {dates[-1]}"
    desc = (f"数据：{_esc(label)}（{kind}）日线{adj_txt}，{dates[0]} 至 {dates[-1]}，"
            f"共 <b>{n}</b> 个交易日，取自本页当前加载的行情。<br>"
            f"趋势线为 <b style=\"color:var(--filter)\">MA{filt}</b>（{filt} 日均线）："
            f"长期趋势向上时金叉才买入，下跌段的假金叉被安检门拦掉；死叉清仓不受安检影响。")
    note = (
        f"下方时间条：<b style=\"color:var(--pass)\">绿色＝持仓</b>，灰色＝空仓。"
        f"关掉安检门再打开对比一下：绿色段会明显变短——这就是回测里「持仓占比腰斩」的来源。"
        f"回撤变小，多半是因为<b>少冒了下跌段的风险</b>，而不是信号变聪明了"
        f"（本项目 20 只标的的检验结论是：回撤改善不显著，夏普反而变差，只能称方向性证据）。"
        f"<br>动画只负责把规则画清楚，不构成任何收益判断；真正的检验见 README 的三口径 p 值。"
    )

    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "TITLE": _esc(title), "H1": _esc(h1), "DESC": desc, "NOTE": note,
        "PRICE": json.dumps(price, separators=(",", ":")),
        "DATES": json.dumps(dates, separators=(",", ":")),
        "FAST": fast, "SLOW": slow, "FILTER": filt, "DURATION": duration,
    }.items():
        html = html.replace("{{" + key + "}}", str(val))

    if "{{" in html:
        raise RuntimeError("模板占位符未全部替换，检查 assets/anim_template.html")
    return html

"""可视化模块：把行情 DataFrame 画成 plotly K线 + 均线图。

被 phase1_kline.py（命令行生成 HTML）与 app.py（Streamlit 网页）共用，
保证「画图逻辑只有一份」，避免重复代码。
"""
import plotly.graph_objects as go


def kline_figure(df, symbol, fast=5, slow=20, filter_ma=None, height=520):
    """返回带 K线 + MA(fast)/MA(slow)（+ 可选趋势过滤线）的 plotly Figure。

    入参 df 需包含列：日期、开盘、最高、最低、收盘，以及 MA{fast}、MA{slow}；
    若传入 filter_ma 且对应 MA 列存在，额外叠加一条虚线作为趋势过滤"安检门"。
    """
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["日期"], open=df["开盘"], high=df["最高"],
        low=df["最低"], close=df["收盘"], name="K线",
    ))
    for w in (fast, slow):
        col = f"MA{w}"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["日期"], y=df[col], mode="lines",
                name=f"MA{w}", line=dict(width=1.5),
            ))
    if filter_ma and f"MA{filter_ma}" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["日期"], y=df[f"MA{filter_ma}"], mode="lines",
            name=f"MA{filter_ma}（过滤）",
            line=dict(width=1.2, dash="dash", color="#ff7f0e"),
        ))
    title = f"{symbol} 日线 K线 + MA{fast}/MA{slow}"
    if filter_ma:
        title += f" + MA{filter_ma}（过滤）"
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="价格（元）",
        xaxis_rangeslider_visible=False,   # 隐藏底部缩放条，更清爽
        legend=dict(orientation="h", y=1.02, x=0),
        height=height,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig

"""Phase 1 - 步骤二：用 plotly 把行情画成可交互的 K线图。

学习目标：
- 认识 plotly（交互式图表库，可缩放/悬停看数值）
- 理解 K线四价：开盘(open)、收盘(close)、最高(high)、最低(low)
"""
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

# 读取步骤一生成的 CSV
CSV = Path(__file__).resolve().parent.parent / "data" / "stock_600519_daily.csv"
# 生成的图表也放在 data/（已被 .gitignore 忽略，不会进仓库）
OUT_HTML = Path(__file__).resolve().parent.parent / "data" / "kline.html"


def plot() -> None:
    df = pd.read_csv(CSV)

    # Candlestick 就是 K线图
    fig = go.Figure(data=[go.Candlestick(
        x=df["日期"],
        open=df["开盘"], high=df["最高"], low=df["最低"], close=df["收盘"],
        name="K线",
    )])
    fig.update_layout(
        title="贵州茅台 600519 日线 K线图",
        xaxis_title="日期",
        yaxis_title="价格（元）",
        xaxis_rangeslider_visible=False,  # 隐藏底部缩放条，更清爽
    )

    fig.write_html(OUT_HTML)   # 保存为网页，方便分享/写进简历
    print(f"✅ K线图已保存到：{OUT_HTML}")
    try:
        fig.show()             # 在浏览器打开交互图（无桌面环境时自动跳过）
    except Exception:
        print("提示：当前环境无法自动打开浏览器，直接用浏览器打开上面的 HTML 文件即可。")


if __name__ == "__main__":
    plot()

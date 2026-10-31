"""Phase 1 增强版：可切换股票的交互式 K线 + 均线工具。

相比 phase1_fetch.py / phase1_plot.py（写死茅台），本脚本：
- 用命令行参数切换任意 A股代码（--symbol）
- 自动计算并叠加 MA5 / MA20 两条均线
- 一只命令完成「拉数据 → 算均线 → 画交互图」

"取数/算均线"逻辑已抽到 data_utils.py 共用，本文件只负责画图与命令行入口。
"""
import argparse
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from data_utils import fetch, add_ma

# 项目根目录 / data 目录（图表放这里，已被 .gitignore 忽略，不会进仓库）
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)


def plot(df: pd.DataFrame, symbol: str) -> Path:
    """画 K线 + 均线，保存为 HTML，返回文件路径。"""
    out_html = DATA / f"kline_{symbol}.html"

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["日期"], open=df["开盘"], high=df["最高"],
        low=df["最低"], close=df["收盘"], name="K线",
    ))
    for w in (5, 20):
        fig.add_trace(go.Scatter(
            x=df["日期"], y=df[f"MA{w}"], mode="lines",
            name=f"MA{w}", line=dict(width=1.5),
        ))

    fig.update_layout(
        title=f"{symbol} 日线 K线 + MA5/MA20",
        xaxis_title="日期",
        yaxis_title="价格（元）",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0),
    )

    fig.write_html(out_html)
    print(f"✅ 图表已保存到：{out_html}")
    return out_html


def main() -> None:
    parser = argparse.ArgumentParser(description="A股 K线 + 均线交互图生成器")
    parser.add_argument("--symbol", default="600519", help="股票代码，不带前缀，如 600519")
    parser.add_argument("--start", default="20230101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default="20231231", help="结束日期 YYYYMMDD")
    parser.add_argument("--adjust", default="qfq", help="复权方式：qfq 前复权 / hfq 后复权")
    args = parser.parse_args()

    print(f"📥 正在拉取 {args.symbol} 的日线行情（{args.start}~{args.end}）...")
    df = fetch(args.symbol, args.start, args.end, args.adjust)
    print(f"   已获取 {len(df)} 行数据。")

    df = add_ma(df)
    plot(df, args.symbol)

    print("\n最新 3 行（含均线）：")
    cols = ["日期", "收盘", "MA5", "MA20"]
    print(df[cols].tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

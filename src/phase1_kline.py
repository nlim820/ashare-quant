"""Phase 1 增强版：可切换股票的交互式 K线 + 均线工具。

相比 phase1_fetch.py / phase1_plot.py（写死茅台），本脚本：
- 用命令行参数切换任意 A股代码（--symbol）
- 自动计算并叠加 MA5 / MA20 两条均线
- 一只命令完成「拉数据 → 算均线 → 画交互图」

金融小知识：
- 均线（MA, Moving Average）是把最近 N 天的收盘价取平均，平滑短期波动。
- MA5 = 近 5 日收盘均价；MA20 ≈ 近一个月（约 20 个交易日）均价。
- 实战里常看「金叉/死叉」：短期均线上穿长期均线叫金叉（偏多），下穿叫死叉（偏空）。
  这正是 Phase 2 双均线策略要复现的核心信号。

用法示例（在命令行）：
    python src/phase1_kline.py --symbol 600519 --start 20230101 --end 20231231
    python src/phase1_kline.py --symbol 000001 --start 20230101 --end 20231231
"""
import argparse
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path

# 东方财富偶发限流时，自动切换到新浪数据源（另一台服务器）
try:
    from akshare.utils.http import Push2RateLimitError
except Exception:  # 老版本 akshare 可能未单独导出该异常
    Push2RateLimitError = Exception

# 项目根目录 / data 目录（图表放这里，已被 .gitignore 忽略，不会污染仓库）
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)


def fetch(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """拉取单只 A股日线行情，返回 DataFrame。

    优先用东方财富（列名为中文，含更多字段）；若被限流，则回退新浪
    数据源，并把列名统一成中文，保证后续画图和算均线逻辑不变。
    """
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust=adjust,
        )
        return df
    except Push2RateLimitError:
        print("   ⚠️ 东方财富被限流，自动切换新浪数据源...")
        # 新浪接口代码要带交易所前缀：6 开头=sh，0/3 开头=sz
        prefix = "sh" if symbol.startswith("6") else "sz"
        sina = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}", start_date=start,
            end_date=end, adjust=adjust,
        )
        # 新浪列名是英文，翻译成东方财富的中文列名，下游无需改动
        sina = sina.rename(columns={
            "date": "日期", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "volume": "成交量",
        })
        return sina


def add_ma(df: pd.DataFrame, windows=(5, 20)) -> pd.DataFrame:
    """在 DataFrame 上新增 MA5 / MA20 列（基于收盘价）。"""
    for w in windows:
        df[f"MA{w}"] = df["收盘"].rolling(window=w).mean()
    return df


def plot(df: pd.DataFrame, symbol: str) -> Path:
    """画 K线 + 均线，保存为 HTML，返回文件路径。"""
    out_html = DATA / f"kline_{symbol}.html"

    fig = go.Figure()
    # 1) K线（蜡烛图）
    fig.add_trace(go.Candlestick(
        x=df["日期"], open=df["开盘"], high=df["最高"],
        low=df["最低"], close=df["收盘"], name="K线",
    ))
    # 2) 均线（基于收盘价计算，叠在同一坐标系）
    for w in (5, 20):
        fig.add_trace(go.Scatter(
            x=df["日期"], y=df[f"MA{w}"], mode="lines",
            name=f"MA{w}", line=dict(width=1.5),
        ))

    fig.update_layout(
        title=f"{symbol} 日线 K线 + MA5/MA20",
        xaxis_title="日期",
        yaxis_title="价格（元）",
        xaxis_rangeslider_visible=False,  # 隐藏底部缩放条，更清爽
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

    # 顺手打印均线最近 3 行，方便核对计算是否正确
    print("\n最新 3 行（含均线）：")
    cols = ["日期", "收盘", "MA5", "MA20"]
    print(df[cols].tail(3).to_string(index=False))


if __name__ == "__main__":
    main()

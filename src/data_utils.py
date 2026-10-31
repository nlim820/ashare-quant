"""数据工具模块：被 Phase 1 / Phase 2 共用，避免重复代码。

提供两个核心函数：
- fetch(): 拉取单只 A股日线行情（东方财富优先，限流自动回退新浪）
- add_ma(): 在行情上计算 MA5 / MA20 均线

金融/工程知识点：
- 把"取数"和"画图/回测"解耦，是真实量化项目的标准做法：
  数据层只管产出干净的 DataFrame，上游（可视化、回测）各自消费。
"""
import akshare as ak
import pandas as pd
from pathlib import Path

try:
    from akshare.utils.http import Push2RateLimitError
except Exception:  # 老版本 akshare 可能未单独导出该异常
    Push2RateLimitError = Exception

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)


def fetch(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """拉取单只 A股日线行情，返回 DataFrame（列名为中文）。

    优先东方财富；若被限流，自动切换新浪并统一列名，下游无需改动。
    """
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust=adjust,
        )
        return df
    except Push2RateLimitError:
        print("   ⚠️ 东方财富被限流，自动切换新浪数据源...")
        prefix = "sh" if symbol.startswith("6") else "sz"
        sina = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}", start_date=start,
            end_date=end, adjust=adjust,
        )
        sina = sina.rename(columns={
            "date": "日期", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "volume": "成交量",
        })
        return sina


def add_ma(df: pd.DataFrame, windows=(5, 20)) -> pd.DataFrame:
    """基于收盘价计算 MA5 / MA20 等均线列。"""
    for w in windows:
        df[f"MA{w}"] = df["收盘"].rolling(window=w).mean()
    return df

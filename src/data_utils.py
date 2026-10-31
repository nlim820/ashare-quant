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


def is_fund(symbol: str) -> bool:
    """判断 6 位代码是否为场内基金（ETF/LOF/封基）。

    股票代码段：60/68（沪）、00/30（深）；基金代码段：50/51/56/58（沪）、
    15/16/18（深）。用代码前缀区分，无需新增显式开关。
    """
    s = symbol.strip()
    return len(s) == 6 and s.isdigit() and s[:2] in (
        "50", "51", "56", "58", "15", "16", "18",
    )


def fund_fetch(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """拉取单只场内基金（ETF/LOF）日线行情，返回与股票同构的 DataFrame。

    使用东方财富 ETF 接口；把可能出现的列名（中/英/异体）统一成项目标准列
    「日期/开盘/收盘/最高/最低/成交量」，因此下游的 add_ma / 回测 / 画图逻辑
    与股票完全共用，无需改动。
    """
    df = ak.fund_etf_hist_em(
        symbol=symbol, period="daily",
        start_date=start, end_date=end, adjust=adjust,
    )
    rename_map = {
        "date": "日期", "日期": "日期",
        "open": "开盘", "开盘": "开盘", "开盘价": "开盘",
        "close": "收盘", "收盘": "收盘", "收盘价": "收盘",
        "high": "最高", "最高": "最高",
        "low": "最低", "最低": "最低",
        "volume": "成交量", "成交量": "成交量",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    keep = ["日期", "开盘", "收盘", "最高", "最低", "成交量"]
    return df[[c for c in keep if c in df.columns]]


def add_ma(df: pd.DataFrame, windows=(5, 20)) -> pd.DataFrame:
    """基于收盘价计算 MA5 / MA20 等均线列。"""
    for w in windows:
        df[f"MA{w}"] = df["收盘"].rolling(window=w).mean()
    return df


def get_price(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """取行情，带本地缓存：已下载过就直接读 CSV，避免重复联网/触发限流。

    缓存文件放在 data/raw/（已被 .gitignore 忽略，不会进仓库）。
    """
    cache_dir = DATA / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}_{start}_{end}.csv"
    if path.exists():
        return pd.read_csv(path, encoding="utf-8-sig")
    df = fund_fetch(symbol, start, end, adjust) if is_fund(symbol) else fetch(symbol, start, end, adjust)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def get_index(symbol: str = "sh000300", start: str = "20200101",
              end: str = "20231231") -> pd.DataFrame:
    """取指数日线（默认沪深300 sh000300），带本地缓存。

    返回含「日期 / 收盘」两列的 DataFrame，用于把策略收益与「市场基准」比较，
    从而判断策略是否真有 alpha（跑赢个股买入持有 ≠ 跑赢市场）。
    """
    cache_dir = DATA / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"idx_{symbol}_{start}_{end}.csv"
    if path.exists():
        return pd.read_csv(path, encoding="utf-8-sig")
    idx = ak.stock_zh_index_daily(symbol=symbol)
    idx = idx.rename(columns={"date": "日期", "close": "收盘"})
    idx["日期"] = pd.to_datetime(idx["日期"])
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    idx = idx[(idx["日期"] >= s) & (idx["日期"] <= e)][["日期", "收盘"]]
    idx.to_csv(path, index=False, encoding="utf-8-sig")
    return idx



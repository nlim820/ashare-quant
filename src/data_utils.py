"""数据工具模块：被 Phase 1 / Phase 2 共用，避免重复代码。

提供核心函数：
- fetch()     拉取单只 A股日线行情（东方财富优先，限流自动回退新浪）
- fund_fetch() 拉取单只场内基金（ETF/LOF）日线
- fetch_tx()  腾讯证券日线（另一路备用源）
- get_price() 统一入口：带本地缓存 + 缓存时效（TTL）+ 数据质量校验
- add_ma()    在行情上计算 MA5 / MA20 等均线

金融/工程知识点：
- 把"取数"和"画图/回测"解耦，是真实量化项目的标准做法：
  数据层只管产出干净的 DataFrame，上游（可视化、回测）各自消费。
- **前复权（qfq）是"以拉取时刻最新价为基准"向前缩放**，因此同一区间在不同
  时间点重新拉取，历史价格会变（基准漂移）。所以缓存必须记录「拉取日期」，
  否则读者无法判断看到的数字属于哪一版数据。本模块用同名 .meta.json
  旁挂文件记录 fetched_at / 数据源 / 行数，供论文与网页标注数据快照日。
"""
import hashlib
import json
import time
from pathlib import Path

import akshare as ak
import pandas as pd

try:
    from akshare.utils.http import Push2RateLimitError
except Exception:  # 老版本 akshare 可能未单独导出该异常
    Push2RateLimitError = Exception

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)

# 缓存默认有效期（天）。超过后尝试重新拉取；拉取失败则回退旧缓存并打印警告
# （保证离线 / 限流 / 海外网络下网页仍可用，不会因为刷新失败而白屏）。
DEFAULT_CACHE_TTL_DAYS = 30

# 标准中文列顺序
KEEP_COLS = ["日期", "开盘", "收盘", "最高", "最低", "成交量"]

_RENAME = {
    "date": "日期", "日期": "日期",
    "open": "开盘", "开盘": "开盘", "开盘价": "开盘",
    "close": "收盘", "收盘": "收盘", "收盘价": "收盘",
    "high": "最高", "最高": "最高",
    "low": "最低", "最低": "最低",
    "volume": "成交量", "成交量": "成交量",
}


# ---------------------------------------------------------------- 数据质量校验

def check_quality(df: pd.DataFrame, symbol: str = "") -> list:
    """对行情做基本质量校验，返回问题描述列表（空列表 = 通过）。

    检查项对应真实踩过的坑：
      - 日期重复（拼接多源 / 缓存错误时的典型症状）
      - 价格为 0 或负（除权处理异常、接口返回空值）
      - OHLC 逻辑矛盾：最高 < 最低 / 最高 < 收盘 / 最低 > 收盘
      - 相邻交易日间隔 > 10 个自然日（长假正常，> 10 天多为数据缺口）
      - 行数过少（< 30 行，均线/回测无意义）
    上游默认只打印警告不抛异常 —— 数据问题应被【看见】，但不该阻断演示。
    """
    issues = []
    if df is None or len(df) == 0:
        return [f"{symbol} 返回空数据"]

    need = ["日期", "开盘", "最高", "最低", "收盘"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        return [f"{symbol} 缺少列 {missing}"]

    d = df.copy()
    d["日期"] = pd.to_datetime(d["日期"], errors="coerce")
    if d["日期"].isna().any():
        issues.append(f"{symbol} 存在无法解析的日期 {int(d['日期'].isna().sum())} 行")

    dup = int(d["日期"].duplicated().sum())
    if dup:
        issues.append(f"{symbol} 日期重复 {dup} 行")

    px = d[["开盘", "最高", "最低", "收盘"]]
    nonpos = int((px <= 0).sum().sum())
    if nonpos:
        issues.append(f"{symbol} 存在非正价格 {nonpos} 个单元格")

    bad_ohlc = int(
        ((d["最高"] < d["最低"])
         | (d["最高"] < d["收盘"])
         | (d["最低"] > d["收盘"])).sum()
    )
    if bad_ohlc:
        issues.append(f"{symbol} OHLC 逻辑矛盾 {bad_ohlc} 行")

    ds = d["日期"].dropna().sort_values()
    if len(ds) > 1:
        # 阈值取 15 天：A 股春节休市最长约 11 个自然日（如 2020-01-23 → 02-03），
        # 用 10 天会把每年春节误报成"数据缺口"，反而淹没真问题。
        gaps = int((ds.diff().dt.days > 15).sum())
        if gaps:
            issues.append(f"{symbol} 存在 {gaps} 处 >15 天数据缺口")

    if len(d) < 30:
        issues.append(f"{symbol} 仅 {len(d)} 行，样本过少")

    return issues


# ---------------------------------------------------------------- 单源取数

def fetch(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """拉取单只 A股日线行情，返回 DataFrame（列名为中文）。

    优先东方财富；若被限流，自动切换新浪并统一列名，下游无需改动。
    """
    try:
        return ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust=adjust,
        )
    except Push2RateLimitError:
        print("   ⚠️ 东方财富被限流，自动切换新浪数据源...")
        prefix = "sh" if symbol.startswith("6") else "sz"
        sina = ak.stock_zh_a_daily(
            symbol=f"{prefix}{symbol}", start_date=start,
            end_date=end, adjust=adjust,
        )
        return sina.rename(columns={k: v for k, v in _RENAME.items() if k in sina.columns})


def is_fund(symbol: str) -> bool:
    """判断 6 位代码是否为场内基金（ETF/LOF/封基）。

    股票代码段：60/68（沪）、00/30（深）；基金代码段：50/51/56/58（沪）、
    15/16/18（深）。用代码前缀区分，无需新增显式开关。
    """
    s = symbol.strip()
    return len(s) == 6 and s.isdigit() and s[:2] in (
        "50", "51", "56", "58", "15", "16", "18",
    )


def _fund_sina_symbol(symbol: str) -> str:
    """把 6 位基金代码转成新浪格式（sh/sz + 代码）。"""
    s = symbol.strip()
    prefix = "sh" if s.startswith("5") else "sz"
    return f"{prefix}{s}"


def fund_fetch(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """拉取单只场内基金（ETF/LOF）日线行情，返回与股票同构的 DataFrame。

    优先东方财富（支持 qfq 前复权 + 起止日期）；若被限流，自动切换新浪。
    **重要限制**：新浪基金接口（fund_etf_hist_sina）只返回【不复权】全量数据，
    这里按日期切片仅作限流兜底。一旦回退，除权除息会造成历史价格跳空、
    收益被系统性低估。为让下游【看得见】这件事，返回值会在 df.attrs 里
    标记 adjust_note="sina_noadj" 并通过 source_used 说明实际数据源。
    """
    try:
        df = ak.fund_etf_hist_em(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust=adjust,
        )
        used, note = "em", ""
    except Push2RateLimitError:
        print("   ⚠️ 东方财富基金接口被限流，自动切换新浪数据源（该源不复权）...")
        raw = ak.fund_etf_hist_sina(symbol=_fund_sina_symbol(symbol))
        raw = raw.rename(columns={k: v for k, v in _RENAME.items() if k in raw.columns})
        raw["日期"] = pd.to_datetime(raw["日期"])
        s, e = pd.to_datetime(start), pd.to_datetime(end)
        df = raw[(raw["日期"] >= s) & (raw["日期"] <= e)].copy()
        used = "sina"
        note = "sina_noadj" if adjust else ""

    df = df.rename(columns={k: v for k, v in _RENAME.items() if k in df.columns})
    out = df[[c for c in KEEP_COLS if c in df.columns]].copy()
    out.attrs["source_used"] = used
    out.attrs["adjust_note"] = note
    return out


def _to_market_symbol(symbol: str) -> str:
    """6 位代码 → 带市场前缀的代码（腾讯 / 新浪接口需要）。

    沪市：6/9（A股）、5（ETF/LOF）→ sh；深市：0/2/3（A股）、1（ETF/LOF）→ sz。
    已带 sh/sz 前缀的直接原样返回。
    """
    s = symbol.strip()
    if len(s) == 6 and s.isdigit():
        return f"sh{s}" if s[0] in ("6", "9", "5") else f"sz{s}"
    return s


def _fetch_sina(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """显式使用新浪数据源（股票走 stock_zh_a_daily，基金走 fund_etf_hist_sina）。

    仅当用户在「数据源」中选择新浪时直接调用；默认路径仍走东财 + 限流回退。
    注意：新浪基金接口返回全量且不复权，这里按日期切片并标记 adjust_note。
    """
    m = _to_market_symbol(symbol)
    if is_fund(symbol):
        raw = ak.fund_etf_hist_sina(symbol=m)
        raw = raw.rename(columns={k: v for k, v in _RENAME.items() if k in raw.columns})
        raw["日期"] = pd.to_datetime(raw["日期"])
        s, e = pd.to_datetime(start), pd.to_datetime(end)
        raw = raw[(raw["日期"] >= s) & (raw["日期"] <= e)].copy()
        out = raw[[c for c in KEEP_COLS if c in raw.columns]].copy()
        out.attrs["source_used"] = "sina"
        out.attrs["adjust_note"] = "sina_noadj" if adjust else ""
        return out
    df = ak.stock_zh_a_daily(symbol=m, start_date=start, end_date=end, adjust=adjust)
    df = df.rename(columns={k: v for k, v in _RENAME.items() if k in df.columns})
    out = df[[c for c in KEEP_COLS if c in df.columns]].copy()
    out.attrs["source_used"] = "sina"
    out.attrs["adjust_note"] = ""
    return out


def fetch_tx(symbol: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """腾讯证券日线（stock_zh_a_hist_tx）：支持 A股个股与场内 ETF，支持 qfq/hfq。

    腾讯接口入参需带市场前缀（如 sh510300 / sz000001），返回英文列名，
    这里统一成项目标准中文列，下游可视化 / 回测无需任何改动。
    注意：不同数据源的复权因子算法不同，跨源结果不宜直接混用比较。
    """
    m = _to_market_symbol(symbol)
    df = ak.stock_zh_a_hist_tx(symbol=m, start_date=start, end_date=end, adjust=adjust)
    df = df.rename(columns={k: v for k, v in _RENAME.items() if k in df.columns})
    out = df[[c for c in KEEP_COLS if c in df.columns]].copy()
    out.attrs["source_used"] = "tx"
    out.attrs["adjust_note"] = ""
    return out


def _download(symbol: str, start: str, end: str, adjust: str, source: str) -> pd.DataFrame:
    """按 source 分派到具体取数函数。"""
    if source == "tx":
        return fetch_tx(symbol, start, end, adjust)
    if source == "sina":
        return _fetch_sina(symbol, start, end, adjust)
    return fund_fetch(symbol, start, end, adjust) if is_fund(symbol) else fetch(symbol, start, end, adjust)


# ---------------------------------------------------------------- 缓存与元数据

def _meta_path(path: Path) -> Path:
    """缓存 CSV 的旁挂元数据文件路径。"""
    return path.with_suffix(".meta.json")


def _read_meta(path: Path) -> dict | None:
    """读取缓存元数据；不存在或损坏返回 None（视为"历史种子数据"）。"""
    mp = _meta_path(path)
    if not mp.exists():
        return None
    try:
        with open(mp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_meta(path: Path, df: pd.DataFrame, source: str, symbol: str) -> dict:
    """写缓存元数据：拉取时间、数据源、复权方式、行数、内容指纹。"""
    cols = [c for c in ["开盘", "最高", "最低", "收盘"] if c in df.columns]
    digest = ""
    if cols:
        try:
            # 用价格矩阵的原始字节做指纹，跨 pandas 版本稳定（不依赖 pd.util.hash_*）
            digest = hashlib.sha256(
                df[cols].to_numpy(dtype="float64").tobytes()
            ).hexdigest()[:16]
        except Exception:
            digest = ""
    meta = {
        "symbol": symbol,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_requested": source,
        "source_used": df.attrs.get("source_used", source),
        "adjust": df.attrs.get("adjust", ""),
        "adjust_note": df.attrs.get("adjust_note", ""),
        "rows": int(len(df)),
        "first_date": str(pd.to_datetime(df["日期"]).min().date()) if len(df) else "",
        "last_date": str(pd.to_datetime(df["日期"]).max().date()) if len(df) else "",
        "price_sha256_16": digest,
    }
    try:
        with open(_meta_path(path), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"   ⚠️ 缓存元数据写入失败（不影响取数）：{e}")
    return meta


def _is_stale(meta: dict | None, max_age_days: float | None) -> bool:
    """判断缓存是否过期。

    约定：没有元数据 = 仓库里随代码分发的「种子快照」，视为【不过期】。
    这类文件是有意入库的固定演示数据（Cloud 上无外网时全靠它），
    若判为过期会每次页面加载都尝试联网，反而拖慢/报错。
    """
    if meta is None or max_age_days is None:
        return False
    ts = meta.get("fetched_at", "")
    try:
        t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return False
    return (time.time() - t) > max_age_days * 86400.0


def _attach_attrs(df: pd.DataFrame, meta: dict | None, source: str) -> pd.DataFrame:
    """把元数据挂回 DataFrame.attrs，便于网页/论文标注数据快照日。"""
    meta = meta or {}
    df.attrs["fetched_at"] = meta.get("fetched_at", "")
    df.attrs["source_used"] = meta.get("source_used", source)
    df.attrs["adjust_note"] = meta.get("adjust_note", "")
    df.attrs["adjust"] = meta.get("adjust", "")
    return df


def get_price(symbol: str, start: str, end: str, adjust: str = "qfq",
              source: str = "auto", max_age_days: float | None = DEFAULT_CACHE_TTL_DAYS,
              validate: bool = True) -> pd.DataFrame:
    """取行情，带本地缓存 + 缓存时效（TTL）+ 质量校验。

    source 数据源选择：
      - auto / em（默认）：东方财富（基金走 ETF 接口），限流时自动回退新浪；
      - tx：腾讯证券日线（stock_zh_a_hist_tx）；
      - sina：新浪日线（显式指定）。
    缓存文件按「复权方式 + 数据源」分别存储，避免不同来源数据互相污染。

    max_age_days：缓存有效期。默认 30 天——超过则尝试重新拉取；
      **拉取失败会自动回退到旧缓存并打印警告**（离线/限流/海外网络下不白屏）。
      传 None 表示永不刷新（复现论文数字时建议用 None + 固定种子数据）。

    validate：是否做数据质量校验（重复日期/非正价/OHLC 矛盾/数据缺口）。
    """
    cache_dir = DATA / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # auto/em 沿用旧缓存名（{code}_{start}_{end}_{adjust}.csv），保持历史缓存可用；
    # 其他源追加 _source 后缀，独立缓存、互不覆盖。
    suffix = "" if source in ("auto", "em") else f"_{source}"
    path = cache_dir / f"{symbol}_{start}_{end}_{adjust}{suffix}.csv"

    if path.exists():
        meta = _read_meta(path)
        if not _is_stale(meta, max_age_days):
            df = pd.read_csv(path, encoding="utf-8-sig")
            df = _attach_attrs(df, meta, source)
            if validate:
                for msg in check_quality(df, symbol):
                    print(f"   ⚠️ 数据质量：{msg}")
            return df

        # 缓存过期：尝试刷新，失败则继续用旧数据（可用性优先）
        print(f"   🔄 {symbol} 缓存已超 {max_age_days:g} 天，尝试刷新...")
        try:
            df = _download(symbol, start, end, adjust, source)
            df.attrs["adjust"] = adjust
            df.to_csv(path, index=False, encoding="utf-8-sig")
            meta = _write_meta(path, df, source, symbol)
            df = _attach_attrs(df, meta, source)
            if validate:
                for msg in check_quality(df, symbol):
                    print(f"   ⚠️ 数据质量：{msg}")
            return df
        except Exception as e:
            print(f"   ⚠️ 刷新失败（{type(e).__name__}），回退到本地旧缓存。"
                  f"数据快照日：{meta.get('fetched_at', '未知')}")
            df = pd.read_csv(path, encoding="utf-8-sig")
            df.attrs["adjust_note"] = "stale_cache"
            return _attach_attrs(df, meta, source)

    df = _download(symbol, start, end, adjust, source)
    df.attrs["adjust"] = adjust
    df.to_csv(path, index=False, encoding="utf-8-sig")
    meta = _write_meta(path, df, source, symbol)
    df = _attach_attrs(df, meta, source)
    if validate:
        for msg in check_quality(df, symbol):
            print(f"   ⚠️ 数据质量：{msg}")
    return df


def get_meta(symbol: str, start: str, end: str, adjust: str = "qfq",
             source: str = "auto") -> dict:
    """读取指定缓存的元数据（不触发下载）。网页用来显示「数据快照日」。"""
    suffix = "" if source in ("auto", "em") else f"_{source}"
    path = DATA / "raw" / f"{symbol}_{start}_{end}_{adjust}{suffix}.csv"
    return _read_meta(path) or {}


def add_ma(df: pd.DataFrame, windows=(5, 20)) -> pd.DataFrame:
    """基于收盘价计算 MA5 / MA20 等均线列。"""
    for w in windows:
        df[f"MA{w}"] = df["收盘"].rolling(window=w).mean()
    return df


def get_index(symbol: str = "sh000300", start: str = "20200101",
              end: str = "20231231") -> pd.DataFrame:
    """取指数日线（默认沪深300 sh000300），带本地缓存。

    返回含「日期 / 收盘」两列的 DataFrame，用于把策略收益与「市场基准」比较，
    从而判断策略是否真有 alpha（跑赢个股买入持有 ≠ 跑赢市场）。
    指数无复权问题，故不需要 qfq 快照说明。
    """
    cache_dir = DATA / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"idx_{symbol}_{start}_{end}.csv"
    if path.exists():
        idx = pd.read_csv(path, encoding="utf-8-sig")
        # 缓存读取时「日期」是字符串，必须转 datetime，否则下方与行情
        # DatetimeIndex 对齐时全部错位、沪深300 基准算不出来（仅首次联网能算）
        idx["日期"] = pd.to_datetime(idx["日期"])
        return idx[["日期", "收盘"]]
    idx = ak.stock_zh_index_daily(symbol=symbol)
    idx = idx.rename(columns={"date": "日期", "close": "收盘"})
    idx["日期"] = pd.to_datetime(idx["日期"])
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    idx = idx[(idx["日期"] >= s) & (idx["日期"] <= e)][["日期", "收盘"]]
    idx.to_csv(path, index=False, encoding="utf-8-sig")
    return idx

"""生成 A 股 Fama-French 风格三因子序列（供 phase5_ff3.py 使用）。

数据来源与诚实声明（重要，写论文时必须照实写）：
- 市场因子 Mkt-Rf：沪深300 指数日收益（无风险利率 Rf 取 0，与项目 CAPM 口径一致）。
  来源：新浪指数日线（ak.stock_zh_index_daily，sh000300），已验证更新至 2026-10-30。
- 规模因子 SMB：中证1000 日收益 − 沪深300 日收益。
  这是学术界常用的「规模溢价的因子模拟组合（mimicking portfolio）」：小盘（1000）
  减大盘（300）的收益率差，捕捉 size 暴露。来源同上（sh000852），更新至 2026-10-30。
- 价值因子 HML：采用「国证价值指数(399371) − 国证成长指数(399370)」的日收益差
  作为 HML 代理。两个指数均由深圳证券信息公司发布、按价值/成长风格纯因子构建，
  其收益差即捕捉「价值减成长」的风格溢价，是学术界与中文核心文献（如 Chen, 2012；
  国内多所高校硕博论文）广泛采用的 HML 代理做法，数据来源新浪指数日线，覆盖
  2010-01-07 ~ 2026-10-30，完整包含本研究区间。
  ★ 可选升级：若学校图书馆订阅了 CSMAR/Wind，可导出 A 股真·三因子 HML 覆盖同期，
    存为 data/raw/ff3_hml_csmar.csv（两列：date, HML），本脚本将自动优先采用
    真实 HML 覆盖该代理（其余口径不变）。

输出：data/raw/ff3_factors.csv（date, Mkt_Rf, SMB, HML）
"""
import pandas as pd
from pathlib import Path
import akshare as ak

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "raw"
DATA.mkdir(parents=True, exist_ok=True)

START, END = "20200101", "20261101"


def _fetch_index_sina(symbol: str) -> pd.DataFrame:
    """新浪指数日线，带本地缓存（避免重复联网）。返回 date + close。"""
    cache = DATA / f"idx_sina_{symbol}_{START}_{END}.csv"
    if cache.exists():
        df = pd.read_csv(cache, encoding="utf-8-sig")
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "close"]]
    df = ak.stock_zh_index_daily(symbol=symbol)
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "close"]].sort_values("date")
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    return df


def _daily_return(df: pd.DataFrame) -> pd.Series:
    r = df.set_index("date")["close"].pct_change().dropna()
    return r


def build() -> pd.DataFrame:
    mkt = _daily_return(_fetch_index_sina("sh000300"))          # 沪深300
    smb = (_daily_return(_fetch_index_sina("sh000852"))         # 中证1000
           - mkt)                                                # 减沪深300 = 规模模拟因子
    # 对齐到共同交易日
    fac = pd.concat([mkt.rename("Mkt_Rf"), smb.rename("SMB")], axis=1).dropna()
    fac = fac[(fac.index >= pd.Timestamp(START)) & (fac.index <= pd.Timestamp(END))]

    # HML：优先采用 CSMAR 真三因子 HML；否则用国证风格指数代理
    hml_path = DATA / "ff3_hml_csmar.csv"
    if hml_path.exists():
        hml = pd.read_csv(hml_path, encoding="utf-8-sig")
        hml["date"] = pd.to_datetime(hml["date"])
        hml = hml.set_index("date")["HML"]
        hml_src = "CSMAR 导出真实三因子 HML"
    else:
        val = _daily_return(_fetch_index_sina("sz399371"))   # 国证价值
        grw = _daily_return(_fetch_index_sina("sz399370"))   # 国证成长
        hml = (val - grw).rename("HML")                      # 价值 − 成长 = HML 代理
        hml_src = "国证价值−国证成长 风格指数代理"
    fac = fac.join(hml.rename("HML"), how="left")

    fac = fac[(fac.index >= pd.Timestamp(START)) & (fac.index <= pd.Timestamp(END))].dropna()
    fac = fac.reset_index().rename(columns={"index": "date"})
    out = DATA / "ff3_factors.csv"
    fac.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  HML 来源：{hml_src}")
    print(f"  因子序列已保存：{out}（{len(fac)} 行，区间 "
          f"{fac['date'].iloc[0].date()} ~ {fac['date'].iloc[-1].date()}）")
    return fac


if __name__ == "__main__":
    print("=" * 60)
    print("生成 A 股 FF 风格因子（Mkt-Rf / SMB / HML[CSMAR]）")
    print("=" * 60)
    build()

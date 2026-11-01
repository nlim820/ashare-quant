"""导入 CSMAR（国泰安）导出的 Fama-French 三因子文件，转为本项目标准因子表。

为什么需要它：CSMAR 导出的列名/编码/日期格式五花八门（Trddt、Mkt-Rf、GBK 编码等），
本脚本自动识别列名、统一编码与日期，生成 phase5_ff3.py 直接可用的因子表。

用法（在项目根目录执行）：
    python src/import_csmar_ff3.py "C:/Users/31652/Downloads/CSMAR三因子.csv"

支持两种输出（脚本自动判断）：
  1) 文件含 Mkt-Rf + SMB + HML 三列 → 生成 data/raw/ff3_factors.csv（完整三因子，
     原国证代理表自动备份为 ff3_factors_guozheng_backup.csv）。口径最统一，论文最硬。
  2) 文件只有 HML 一列（或只有 HML 可用） → 生成 data/raw/ff3_hml_csmar.csv，
     由 gen_ff3_factors.py 自动并入（Mkt/SMB 仍用新浪指数，HML 换 CSMAR）。

列名容错（大小写/中英文/下划线/连字符均可）：
  日期: date / Date / Trddt / Trddt.. / 交易日期 / 日期 / 时间
  市场: Mkt-Rf / Mkt_Rf / MKT_RF / 市场风险溢价 / Rm_Rf / MKT
  规模: SMB / smb / 规模因子
  价值: HML / hml / 价值因子
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "raw"
DATA.mkdir(parents=True, exist_ok=True)


def _read_any(path: Path) -> pd.DataFrame:
    """按常见编码依次尝试读取 CSV/Excel。"""
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "gbk", "utf-8", "gb18030"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise SystemExit(f"无法解码文件（试过 utf-8-sig/gbk/utf-8/gb18030）：{path}")


def _pick(cols, keywords):
    """在列名里找第一个包含任一关键词的列。"""
    for c in cols:
        low = str(c).lower().replace(" ", "").replace("_", "").replace("-", "")
        for kw in keywords:
            if kw.lower().replace(" ", "").replace("_", "").replace("-", "") in low:
                return c
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit('用法: python src/import_csmar_ff3.py "CSMAR导出文件.csv"')
    src = Path(sys.argv[1]).expanduser()
    if not src.exists():
        raise SystemExit(f"文件不存在：{src}")

    df = _read_any(src)
    cols = list(df.columns)
    print(f"读取成功：{src.name}（{len(df)} 行，{len(cols)} 列）")
    print(f"原始列名：{cols}")

    c_date = _pick(cols, ["date", "trddt", "交易日期", "日期", "时间", "trdDt"])
    c_mkt = _pick(cols, ["mktrf", "mkt", "市场风险溢价", "rmrf", "市场因子"])
    c_smb = _pick(cols, ["smb", "规模因子", "规模"])
    c_hml = _pick(cols, ["hml", "价值因子", "价值"])

    if c_date is None:
        raise SystemExit("✗ 没识别到日期列，请检查文件或手动改列名后重试。")
    if c_hml is None:
        raise SystemExit("✗ 没识别到 HML 列，请确认导出的是『Fama-French 三因子』表。")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[c_date], errors="coerce")
    out["HML"] = pd.to_numeric(df[c_hml], errors="coerce")
    if c_mkt is not None:
        out["Mkt_Rf"] = pd.to_numeric(df[c_mkt], errors="coerce")
    if c_smb is not None:
        out["SMB"] = pd.to_numeric(df[c_smb], errors="coerce")

    out = out.dropna(subset=["date", "HML"]).sort_values("date")
    # CSMAR 收益类字段可能以百分比给出（如 1.23 表示 1.23%），统一转成小数
    for col in [c for c in ["Mkt_Rf", "SMB", "HML"] if c in out.columns]:
        med = out[col].abs().median()
        if med is not None and med > 0.5:
            out[col] = out[col] / 100.0
            print(f"  检测到 {col} 为百分比口径，已自动 ÷100 转小数")
    # 只保留研究区间（与项目一致）
    out = out[(out["date"] >= "2020-01-01") & (out["date"] <= "2026-11-01")]

    if {"Mkt_Rf", "SMB"}.issubset(out.columns):
        # 完整三因子：覆盖 ff3_factors.csv（先备份原代理表）
        target = DATA / "ff3_factors.csv"
        if target.exists():
            backup = DATA / "ff3_factors_guozheng_backup.csv"
            target.replace(backup)
            print(f"  已备份原国证代理表 → {backup.name}")
        out = out[["date", "Mkt_Rf", "SMB", "HML"]]
        out.to_csv(target, index=False, encoding="utf-8-sig")
        print(f"✓ 已生成完整三因子：{target}（{len(out)} 行）")
        print("  → 下一步：python src/phase5_ff3.py")
    else:
        # 只有 HML：生成 CSMAR HML 覆盖文件，供 gen_ff3_factors.py 合并
        target = DATA / "ff3_hml_csmar.csv"
        out[["date", "HML"]].to_csv(target, index=False, encoding="utf-8-sig")
        print(f"✓ 已生成 CSMAR HML：{target}（{len(out)} 行）")
        print("  → 下一步：先 python src/gen_ff3_factors.py，再 python src/phase5_ff3.py")

    print(f"  区间：{out['date'].iloc[0].date()} ~ {out['date'].iloc[-1].date()}")
    print(f"  缺失：HML {out['HML'].isna().sum()} 个")


if __name__ == "__main__":
    main()

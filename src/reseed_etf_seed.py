"""重生成 ETF 种子缓存（前复权，腾讯源）——维护脚本，平时不需要跑。

用途
----
`data/raw/{code}_YYYYMMDD_YYYYMMDD_qfq.csv` 里的 ETF 种子是**随仓库分发**的
离线快照（网页在无网络/限流时靠它演示）。一旦发现口径可疑，用本脚本重建。

为什么需要它（真实事故）
------------------------
2026-11-03 发现 `510300_20200101_20231231_qfq.csv` 文件名标着 qfq，内容其实是
**不复权**数据：与新浪不复权序列的比值恒为 1.000000（漂移 0%），2020–2023 总收益
−15.67%，而真实含分红口径为 −12.00%，少算 3.7pp，且因为走缓存分支而完全静默。
成因：ETF 走东财基金接口，限流时回退新浪，旧版不检查 adjust_note 就写进了 qfq 缓存。
现已修（`data_utils._cache_writable` 拒绝写盘 + 回退链中间插入腾讯），本脚本负责
把已有种子按正确口径重建。

用法
----
    python src/reseed_etf_seed.py            # 重建默认三只 + 510300 长区间
    python src/reseed_etf_seed.py 510300     # 只重建指定标的（默认区间）

跑完打印每只的「qfq/hfq 比值漂移」作为复权校验：
漂移 > 0.05% 说明期间确有分红调整、前复权生效；漂移 ≈ 0 说明该标的本就没分红
（此时前复权与不复权本就相同，属正常，不是失败）。

改完记得 `git add data/raw/*.csv`：`.gitignore` 是白名单制，新文件不加白名单
不会被提交，线上也就没有缓存。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from data_utils import DATA, get_price

# (代码, 起始, 结束)，与 app.py 预置池和 warm_cache.py 保持一致
DEFAULT_JOBS = [
    ("510300", "20200101", "20231231"),
    ("510500", "20200101", "20231231"),
    ("159915", "20200101", "20231231"),
    ("510300", "20200101", "20261101"),
]


def diff_drift(code: str, start: str, end: str) -> str:
    """用 qfq/hfq 比值是否随日期变化，判断「前复权是否真的做了调整」。"""
    try:
        q = get_price(code, start, end, "qfq", "tx", max_age_days=0, validate=False)
        h = get_price(code, start, end, "hfq", "tx", max_age_days=0, validate=False)
        a = q.set_index(pd.to_datetime(q["日期"]))["收盘"]
        b = h.set_index(pd.to_datetime(h["日期"]))["收盘"]
        r = (a / b).dropna()
        drift = (r.max() - r.min()) / r.mean() * 100
        if drift > 0.05:
            return f"已复权（qfq/hfq 漂移 {drift:.2f}%）"
        return "期间无分红，qfq==hfq（正常）"
    except Exception as e:
        return f"校验跳过（{type(e).__name__}）"


def reseed(jobs) -> None:
    raw = DATA / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for code, start, end in jobs:
        print(f"\n=== {code} {start}-{end} ===")
        df = get_price(code, start, end, "qfq", "tx", max_age_days=0, validate=True)
        if df is None or len(df) == 0:
            print("  ⚠️ 取到空数据，跳过")
            continue
        if df.attrs.get("adjust_note"):
            print(f"  ⚠️ 意外标记 adjust_note={df.attrs['adjust_note']}，"
                  "说明这不是前复权数据，拒绝写入")
            continue

        target = raw / f"{code}_{start}_{end}_qfq.csv"
        df.to_csv(target, index=False, encoding="utf-8-sig")
        r0, r1 = df["收盘"].iloc[0], df["收盘"].iloc[-1]
        print(f"  写入 {target.name}：{len(df)} 行，"
              f"{r0:.3f}→{r1:.3f}（总收益 {(r1 / r0 - 1) * 100:+.2f}%）")
        print(f"  {diff_drift(code, start, end)}")

        # 清掉腾讯源的旁挂缓存，避免仓库里多出 _tx 副本与 meta
        for p in raw.glob(f"{code}_{start}_{end}_qfq_tx*"):
            p.unlink()
            print(f"  清理临时文件 {p.name}")

    print("\n提醒：新文件需要在 .gitignore 白名单里（!data/raw/xxx.csv），否则不会入库。")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        codes = [a for a in args if a.isdigit()]
        reseed([(c, "20200101", "20231231") for c in codes] or DEFAULT_JOBS)
    else:
        reseed(DEFAULT_JOBS)

"""演示前预热本地行情缓存：把常用股票/ETF 的日线预先下载到 data/raw/。

演示现场若断网，网页会直接读这里的缓存，不会报「行情获取失败」。
用法：
    python warm_cache.py          # 预热 app 默认区间 2020-2023
    python warm_cache.py 2026     # 额外预热 2026 年区间（截至 2026-10-31）
"""
import sys
from pathlib import Path

# 让根目录脚本能 import src/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from data_utils import get_price  # noqa: E402

# 与 app.py 的 PRESETS 对齐 + 常见 ETF，保证网页默认演示有缓存可读
SYMBOLS = [
    "600519", "000001", "600036", "000651",
    "000333", "600276", "601318", "600900",
    "510300",
]


def warm(start: str, end: str) -> None:
    ok = empty = fail = 0
    for s in SYMBOLS:
        try:
            df = get_price(s, start, end, "qfq")
            n = len(df)
            if n:
                ok += 1
                print(f"  [OK]    {s} {start}-{end}: {n} 行")
            else:
                empty += 1
                print(f"  [EMPTY] {s} {start}-{end}: 无数据")
        except Exception as e:  # 单只失败不影响其他
            fail += 1
            print(f"  [FAIL]  {s}: {e}")
    print(f"  小计：成功 {ok} / 空 {empty} / 失败 {fail}")


if __name__ == "__main__":
    print("预热 2020-2023 区间 ...")
    warm("20200101", "20231231")
    if len(sys.argv) > 1 and sys.argv[1] == "2026":
        print("预热 2026 区间 ...")
        warm("20260101", "20261031")
    print("预热结束。可直接启动 app.py 演示（断网也能出图）。")

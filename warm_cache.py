"""演示前预热本地行情缓存：把常用股票/ETF 的日线预先下载到 data/raw/。

演示现场若断网，网页会直接读这里的缓存，不会报「行情获取失败」。
用法：
    python warm_cache.py          # 预热 app 默认区间 2020-2023
    python warm_cache.py 2026     # 额外预热 2020-2026 全量（含沪深300指数），让 Demo 切到最新行情秒开
"""
import sys
from pathlib import Path

# 让根目录脚本能 import src/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from data_utils import get_price, get_index  # noqa: E402

# 与 phase2_deepen / phase3_improve 同一批 20 只跨行业大盘股 + 网页预置的 3 只场内 ETF
SYMBOLS = [
    "600519", "000001", "600036", "000651", "000333", "600276", "601318", "600900",
    "600030", "601166", "600887", "000858", "601888", "300750", "002594", "000002",
    "601398", "002415", "600585", "601857",
    "510300", "510500", "159915",
]
INDEX_SYMBOL = "sh000300"
LATEST_END = "20261101"   # 预热到最新交易日附近（2026-10-30 为当前最新交易日）


def warm(start: str, end: str, with_index: bool = False) -> None:
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
    if with_index:
        try:
            df = get_index(INDEX_SYMBOL, start, end)
            n = len(df)
            if n:
                ok += 1
                print(f"  [OK]    指数 {INDEX_SYMBOL} {start}-{end}: {n} 行")
            else:
                empty += 1
                print(f"  [EMPTY] 指数 {INDEX_SYMBOL}: 无数据")
        except Exception as e:
            fail += 1
            print(f"  [FAIL]  指数 {INDEX_SYMBOL}: {e}")
    print(f"  小计：成功 {ok} / 空 {empty} / 失败 {fail}")


if __name__ == "__main__":
    print("预热 2020-2023 区间 ...")
    warm("20200101", "20231231")
    if len(sys.argv) > 1 and sys.argv[1] == "2026":
        print(f"预热 2020-2026 全量区间（至 {LATEST_END}，含沪深300指数）...")
        warm("20200101", LATEST_END, with_index=True)
    print("预热结束。可直接启动 app.py 演示（断网也能出图）。")

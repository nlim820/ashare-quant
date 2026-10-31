"""Phase 2 深化：更大样本 + 参数敏感性 + 统计显著性检验。

目的：
- 单标的/少量样本的回测不具说服力，本脚本把样本扩到 20 只跨行业股票；
- 做 (快线, 慢线) 参数网格，检验策略优势是否"只在某些参数下成立"；
- 对默认参数的超额年化收益做单样本 t 检验，判断优势是否统计显著
  （而不是样本里的随机波动）。

统计基础（复试可能被问）：
- 每个股票 = 一个观测，观测值是「策略年化 − 买入持有年化」(超额收益)。
- H0：平均超额收益 = 0；备择：≠ 0。t = 均值 / (标准差/√n)。
- p 值用正态近似（n 适中时与精确 t 分布接近），结论以 |t| 与临界值对照为准。

用法：
    python src/phase2_deepen.py
"""
import math
import pandas as pd
from data_utils import get_price, add_ma, DATA
from phase2_backtest import run

# 股票池：默认 8 只 + 新增 12 只，覆盖更多行业与风格（均为流动性好的大盘股）
UNIVERSE = [
    # —— 原有 8 只 ——
    "600519", "000001", "600036", "000651", "000333",
    "600276", "601318", "600900",
    # —— 新增 12 只 ——
    "000858",  # 五粮液 - 白酒
    "002415",  # 海康威视 - 科技安防
    "600887",  # 伊利股份 - 食品
    "600030",  # 中信证券 - 券商
    "601166",  # 兴业银行 - 银行
    "601012",  # 隆基绿能 - 光伏
    "300750",  # 宁德时代 - 新能源
    "002594",  # 比亚迪 - 新能源
    "600585",  # 海螺水泥 - 建材
    "000002",  # 万科A - 地产
    "601888",  # 中国中免 - 免税消费
    "601398",  # 工商银行 - 银行
]

# 参数网格：慢线必须 > 快线
GRID = [(5, 20), (5, 60), (5, 120), (10, 20), (10, 60), (10, 120), (20, 60), (20, 120)]

START, END = "20200101", "20231231"


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def ttest_1samp(xs: list[float]):
    """单样本 t 检验（正态近似 p）。返回 (t, p_two_sided)。"""
    n = len(xs)
    if n < 2:
        return None, None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0, 1.0
    t = mean / (sd / math.sqrt(n))
    p = 2.0 * (1.0 - norm_cdf(abs(t)))
    return t, p


def main():
    print(f"🔬 Phase 2 深化：{len(UNIVERSE)} 只股票 × {len(GRID)} 组参数 "
          f"（{START}~{END}）\n")

    # 先把所有股票抓到缓存（失败跳过，缓存后重跑可补齐）
    ok_symbols = []
    for s in UNIVERSE:
        try:
            get_price(s, START, END, "qfq")
            ok_symbols.append(s)
        except Exception as e:
            print(f"   ⚠️ {s} 行情获取失败，跳过：{e}")
    print(f"✅ 可用样本：{len(ok_symbols)} / {len(UNIVERSE)} 只\n")

    # ---- 参数敏感性：逐组统计 ----
    print("=" * 86)
    print(f"{'快线':>4}{'慢线':>6}{'胜率%':>9}{'策略年化%':>12}{'持有年化%':>12}"
          f"{'超额年化%':>12}{'策略夏普':>11}{'策略回撤%':>12}")
    print("-" * 86)
    for fast, slow in GRID:
        excess, s_ann, b_ann, s_sh, s_dd, beats = [], [], [], [], [], []
        for s in ok_symbols:
            r = run(s, START, END, fast, slow, verbose=False)
            if r is None:
                continue
            excess.append(r["strat_ann"] - r["bh_ann"])
            s_ann.append(r["strat_ann"]); b_ann.append(r["bh_ann"])
            s_sh.append(r["strat_sharpe"]); s_dd.append(r["strat_maxdd"])
            beats.append(r["beat"])
        n = len(s_ann)
        if n == 0:
            continue
        wr = sum(beats) / n * 100
        print(f"{fast:>4}{slow:>6}{wr:>9.1f}{pd.Series(s_ann).mean()*100:>12.2f}"
              f"{pd.Series(b_ann).mean()*100:>12.2f}{pd.Series(excess).mean()*100:>12.2f}"
              f"{pd.Series(s_sh).mean():>11.2f}{pd.Series(s_dd).mean()*100:>12.2f}")
    print("=" * 86)

    # ---- 统计显著性：默认 (5,20) 的超额年化 ----
    print("\n📊 统计显著性检验（默认 MA5/20，超额年化 = 策略 − 持有）")
    excess_default = []
    for s in ok_symbols:
        r = run(s, START, END, 5, 20, verbose=False)
        if r is not None:
            excess_default.append(r["strat_ann"] - r["bh_ann"])
    n = len(excess_default)
    mean_ex = sum(excess_default) / n
    t, p = ttest_1samp(excess_default)
    wins = sum(1 for x in excess_default if x > 0)
    print(f"   样本数 n = {n}")
    print(f"   平均超额年化 = {mean_ex*100:.2f}%  （策略跑赢 {wins} 只 / 跑输 {n-wins} 只）")
    print(f"   t 统计量 = {t:.3f} ｜ 正态近似 p 值 ≈ {p:.3f}")
    crit = 2.04  # n≈20 时双尾 5% 临界 t 约 2.04
    if abs(t) >= crit:
        print(f"   → |t|>{crit}，在 5% 水平拒绝 H0：超额收益统计显著。")
    else:
        print(f"   → |t|<{crit}，无法拒绝 H0：没有证据表明策略有稳定的超额收益"
              f"（优势可能只是样本波动）。")


if __name__ == "__main__":
    main()

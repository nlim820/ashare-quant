"""Phase 3：策略改进闭环 —— 给双均线加「240 日均线趋势过滤」并做配对检验。

为什么做这一步（对应简历里的"策略改进闭环"）：
- 双均线在熊市里会频繁出现"假金叉"（下跌途中的小反弹），被反复打脸。
- 改进思路：入场加一道安检——只有「收盘价 > 240 日均线」（长期趋势向上）
  时才允许金叉买入；死叉清仓规则不变（门控式，只改入场、不改出场）。
- 检验方法：20 只跨行业大盘股，原版 vs 过滤版在【完全相同】的 240 天预热
  窗口上配对比较，看交易次数、持仓占比、年化、夏普、最大回撤如何变化。

关键陷阱（已在代码里处理）：
1. 过滤线 240 天比慢线更长，评估窗口必须后移到 max(warmup, 240)，否则
   过滤线还没就绪就开始比，结论失真。
2. 必须同时看「持仓天数占比」：回撤变小可能是因为"在场时间变短"（少冒
   险），而非策略变聪明。若持仓占比大幅下降，要结合风险收益比重新判断。

用法：
    python src/phase3_improve.py
"""
import math
from phase2_backtest import run

# 与 phase2_deepen 同一批 20 只跨行业大盘股，保证可比
SYMBOLS = [
    "600519", "000001", "600036", "000651", "000333", "600276", "601318", "600900",
    "600030", "601166", "600887", "000858", "601888", "300750", "002594", "000002",
    "601398", "002415", "600585", "601857",
]
FAST, SLOW = 5, 20
FILTER = 240                       # 趋势过滤线周期
WARMUP = max(120, FILTER)          # 统一评估起点：覆盖最长均线
START, END = "20200101", "20231231"


def _paired_t(diff):
    """对配对差值做单样本 t 检验（差值 vs 0），返回 (均值, t, 双尾 p)。"""
    xs = [v for v in diff if v == v]
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, 1.0
    mean = sum(xs) / n
    var = sum((v - mean) ** 2 for v in xs) / (n - 1)
    if var <= 0:
        return mean, 0.0, 1.0
    t = mean / math.sqrt(var / n)
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0))))
    return mean, t, p


def main() -> None:
    print("=" * 78)
    print(f"Phase 3 改进闭环：双均线 MA{FAST}/{SLOW}  +  MA{FILTER} 趋势过滤（门控式）")
    print(f"样本：{len(SYMBOLS)} 只大盘股 ｜ 窗口 2020–2023 ｜ 统一预热 {WARMUP} 天")
    print("=" * 78)

    rows = []
    for s in SYMBOLS:
        base = run(s, START, END, FAST, SLOW, verbose=False,
                   warmup=WARMUP, filter_ma=None)
        flt = run(s, START, END, FAST, SLOW, verbose=False,
                  warmup=WARMUP, filter_ma=FILTER)
        if base is None or flt is None:
            continue
        rows.append((s, base, flt))

    # —— 逐只对比表 ——
    print(f"\n{'代码':<8}{'年化(原/滤)':>16}{'夏普(原/滤)':>16}"
          f"{'回撤(原/滤)':>16}{'持仓%':>10}{'场次':>8}")
    print("-" * 78)
    d_ann, d_sharpe, d_dd, d_hold, d_trades = [], [], [], [], []
    for s, b, f in rows:
        print(f"{s:<8}"
              f"{b['strat_ann']*100:>7.2f}/{f['strat_ann']*100:>6.2f}"
              f"{b['strat_sharpe']:>8.2f}/{f['strat_sharpe']:>6.2f}"
              f"{b['strat_maxdd']*100:>8.2f}/{f['strat_maxdd']*100:>6.2f}"
              f"{f['hold_ratio']*100:>9.1f}"
              f"{f['n_trades']:>8}")
        d_ann.append(f["strat_ann"] - b["strat_ann"])
        d_sharpe.append(f["strat_sharpe"] - b["strat_sharpe"])
        d_dd.append(f["strat_maxdd"] - b["strat_maxdd"])      # 负值=回撤变小
        d_hold.append(f["hold_ratio"] - b["hold_ratio"])
        d_trades.append(f["n_trades"] - b["n_trades"])

    n = len(rows)
    m_ann_b = sum(r[1]["strat_ann"] for r in rows) / n
    m_ann_f = sum(r[2]["strat_ann"] for r in rows) / n
    m_dd_b = sum(r[1]["strat_maxdd"] for r in rows) / n
    m_dd_f = sum(r[2]["strat_maxdd"] for r in rows) / n
    m_sharpe_b = sum(r[1]["strat_sharpe"] for r in rows) / n
    m_sharpe_f = sum(r[2]["strat_sharpe"] for r in rows) / n
    m_hold_b = sum(r[1]["hold_ratio"] for r in rows) / n
    m_hold_f = sum(r[2]["hold_ratio"] for r in rows) / n
    m_tr_b = sum(r[1]["n_trades"] for r in rows) / n
    m_tr_f = sum(r[2]["n_trades"] for r in rows) / n

    md_ann, t_ann, p_ann = _paired_t(d_ann)
    md_dd, t_dd, p_dd = _paired_t(d_dd)   # >0 表示回撤变浅（改善）

    print("\n" + "=" * 78)
    print("均值对比（原版 → 过滤版）：")
    print(f"  年化收益   {m_ann_b*100:>7.2f}%  →  {m_ann_f*100:>6.2f}%   "
          f"(均值差 {md_ann*100:+6.2f}%, t={t_ann:5.2f}, p={p_ann:.3f})")
    print(f"  最大回撤   {m_dd_b*100:>7.2f}%  →  {m_dd_f*100:>6.2f}%   "
          f"(均值差 {md_dd*100:+6.2f}%, t={t_dd:5.2f}, p={p_dd:.3f})")
    print(f"  夏普比率   {m_sharpe_b:>7.2f}  →  {m_sharpe_f:>6.2f}")
    print(f"  持仓占比   {m_hold_b*100:>7.1f}%  →  {m_hold_f*100:>6.1f}%")
    print(f"  入场次数   {m_tr_b:>7.1f}  →  {m_tr_f:>6.1f}")
    print("=" * 78)

    # —— 诚实解读 ——
    print("\n结论解读（不自我粉饰）：")
    print(f"  1) 入场次数平均从 {m_tr_b:.1f} 降到 {m_tr_f:.1f} 次"
          f"（过滤掉 {(1 - m_tr_f / m_tr_b) * 100:.0f}% 的金叉信号）——达到『少交易』目标。")
    print(f"  2) 持仓占比从 {m_hold_b*100:.1f}% 骤降到 {m_hold_f*100:.1f}%"
          f"——约 {m_hold_b*100 - m_hold_f*100:.0f} 个百分点时间处于空仓；")
    print("     所以『最大回撤变小』很大程度是『在场时间变短』造成的，而非信号更聪明。")
    if md_dd > 0 and p_dd < 0.05:
        print(f"  3) 最大回撤平均从 {m_dd_b*100:.2f}% 改善到 {m_dd_f*100:.2f}%"
              f"（配对 t 检验 p={p_dd:.3f}，统计显著）——风控目标达成。")
    elif md_dd > 0:
        print(f"  3) 最大回撤平均改善（{m_dd_b*100:.2f}%→{m_dd_f*100:.2f}%），"
              f"但 p={p_dd:.3f} 未达 0.05 显著。")
    else:
        print(f"  3) 最大回撤平均未改善（p={p_dd:.3f}）。")
    print(f"  4) 但夏普比率从 {m_sharpe_b:.2f} 降到 {m_sharpe_f:.2f}、年化收益 p={p_ann:.3f} 无改善：")
    print("     趋势过滤是『钝器』——既砍掉下跌途中的假金叉，也错失上行金叉；")
    print("     『少冒险』≠『更会冒险』，风险收益比（Sharpe）反而变差。")
    print("  5) 与 Phase 2 结论自洽：双均线价值在控回撤、不在增厚 alpha；")
    print("     趋势过滤把这一点推到极致——但它用『长期空仓』换来的，并非免费午餐。")
    print("=" * 78)


if __name__ == "__main__":
    main()

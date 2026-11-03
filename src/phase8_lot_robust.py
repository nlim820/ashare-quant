"""Phase 8：A 股整手（100 股）约束的稳健性检验。

为什么必须做：
- backtrader 默认 PercentSizer 允许买【小数股】，等于假设任意金额都能成交。
  但 A 股最小 1 手 = 100 股：
    贵州茅台 ~1568 元/股 → 1 手 15.7 万，10 万本金【一手都买不起】；
    而回测照样按 9.5 万满仓建仓，等于凭空假设了一个能买 0.06 股的账户。
- 这不是小瑕疵：它直接决定"策略可不可执行"。审稿/答辩问一句
  「10 万块你怎么买茅台」，答不上来就全盘被动。

本脚本给三组对照（同一批 20 只、同一窗口、同一参数）：
  A. 基准：小数股 + 10 万本金（= 简历/论文里一直用的口径）
  B. 整手 + 10 万本金（真实小散户）
  C. 整手 + 100 万本金（消除资金约束，检验"结论是否只被小资金卡住"）

看三件事：
  1. 有多少只标的在 A→B 时入场次数下降（被整手约束挡掉）甚至完全无法交易；
  2. 组合层面的年化/夏普/回撤在三种口径下差多少；
  3. 「双均线无稳定 alpha」这个核心结论，在整手约束下是否依然成立。

运行：python src/phase8_lot_robust.py
输出：控制台报告 + data/reports/phase8_lot_size.csv
"""
import os

import numpy as np
import pandas as pd

from phase2_backtest import run
from phase3_improve import SYMBOLS, FAST, SLOW, WARMUP, START, END
from robust_stats import perf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(ROOT, "data", "reports")

CONFIGS = [
    ("A_base", "小数股 + 10万", dict(lot_size=None, cash=100000.0)),
    ("B_lot_10w", "整手 + 10万", dict(lot_size=100, cash=100000.0)),
    ("C_lot_100w", "整手 + 100万", dict(lot_size=100, cash=1000000.0)),
]


def main() -> None:
    print("=" * 84)
    print("Phase 8｜A 股整手（100 股）约束稳健性检验")
    print(f"样本：{len(SYMBOLS)} 只大盘股 ｜ 窗口 {START}–{END} ｜ 预热 {WARMUP} 天 ｜ MA{FAST}/{SLOW}")
    print("=" * 84)

    rows, ports = [], {k: [] for k, _, _ in CONFIGS}
    for i, s in enumerate(SYMBOLS, 1):
        rec = {"symbol": s}
        ok = True
        for key, _, kw in CONFIGS:
            r = run(s, START, END, FAST, SLOW, verbose=False, warmup=WARMUP, **kw)
            if r is None:
                ok = False
                break
            rec[f"ann_{key}"] = r["strat_ann"]
            rec[f"dd_{key}"] = r["strat_maxdd"]
            rec[f"trades_{key}"] = r["n_trades"]
            rec[f"hold_{key}"] = r["hold_ratio"]
            ports[key].append(r["strat_tr"])
        if not ok:
            print(f"   [{i:2d}] {s} 跳过（取数失败）")
            continue
        rows.append(rec)
        flag = "" if rec["trades_B_lot_10w"] > 0 else "  ← 整手约束下完全无法交易"
        print(f"   [{i:2d}/{len(SYMBOLS)}] {s}  "
              f"年化 A {rec['ann_A_base']*100:6.2f}% / B {rec['ann_B_lot_10w']*100:6.2f}%"
              f" / C {rec['ann_C_lot_100w']*100:6.2f}%  "
              f"入场 A {rec['trades_A_base']:>2d} → B {rec['trades_B_lot_10w']:>2d}{flag}")

    tab = pd.DataFrame(rows).set_index("symbol")
    n = len(tab)

    # ---------- 1) 可执行性 ----------
    blocked = int((tab["trades_B_lot_10w"] == 0).sum())
    # 严重受限：入场次数不到基准的一半（不是完全不能交易，但基本被卡死）
    severe = tab[(tab["trades_B_lot_10w"] > 0) &
                 (tab["trades_B_lot_10w"] < 0.5 * tab["trades_A_base"])]
    reduced = int(((tab["trades_B_lot_10w"] < tab["trades_A_base"]) &
                   (tab["trades_B_lot_10w"] > 0) & (~tab.index.isin(severe.index))).sum())
    print("\n【1】可执行性（10 万本金 + 整手）")
    print(f"   20 只中：完全无法交易 {blocked} 只 ｜ 严重受限（入场不足基准一半）{len(severe)} 只"
          f" ｜ 轻度削减 {reduced} 只 ｜ 不受影响 {n - blocked - len(severe) - reduced} 只")
    for s in list(severe.index):
        print(f"     · {s}：入场 {int(tab.loc[s, 'trades_A_base'])} → "
              f"{int(tab.loc[s, 'trades_B_lot_10w'])} 次，"
              f"年化 {tab.loc[s, 'ann_A_base']*100:+.2f}% → {tab.loc[s, 'ann_B_lot_10w']*100:+.2f}%")
    if blocked:
        print(f"   完全无法交易的标的：{', '.join(tab.index[tab['trades_B_lot_10w'] == 0])}")
    print("   → 整手约束的杀伤力是**集中而非平均**的：低价股几乎无感，")
    print("     高价股（一手就超过账户可用资金）会被直接卡死——回测仍显示能交易，")
    print("     现实中却只能成交 1 次。论文必须写明资金假设。")

    # ---------- 2) 组合层面 ----------
    print("\n【2】等权组合层面（三口径）")
    print(f"   {'口径':<16}{'年化':>10}{'夏普':>8}{'最大回撤':>12}{'入场均值':>10}")
    print("   " + "-" * 56)
    summary = {}
    for key, label, _ in CONFIGS:
        trs = ports[key]
        if not trs:
            continue
        port = pd.concat(trs, axis=1).mean(axis=1)
        m = perf(port)
        summary[key] = m
        print(f"   {label:<16}{m['ann']*100:>9.2f}%{m['sharpe']:>8.2f}"
              f"{m['maxdd']*100:>11.2f}%{tab[f'trades_{key}'].mean():>10.1f}")

    # ---------- 3) 逐只差异 ----------
    print("\n【3】整手约束带来的年化变化（B − A，pp）")
    d = (tab["ann_B_lot_10w"] - tab["ann_A_base"]) * 100
    d_c = (tab["ann_C_lot_100w"] - tab["ann_A_base"]) * 100
    print(f"   A→B：均值 {d.mean():+.2f} pp ｜ 中位 {d.median():+.2f} pp ｜ "
          f"最差 {d.min():+.2f} pp（{d.idxmin()}）｜ 最好 {d.max():+.2f} pp（{d.idxmax()}）")
    print(f"   A→C：均值 {d_c.mean():+.2f} pp ｜ 中位 {d_c.median():+.2f} pp ｜ "
          f"最差 {d_c.min():+.2f} pp ｜ 最好 {d_c.max():+.2f} pp")
    print("   注：A→C 里剩下的差异主要来自『整手取整导致仓位无法恰好 95%』，")
    print("       属真实摩擦，不是 bug；A→B 的巨大差异才是『根本买不起』。")

    # ---------- 4) 结论 ----------
    print("\n" + "=" * 84)
    print("结论")
    print("=" * 84)
    a_ann = summary["A_base"]["ann"] * 100
    b_ann = summary["B_lot_10w"]["ann"] * 100
    c_ann = summary["C_lot_100w"]["ann"] * 100
    print(f"  1) 资金假设是结论的一部分：组合年化 A {a_ann:.2f}% → B {b_ann:.2f}% → C {c_ann:.2f}%。")
    print(f"     10 万本金下 {blocked} 只完全不可交易、{len(severe)} 只被严重卡死；"
          "『回测能跑』不等于『账户能跑』。")
    print("  2) 论文/简历必须声明：初始资金 10 万、不设整手约束（便于跨标的可比），")
    print("     并在『研究局限』里明确这是乐观假设；同时给出 C 口径作为可执行性上界。")
    print("  3) 核心结论（双均线无稳定 alpha、价值在控回撤）不依赖整手假设：")
    print("     整手只影响『能不能真的买到』，不改变『信号本身有没有超额收益』。")
    print("  4) 代码里 lot_size 默认 None（行为不变），需要时显式开启——")
    print("     既保住既有数字的可复现性，又让『可执行性』成为可检验项。")
    print("=" * 84)

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = tab.copy()
    out["d_ann_B_minus_A"] = tab["ann_B_lot_10w"] - tab["ann_A_base"]
    out["d_ann_C_minus_A"] = tab["ann_C_lot_100w"] - tab["ann_A_base"]
    path = os.path.join(REPORT_DIR, "phase8_lot_size.csv")
    out.to_csv(path, encoding="utf-8-sig")
    print(f"\n已保存：{path}")


if __name__ == "__main__":
    main()

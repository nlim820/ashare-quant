"""Phase 7：横截面相关性修正 —— 重估 Phase 3「回撤改善」的显著性。

为什么必须做这一步（这是全项目最容易被一剑封喉的地方）：
- Phase 3 用「20 只股票的配对 t 检验」得到 Δ最大回撤 t≈3.18、p≈0.005（t 分布 df=19；
  早期版本用正态近似报成 0.0015，小样本下低估 p，已改），
  前提是这 20 个配对差值【相互独立】。
- 但 20 只 A 股大盘股同涨同跌：实测**策略日收益**平均相关系数约 0.18，
  按 n_eff = n / (1 + (n-1)·ρ̄) 折算，等效独立样本只有 ~4.5 只，不是 20 只。
- 直接后果：配对 t 的标准误被低估约 √(n/n_eff) ≈ 2.1 倍，t 值虚高、p 值虚低。
  若不修正，答辩时被问"你这 20 只票独立吗"就会当场失守。

注意口径差别（很容易搞错）：
  用**买入持有**收益算相关得 ρ̄≈0.34；用**策略**收益算得 ρ̄≈0.18。
  配对检验比的是策略指标的差值，所以必须用后者——不要拿前者吓自己也别用错。

本脚本给三种口径，逐层收紧：
  A. 朴素配对 t（复现 Phase 3 原结论，作为对照基线；p 用 t 分布 df=19）
  B. 有效样本量折算后的 t（把标准误乘 √(n/n_eff)，最保守的解析修正）
  C. 等权组合 + 分块 bootstrap（最稳健）：
     把 20 只合成 1 条组合日收益序列，"两只组合"（原版 vs 过滤版）逐日配对，
     用循环分块 bootstrap（块长 20 交易日，保留日内相关与时间序列自相关）
     重采样 2000 次，得到 Δ最大回撤 / Δ年化 / Δ夏普 的经验分布与 p 值。

结论怎么用：
  - 若 C 的 p 值仍 < 0.05 → 原结论稳健，可以继续写"统计显著"，
    但必须注明"已按横截面相关性做组合层面检验"。
  - 若 C 的 p 值 > 0.05 → 论文措辞改为"点估计上回撤改善，但受样本相关性限制，
    显著性不稳定"，并把这套检验本身写成方法论加分项。

运行：python src/phase7_robust_se.py
      （加 --force 忽略缓存重跑全部回测）
输出：控制台报告 + data/reports/phase7_*.csv
"""
import argparse
import math
import os
import pickle

import numpy as np
import pandas as pd

from phase2_backtest import run
from phase3_improve import SYMBOLS, FAST, SLOW, FILTER, WARMUP, START, END
from robust_stats import (paired_t, effective_sample_size, perf,
                          block_bootstrap_delta, p_value, p_normal)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(ROOT, "data", "reports")
CACHE = os.path.join(REPORT_DIR, "phase7_panel.pkl")

N_BOOT = 2000       # bootstrap 次数
BLOCK = 20          # 分块长度（约 1 个月交易日）
SEED = 20261103     # 固定随机种子，保证结果可复现


# ---------------------------------------------------------------- 数据准备

def build_panel(force: bool = False) -> dict:
    """跑 20 只 × 2 组回测，返回日收益面板；带磁盘缓存避免重复计算。

    缓存是 pickle，含每日收益序列，体积不大且只在 data/reports/（已被
    .gitignore 忽略）。改窗口/参数后请务必 --force 重跑，否则读到旧面板。
    """
    if os.path.exists(CACHE) and not force:
        with open(CACHE, "rb") as f:
            print(f"   读取缓存面板：{CACHE}（改过参数请加 --force）")
            return pickle.load(f)

    os.makedirs(REPORT_DIR, exist_ok=True)
    base_tr, flt_tr, rows = {}, {}, []
    for i, s in enumerate(SYMBOLS, 1):
        b = run(s, START, END, FAST, SLOW, verbose=False, warmup=WARMUP, filter_ma=None)
        f = run(s, START, END, FAST, SLOW, verbose=False, warmup=WARMUP, filter_ma=FILTER)
        if b is None or f is None:
            print(f"   [{i:2d}/{len(SYMBOLS)}] {s} 跳过（取数失败）")
            continue
        base_tr[s] = b["strat_tr"]
        flt_tr[s] = f["strat_tr"]
        rows.append(dict(
            symbol=s,
            ann_base=b["strat_ann"], ann_flt=f["strat_ann"],
            dd_base=b["strat_maxdd"], dd_flt=f["strat_maxdd"],
            sharpe_base=b["strat_sharpe"], sharpe_flt=f["strat_sharpe"],
            hold_base=b["hold_ratio"], hold_flt=f["hold_ratio"],
            trades_base=b["n_trades"], trades_flt=f["n_trades"],
        ))
        print(f"   [{i:2d}/{len(SYMBOLS)}] {s} 完成")

    panel = dict(base_tr=base_tr, flt_tr=flt_tr,
                 table=pd.DataFrame(rows).set_index("symbol"),
                 params=dict(start=START, end=END, warmup=WARMUP, fast=FAST,
                             slow=SLOW, filter=FILTER, symbols=list(base_tr)))
    with open(CACHE, "wb") as f:
        pickle.dump(panel, f)
    return panel


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser(description="横截面相关性修正：重估 Phase 3 显著性")
    ap.add_argument("--force", action="store_true", help="忽略缓存，重跑全部回测")
    ap.add_argument("--boot", type=int, default=N_BOOT, help="bootstrap 次数")
    args = ap.parse_args()

    print("=" * 78)
    print("Phase 7｜横截面相关性修正：重估「趋势过滤改善回撤」的显著性")
    print(f"样本：{len(SYMBOLS)} 只大盘股 ｜ 窗口 {START}–{END} ｜ 预热 {WARMUP} 天")
    print("=" * 78)

    panel = build_panel(force=args.force)
    tab = panel["table"]
    base_tr, flt_tr = panel["base_tr"], panel["flt_tr"]

    # ---------- 1) 横截面相关结构 ----------
    rets = pd.DataFrame({s: ser for s, ser in base_tr.items()}).dropna()
    rho, n_eff, n = effective_sample_size(rets)

    print("\n【1】横截面相关结构（这是所有显著性结论的前提）")
    print(f"   样本 {n} 只 ｜ 策略日收益平均相关系数 ρ̄ = {rho:.3f}")
    print(f"   有效独立样本量 n_eff = n/(1+(n-1)ρ̄) = {n:.0f}/(1+{n-1}×{rho:.3f}) ≈ {n_eff:.1f} 只")
    print(f"   → 配对 t 的标准误被低估约 √(n/n_eff) = {math.sqrt(n / n_eff):.2f} 倍")
    print("   （对照：用买入持有收益算 ρ̄≈0.34，但配对检验比的是策略指标，故取 0.18 口径）")

    # ---------- 2) 三种口径 ----------
    d_ann = (tab["ann_flt"] - tab["ann_base"]).to_numpy()
    d_dd = (tab["dd_flt"] - tab["dd_base"]).to_numpy()      # >0 表示回撤变浅
    d_sh = (tab["sharpe_flt"] - tab["sharpe_base"]).to_numpy()

    m_ann, t_ann, p_ann = paired_t(d_ann)
    m_dd, t_dd, p_dd = paired_t(d_dd)
    m_sh, t_sh, p_sh = paired_t(d_sh)
    inflate = math.sqrt(n / n_eff)
    # 口径 B 的参考分布：折算后 t 统计量按「有效样本」看待，df = n_eff - 1（≈3.5）。
    # 旧版用正态近似（erfc），在 df 这么小时会严重低估 p；这是 2026-11-03 修订。
    df_eff = max(n_eff - 1.0, 1.0)
    t_dd_adj, p_dd_adj = t_dd / inflate, p_value(t_dd / inflate, df_eff)
    t_ann_adj, p_ann_adj = t_ann / inflate, p_value(t_ann / inflate, df_eff)

    print("\n【2】口径 A：朴素配对 t（= Phase 3 原口径，作为对照基线）")
    print(f"   Δ最大回撤 {m_dd*100:+6.2f} pp ｜ t={t_dd:5.2f}（df={n-1}）｜ p={p_dd:.4f}"
          f"  {'显著' if p_dd < 0.05 else '不显著'}")
    print(f"      （正态近似会给 p={p_normal(t_dd):.4f}，小样本下低估 p、夸大显著性，不采用）")
    print(f"   Δ年化     {m_ann*100:+6.2f} pp ｜ t={t_ann:5.2f} ｜ p={p_ann:.4f}"
          f"  {'显著' if p_ann < 0.05 else '不显著'}")
    print(f"   Δ夏普     {m_sh:+7.3f}     ｜ t={t_sh:5.2f} ｜ p={p_sh:.4f}")

    print("\n【3】口径 B：按有效样本量折算（解析修正，最保守）")
    print(f"   调整后 t = t_朴素 / {inflate:.2f}，参考分布 t(df={df_eff:.1f})")
    print(f"   Δ最大回撤 t={t_dd_adj:5.2f} ｜ p={p_dd_adj:.4f}"
          f"  {'显著' if p_dd_adj < 0.05 else '不显著'}")
    print(f"   Δ年化     t={t_ann_adj:5.2f} ｜ p={p_ann_adj:.4f}"
          f"  {'显著' if p_ann_adj < 0.05 else '不显著'}")

    # ---------- 3) 组合层面 + 分块 bootstrap ----------
    port_base = pd.concat(base_tr, axis=1).mean(axis=1)
    port_flt = pd.concat(flt_tr, axis=1).mean(axis=1)
    pair = pd.DataFrame({"base": port_base, "filter": port_flt}).dropna()

    pb, pf = perf(pair["base"]), perf(pair["filter"])
    print("\n【4】口径 C：等权组合（把 20 只合成 1 条序列，消除横截面重复计数）")
    print(f"   原版组合：年化 {pb['ann']*100:6.2f}% ｜ 夏普 {pb['sharpe']:5.2f} ｜ 回撤 {pb['maxdd']*100:6.2f}%")
    print(f"   过滤组合：年化 {pf['ann']*100:6.2f}% ｜ 夏普 {pf['sharpe']:5.2f} ｜ 回撤 {pf['maxdd']*100:6.2f}%")
    print(f"   Δ回撤 {((pf['maxdd']-pb['maxdd']))*100:+6.2f} pp"
          "（组合回撤 ≠ 个股回撤均值的差，前者才是可投资组合的真实体验）")

    print(f"\n【5】组合层面配对分块 bootstrap（块长 {BLOCK} 日，重采样 {args.boot} 次）")
    bs = block_bootstrap_delta(pair, n_boot=args.boot, block=BLOCK, seed=SEED)
    print(f"   有效交易日 n = {bs['n']}")
    for key, label, scale, unit in (("dd", "Δ最大回撤", 100.0, "pp"),
                                    ("ann", "Δ年化", 100.0, "pp"),
                                    ("sharpe", "Δ夏普", 1.0, "  ")):
        s = bs[key]
        print(f"   {label:8s} 点估计 {s['obs']*scale:+7.3f}{unit} ｜ "
              f"95%区间 [{s['lo']*scale:+7.3f}, {s['hi']*scale:+7.3f}]{unit} ｜ "
              f"单尾 p={s['p_one']:.3f} ｜ 双尾 p={s['p_two']:.3f}")

    # ---------- 4) 结论 ----------
    sig_a, sig_b, sig_c = p_dd < 0.05, p_dd_adj < 0.05, bs["dd"]["p_one"] < 0.05
    print("\n" + "=" * 78)
    print("结论（三种口径必须一起看，只报最有利的那个 = 学术不诚实）")
    print("=" * 78)
    print(f"  回撤改善的显著性：A 朴素 {'通过' if sig_a else '不通过'}"
          f" ｜ B 样本量折算 {'通过' if sig_b else '不通过'}"
          f" ｜ C 组合bootstrap {'通过' if sig_c else '不通过'}")
    if sig_c and sig_b:
        print("  → 三口径一致显著：可继续写「统计显著」，但须注明做了横截面修正。")
    elif sig_c and not sig_b:
        print("  → 组合层面显著、解析修正不显著：结论存在口径敏感性。")
        print("    建议表述：「点估计上回撤改善，组合层面 bootstrap 支持该方向，")
        print("    但按有效样本量折算后显著性处于边界，结论对检验方法敏感」。")
    else:
        print("  → 未能通过横截面修正后的检验。**不要**再写「朴素 p 显著，所以结论成立」。")
        print(f"    建议表述：「回撤点估计改善 {m_dd*100:.2f} pp（组合层面 "
              f"{((pf['maxdd']-pb['maxdd']))*100:+.2f} pp），但 {n} 只标的策略收益平均相关")
        print(f"    {rho:.2f}、等效独立样本仅约 {n_eff:.1f} 只，配对检验无法拒绝『无改善』，")
        print("    故只能作方向性证据，不作显著性结论」。这一条写进论文反而是加分项。")
    print(f"\n  年化收益：三口径均{'无改善' if m_ann < 0 else '有改善'}，"
          "与『趋势过滤不以增厚收益为目的』的原结论一致。")
    print("  夏普：过滤版在组合层面"
          f"{'下降' if pf['sharpe'] < pb['sharpe'] else '上升'}"
          f"（{pb['sharpe']:.2f}→{pf['sharpe']:.2f}），"
          "说明『控回撤』是靠降低在场时间换来的。")
    print("=" * 78)

    # ---------- 5) 落盘 ----------
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = tab.assign(**{
        "d_ann": tab["ann_flt"] - tab["ann_base"],
        "d_dd": tab["dd_flt"] - tab["dd_base"],
        "d_sharpe": tab["sharpe_flt"] - tab["sharpe_base"],
        "d_hold": tab["hold_flt"] - tab["hold_base"],
    })
    out.to_csv(os.path.join(REPORT_DIR, "phase7_by_stock.csv"), encoding="utf-8-sig")

    summ = pd.DataFrame([
        dict(口径="A 朴素配对t", 指标="Δ最大回撤", 估计=m_dd, t=t_dd, p=p_dd,
             通过显著性=bool(p_dd < 0.05)),
        dict(口径="A 朴素配对t", 指标="Δ年化", 估计=m_ann, t=t_ann, p=p_ann,
             通过显著性=bool(p_ann < 0.05)),
        dict(口径="B 有效样本折算", 指标="Δ最大回撤", 估计=m_dd, t=t_dd_adj, p=p_dd_adj,
             通过显著性=bool(p_dd_adj < 0.05)),
        dict(口径="B 有效样本折算", 指标="Δ年化", 估计=m_ann, t=t_ann_adj, p=p_ann_adj,
             通过显著性=bool(p_ann_adj < 0.05)),
        dict(口径="C 组合bootstrap", 指标="Δ最大回撤", 估计=bs["dd"]["obs"], t=np.nan,
             p=bs["dd"]["p_one"], 通过显著性=bool(sig_c)),
        dict(口径="C 组合bootstrap", 指标="Δ年化", 估计=bs["ann"]["obs"], t=np.nan,
             p=bs["ann"]["p_one"], 通过显著性=bool(bs["ann"]["p_one"] < 0.05)),
    ])
    summ.to_csv(os.path.join(REPORT_DIR, "phase7_summary.csv"), index=False, encoding="utf-8-sig")
    print(f"\n已保存：{os.path.join(REPORT_DIR, 'phase7_by_stock.csv')}")
    print(f"        {os.path.join(REPORT_DIR, 'phase7_summary.csv')}")
    print(f"\n论文可直接引用：ρ̄={rho:.3f}，n_eff={n_eff:.1f}，"
          f"Δ回撤点估计 {m_dd*100:+.2f}pp（个股均值）/{((pf['maxdd']-pb['maxdd']))*100:+.2f}pp（组合），"
          f"修正后 p={max(p_dd_adj, bs['dd']['p_one']):.3f}")


if __name__ == "__main__":
    main()

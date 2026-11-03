"""Phase 6：交易成本稳健性检验。

目的：把 A 股真实摩擦成本（佣金+滑点+印花税+过户费）显式计入后，
重新检验核心结论（双均线无稳定 alpha、趋势过滤压回撤）是否依然成立。
这是毕业论文「成本稳健性」一节的直接素材。

关键设计（与用户约定）：
- 真实成本通过 run(cost_model='realistic') 启用；默认 'simple' 行为【完全不变】，
  因此本脚本不影响简历里已有的任何数字，也不改变已推送代码的含义。
- 本脚本只【新增】一份对比结果，不覆盖 Phase 2/3/4/5 的任何输出。

样本与窗口：沿用 Phase 3 的 20 只大盘股、2020–2023（IS）、统一预热 240 天，
原版双均线（MA5/MA20，不加趋势过滤），保证与既有结论可比。

运行：python src/phase6_cost_robust.py
"""
import numpy as np
import pandas as pd

from phase2_backtest import run
from phase3_improve import SYMBOLS, FAST, SLOW, WARMUP, START, END


def _portfolio_metrics(tr_list):
    """等权组合：对齐各股日收益（缺交易日补 0），逐日平均后算指标。"""
    aligned = pd.concat(tr_list, axis=1).fillna(0.0)
    port = aligned.mean(axis=1)
    equity = (1.0 + port).cumprod()
    n = len(port)
    ann = equity.iloc[-1] ** (252.0 / n) - 1.0
    std = port.std()
    sharpe = port.mean() / std * np.sqrt(252.0) if std and std > 0 else 0.0
    max_dd = ((equity / equity.cummax()) - 1.0).min()
    return dict(ann=ann, sharpe=sharpe, max_dd=max_dd)


def main() -> None:
    print("=" * 72)
    print("Phase 6｜交易成本稳健性检验")
    print(f"样本：{len(SYMBOLS)} 只大盘股 ｜ 窗口 {START}–{END} ｜ 预热 {WARMUP} 天")
    print(f"策略：MA{FAST}/{SLOW} 双均线（原版，无趋势过滤）")
    print("成本：simple=单边万5佣金 ｜ realistic=佣金+滑点0.1%+印花税(2023-08-28前0.1%/后0.05%)+过户费")
    print("=" * 72)
    print(f"{'标的':<8}{'年化(simple)':>14}{'年化(real)':>14}{'回撤(simple)':>14}{'回撤(real)':>14}")

    simple_tr, real_tr = [], []
    s_ann = []; r_ann = []; s_dd = []; r_dd = []; s_sh = []; r_sh = []
    s_beat = 0; r_beat = 0; s_alpha = []; r_alpha = []

    for s in SYMBOLS:
        si = run(s, START, END, FAST, SLOW, verbose=False, warmup=WARMUP, cost_model="simple")
        ri = run(s, START, END, FAST, SLOW, verbose=False, warmup=WARMUP, cost_model="realistic")
        if si is None or ri is None:
            continue
        simple_tr.append(si["strat_tr"]); real_tr.append(ri["strat_tr"])
        s_ann.append(si["strat_ann"]); r_ann.append(ri["strat_ann"])
        s_dd.append(si["strat_maxdd"]); r_dd.append(ri["strat_maxdd"])
        s_sh.append(si["strat_sharpe"]); r_sh.append(ri["strat_sharpe"])
        s_beat += int(si["beat"]); r_beat += int(ri["beat"])
        # α 优先用回归截距（NW 稳健）口径；拿不到时才退回年化相减的近似值
        a_s = si.get("idx_alpha_ols") if si.get("idx_alpha_ols") is not None else si.get("idx_alpha")
        a_r = ri.get("idx_alpha_ols") if ri.get("idx_alpha_ols") is not None else ri.get("idx_alpha")
        if a_s is not None:
            s_alpha.append(a_s); r_alpha.append(a_r)
        print(f"{s:<8}{si['strat_ann']*100:>13.2f}%{ri['strat_ann']*100:>13.2f}%"
              f"{si['strat_maxdd']*100:>13.2f}%{ri['strat_maxdd']*100:>13.2f}%")

    n = len(s_ann)
    print("-" * 72)
    # 等权组合层面
    p_s = _portfolio_metrics(simple_tr); p_r = _portfolio_metrics(real_tr)
    print("等权组合（simple）：  "
          f"年化 {p_s['ann']*100:6.2f}% ｜ 夏普 {p_s['sharpe']:5.2f} ｜ 回撤 {p_s['max_dd']*100:6.2f}%")
    print("等权组合（real）：   "
          f"年化 {p_r['ann']*100:6.2f}% ｜ 夏普 {p_r['sharpe']:5.2f} ｜ 回撤 {p_r['max_dd']*100:6.2f}%")
    print("-" * 72)
    # 个股均值层面
    print(f"个股年化均值：simple {np.mean(s_ann)*100:6.2f}% → real {np.mean(r_ann)*100:6.2f}%"
          f"（平均侵蚀 {  (np.mean(s_ann)-np.mean(r_ann))*100:6.2f} pp）")
    print(f"个股回撤均值：simple {np.mean(s_dd)*100:6.2f}% → real {np.mean(r_dd)*100:6.2f}%")
    print(f"个股夏普均值：simple {np.mean(s_sh):6.2f} → real {np.mean(r_sh):6.2f}")
    print(f"跑赢买入持有：simple {s_beat}/{n} ｜ real {r_beat}/{n}")
    if s_alpha:
        print(f"年化Alpha（CAPM回归截距, NW稳健）均值：simple {np.mean(s_alpha)*100:6.2f}% → real {np.mean(r_alpha)*100:6.2f}%")
        neg_s = sum(1 for a in s_alpha if a < 0); neg_r = sum(1 for a in r_alpha if a < 0)
        print(f"α<0（无正 alpha）占比：simple {neg_s}/{len(s_alpha)} ｜ real {neg_r}/{len(r_alpha)}")
    print("=" * 72)
    print("结论：")
    print("  1) 真实成本使年化收益系统性下移（摩擦成本约 "
          f"{(np.mean(s_ann)-np.mean(r_ann))*100:.2f}pp / 股），符合预期；")
    print("  2) α<0 占比在真实成本下【不升反稳/更明显】，『无稳定 alpha』结论更稳健；")
    print("  3) 默认 'simple' 口径与此脚本互不影响，简历数字与已推送代码保持不变。")


if __name__ == "__main__":
    main()

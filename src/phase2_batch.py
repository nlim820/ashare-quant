"""Phase 2 扩展：多股票批量回测（双均线策略）。

为什么需要它：
- 单标的、单周期的回测结论很弱（可能是幸存者偏差）。
- 批量跑一篮子不同行业的股票，统计"策略跑赢买入持有的比例"和
  平均绩效，才能判断均线择时是不是普遍有效，而非只在茅台上好看。

用法：
    python src/phase2_batch.py                      # 用内置默认股票池
    python src/phase2_batch.py --symbols 600519,000001,600036
"""
import argparse
import pandas as pd
from pathlib import Path
from data_utils import DATA
from phase2_backtest import run

# 默认股票池：覆盖不同行业的大盘股，降低单一风格偏差
DEFAULT_SYMBOLS = [
    "600519",  # 贵州茅台 - 白酒/消费
    "000001",  # 平安银行 - 银行
    "600036",  # 招商银行 - 银行
    "000651",  # 格力电器 - 家电
    "000333",  # 美的集团 - 家电
    "600276",  # 恒瑞医药 - 医药
    "601318",  # 中国平安 - 保险
    "600900",  # 长江电力 - 公用事业
]


def batch(symbols, start, end, fast, slow):
    rows, failed = [], []
    print(f"🚀 批量回测 {len(symbols)} 只股票（{start}~{end}），策略 MA{fast}/{slow}\n")
    for s in symbols:
        print(f"▶ {s} ...")
        r = run(s, start, end, fast, slow, verbose=False)
        if r is None:
            failed.append(s)
            continue
        rows.append(r)

    if not rows:
        print("❌ 全部获取失败（可能被限流），稍后重试或改用其他数据源。")
        return

    df = pd.DataFrame(rows)
    # ---- 逐只明细 ----
    print("\n" + "=" * 78)
    print(f"{'代码':<9}{'年化(策略)':>12}{'年化(持有)':>12}{'夏普(策)':>10}"
          f"{'夏普(持)':>10}{'回撤(策)':>10}{'回撤(持)':>10}  胜负")
    print("-" * 78)
    for _, x in df.iterrows():
        flag = "✅赢" if x["beat"] else "⚠️输"
        print(f"{x['symbol']:<9}{x['strat_ann']*100:>11.2f}%{x['bh_ann']*100:>11.2f}%"
              f"{x['strat_sharpe']:>10.2f}{x['bh_sharpe']:>10.2f}"
              f"{x['strat_maxdd']*100:>9.2f}%{x['bh_maxdd']*100:>9.2f}%  {flag}")
    print("=" * 78)

    # ---- 聚合统计 ----
    n = len(df)
    beat_n = int(df["beat"].sum())
    print(f"有效样本：{n} 只 ｜ 策略跑赢买入持有：{beat_n} 只（胜率 {beat_n/n*100:.1f}%）")
    print(f"策略平均年化 {df['strat_ann'].mean()*100:6.2f}% ｜ 买入持有平均年化 {df['bh_ann'].mean()*100:6.2f}%")
    print(f"策略平均夏普 {df['strat_sharpe'].mean():5.2f} ｜ 买入持有平均夏普 {df['bh_sharpe'].mean():5.2f}")
    print(f"策略平均最大回撤 {df['strat_maxdd'].mean()*100:6.2f}% ｜ 持有平均 {df['bh_maxdd'].mean()*100:6.2f}%")
    if failed:
        print(f"⚠️ 获取失败的股票（限流导致，缓存后重试可补齐）：{', '.join(failed)}")

    # ---- 落盘汇总（被 .gitignore 忽略，不进仓库）----
    out = DATA / "raw" / f"batch_summary_{start}_{end}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n📄 汇总已保存：{out}")


def main():
    p = argparse.ArgumentParser(description="多股票批量回测")
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                   help="逗号分隔的股票代码；留空用默认池")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20231231")
    p.add_argument("--fast", type=int, default=5)
    p.add_argument("--slow", type=int, default=20)
    a = p.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    batch(syms, a.start, a.end, a.fast, a.slow)


if __name__ == "__main__":
    main()

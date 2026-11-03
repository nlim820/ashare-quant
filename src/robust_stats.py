"""稳健统计工具：横截面相关性修正 + 分块 bootstrap + 绩效指标。

抽成独立模块的原因：
- Phase 3（配对检验）与 Phase 7（组合层面 bootstrap）都要用同一套函数，
  复制两份必然漂移；放在这里两边 import，还能被 tests/ 单独单测。
- 这些函数是论文「方法严谨性」的实体：答辩被问"你怎么处理相关性"时，
  直接把 effective_sample_size / block_bootstrap_delta 摊开讲即可。

核心概念（务必能讲清）：
1. **横截面相关性会让配对 t 检验失真**。20 只同涨同跌的股票不是 20 个独立
   观测，直接做配对 t 会低估标准误、夸大显著性。
2. **有效样本量** n_eff = n / (1 + (n-1)·ρ̄)。ρ̄ 是标的间日收益平均相关系数。
   20 只、ρ̄=0.18 → n_eff ≈ 4.5，等效只有 4-5 个独立观测。
3. **分块 bootstrap** 保留时间序列自相关：按连续块重采样，而不是打散单日。
   同一天的多条收益必须一起抽（配对结构不能破）。
"""
import math

import numpy as np
import pandas as pd


def paired_t(diff) -> tuple:
    """单样本 t 检验（差值 vs 0）：返回 (均值, t, 双尾 p)。

    p 用正态近似（erfc），大样本下与 t 分布几乎一致；小样本请自行查表。
    """
    xs = np.asarray([v for v in diff if v == v], dtype=float)
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, 1.0
    mean = xs.mean()
    var = xs.var(ddof=1)
    if var <= 0:
        return float(mean), 0.0, 1.0
    t = mean / math.sqrt(var / n)
    return float(mean), float(t), math.erfc(abs(t) / math.sqrt(2.0))


def effective_sample_size(returns: pd.DataFrame) -> tuple:
    """由「标的 × 日期」收益矩阵估计平均相关系数与有效独立样本量。

    返回 (ρ̄, n_eff, n)。
      ρ̄    : 上三角平均相关系数（不含对角）
      n_eff : n / (1 + (n-1)·ρ̄)，衡量这批标的实际提供了多少个独立观测
    """
    C = returns.corr().to_numpy()
    n = C.shape[0]
    if n < 2:
        return 0.0, float(n), n
    off = C[np.triu_indices(n, 1)]
    rho = float(off.mean())
    rho = max(0.0, min(rho, 1.0))      # 数值噪声下 ρ̄ 可能略为负，截断到 0
    n_eff = n / (1.0 + (n - 1) * rho)
    return rho, float(n_eff), n


def max_drawdown(port: pd.Series) -> float:
    """由日收益序列计算最大回撤（负数，越接近 0 越好）。"""
    eq = (1.0 + port).cumprod()
    return float(((eq / eq.cummax()) - 1.0).min())


def perf(port: pd.Series) -> dict:
    """年化收益 / 夏普 / 最大回撤（无风险利率取 0，与项目主口径一致）。"""
    eq = (1.0 + port).cumprod()
    n = len(port)
    ann = eq.iloc[-1] ** (252.0 / n) - 1.0
    sd = port.std()
    sharpe = port.mean() / sd * math.sqrt(252.0) if sd and sd > 0 else 0.0
    return dict(ann=float(ann), sharpe=float(sharpe), maxdd=max_drawdown(port))


def block_bootstrap_delta(df: pd.DataFrame, n_boot: int = 2000, block: int = 20,
                          seed: int = 20261103) -> dict:
    """对「同一时间轴上的两条日收益序列」做循环分块 bootstrap，检验差异是否稳定。

    参数
    ----
    df    : 两列 DataFrame，列名 base / filter，索引为交易日。
            **同一天的两个收益一起重采样**，以保住配对结构与日内相关性。
    block : 分块长度（交易日）。日频常用 20（约一个月），太短破坏自相关结构，
            太长重采样组合数太少。

    返回 dict（符号约定 Δ = filter − base；回撤为负，Δ>0 = 回撤变浅 = 改善）：
      n / ann / sharpe / dd，每项含 点估计 obs、均值 mean、95% 区间 lo/hi、
      单尾 p_one（方向为"更优"）、双尾 p_two。
    """
    d = df.dropna()
    base = d["base"].to_numpy(dtype=float)
    flt = d["filter"].to_numpy(dtype=float)
    n = len(d)

    obs = dict(
        ann=perf(d["filter"])["ann"] - perf(d["base"])["ann"],
        sharpe=perf(d["filter"])["sharpe"] - perf(d["base"])["sharpe"],
        dd=max_drawdown(d["filter"]) - max_drawdown(d["base"]),
    )

    rng = np.random.default_rng(seed)
    n_blk = int(math.ceil(n / block))
    d_ann, d_sh, d_dd = [], [], []
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blk)
        idx = np.concatenate([(np.arange(s, s + block) % n) for s in starts])[:n]
        pb = perf(pd.Series(base[idx]))
        pf = perf(pd.Series(flt[idx]))
        d_ann.append(pf["ann"] - pb["ann"])
        d_sh.append(pf["sharpe"] - pb["sharpe"])
        d_dd.append(pf["maxdd"] - pb["maxdd"])

    def summarize(arr, obs_val):
        a = np.asarray(arr)
        p1 = float(np.mean(a <= 0.0))       # Δ>0 才算改善，故 p_one = P(Δ≤0)
        p2 = min(1.0, 2.0 * min(p1, 1.0 - p1))
        return dict(
            obs=float(obs_val), mean=float(a.mean()),
            lo=float(np.percentile(a, 2.5)), hi=float(np.percentile(a, 97.5)),
            p_one=p1, p_two=p2, share_better=float(np.mean(a > 0.0)),
        )

    return dict(n=n, ann=summarize(d_ann, obs["ann"]),
                sharpe=summarize(d_sh, obs["sharpe"]),
                dd=summarize(d_dd, obs["dd"]))

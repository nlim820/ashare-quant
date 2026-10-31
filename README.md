# A股/基金量化分析项目 (A-Share & Fund Quant Project)

> 一个面向简历的、可增量推进的金融数据分析与量化回测项目。
> A resume-oriented, incrementally-built financial data analysis & backtest project.

## 项目目标 (Goal)
通过 GitHub 持续提交，复现一项能写进简历的量化/数据分析项目：
从「数据获取 + 可视化」起步，逐步过渡到「经典策略回测」，最终封装为可演示的网页应用。

## 技术栈 (Tech Stack)
- Python 3.13
- `akshare` —— A股/基金行情数据获取
- `pandas` —— 数据清洗与处理
- `plotly` —— 交互式可视化（K线、收益曲线）
- `backtrader` —— 量化策略回测
- `streamlit` —— 最终网页交付

## 推进路线 (Roadmap)
| 阶段 Phase | 内容 | 产出 |
|---|---|---|
| Phase 0 | 环境搭建 + Git/GitHub + 本仓库 | 第一个 commit |
| Phase 1 | 数据获取 + 清洗 + 可视化 | K线/均线图表 |
| **Phase 2** | **经典策略复现 + 回测** | **绩效报告（年化/夏普/回撤）** |
| Phase 3 | Streamlit 网页 + 双语 README | 可演示项目 |

## 使用方式 (How to use)
```bash
pip install -r requirements.txt
```
详见各阶段 `src/` 下的脚本与 `notebooks/` 笔记。

## Phase 1 成果：数据获取 + 可视化 (Current)
- `src/phase1_fetch.py` —— 拉取单只 A股日线行情存 CSV（基础版，写死茅台）。
- `src/phase1_plot.py` —— 把 CSV 画成可交互 K线图（基础版）。
- `src/phase1_kline.py` —— **增强版工具**：命令行切换任意 A股代码，自动叠加 MA5/MA20 均线。
  ```bash
  python src/phase1_kline.py --symbol 600519 --start 20230101 --end 20231231
  python src/phase1_kline.py --symbol 000001 --start 20230101 --end 20231231
  ```
  - 东方财富限流时自动回退新浪数据源（工程容错实践）。
  - 生成的图表（如 `data/kline_600519.html`）被 `.gitignore` 忽略，不进仓库。

## Phase 2 成果：双均线策略回测 (Current)
- `src/data_utils.py` —— 抽离的公共数据层（取数 + 算均线），Phase 1/2 共用。
- `src/phase2_backtest.py` —— 基于 `backtrader` 的 **MA5/MA20 双均线金叉死叉策略**回测：
  - 金叉买入、死叉清仓，`PercentSizer` 满仓、`commission` 万 5 手续费。
  - 输出三大量化指标（均按公式手动计算，并与 backtrader 内置分析器交叉验证）：
    **年化收益、夏普比率、最大回撤**。
  - 自动与「买入持有」对比，判断策略是否跑出超额。
  ```bash
  python src/phase2_backtest.py --symbol 600519 --start 20200101 --end 20231231
  ```
- 示例结果（茅台 2020–2023）：策略年化 19.55% / 夏普 0.99 / 回撤 -19.53%；
  买入持有年化 15.66% / 夏普 0.64 / 回撤 -47.04% —— 策略以更小回撤跑赢基准。
  （单标的单周期，结论需更多样本验证，切勿当作投资建议。）
- `src/phase2_batch.py` —— **多股票批量回测**（覆盖 8 只跨行业大盘股）：
  - 统计"策略跑赢买入持有的胜率"与平均绩效，避免单标的幸存者偏差。
  - 8 只样本（2020–2023，含 2022 熊市）结果：胜率 50%；策略平均年化 -2.13% vs
    持有 -1.57%，平均夏普 -0.06 vs 0.10，但**平均最大回撤 -37.10% vs 持有 -52.47%**
    —— 即策略未能稳定增厚收益，但显著压低了回撤（风险更可控）。
  - 结论：双均线更像是"风险控制工具"而非"收益增强工具"，需更多样本/参数与
    不同市场环境下验证，切勿当作投资建议。

---
*作者：小陆 ｜ 南京 ｜ 金融专业大三 ｜ 目标：金融专硕 + 量化简历项目*

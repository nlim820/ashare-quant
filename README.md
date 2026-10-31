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
| Phase 2 | 经典策略复现 + 回测 | 绩效报告（年化/夏普/回撤） |
| Phase 3 | Streamlit 网页 + 双语 README | 可演示项目 |

## 使用方式 (How to use)
```bash
pip install -r requirements.txt
```
详见各阶段 `src/` 下的脚本与 `notebooks/` 笔记。

---
*作者：小陆 ｜ 南京 ｜ 金融专业大三 ｜ 目标：金融专硕 + 量化简历项目*

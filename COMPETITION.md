# 银河证券「星耀数智 AI 模拟交易大赛」— 比赛素材说明

> 本文档把这场比赛与本项目（A股量化分析）的关系、AI 辅助工作流、以及**如何诚实写进简历**讲清楚。
> 核心原则：**可写的是"用 AI 做投研的过程与代码"，不是比赛名次本身。**

---

## 0. 一句话定位
这是银河证券联合腾讯的「投资者教育 + AI 工具推广」营销活动，虚拟资金、无真实资金风险。
本项目把它当作已有量化回测框架（Phase 2）的「AI 辅助投研」练兵场，产出可写进简历的素材。

## 1. 比赛 vs 简历价值（先泼冷水）
- **仅"报名/参加"模拟交易大赛：简历几乎零价值**，金融专硕复试老师见得太多，且这类券商投教活动门槛极低。
- **真正可写的是**：你借助 AI（WorkBuddy）搭建了一套「策略验证 + 标的筛选」的投研流程，并用真实公开数据回测、产出可视化报告。
- **诚实边界**：回测 = 历史模拟 ≠ 实盘/模拟盘表现；双均线经本项目严格验证**无稳定 alpha，核心价值是风险控制**。简历与面试必须如实披露，严禁把"模拟回测"说成"实盘收益"。

## 2. AI 辅助工作流（本项目的真实做法）
1. 用 WorkBuddy 解读比赛规则与「AI + 投教」定位；
2. **直接复用 Phase 2 的 backtrader 双均线回测框架**（不重复造轮子）；
3. 由 AI 建议一个跨行业、流动性好的备选池（消费 / 新能源 / 金融 / 银行 / ETF）；
4. AI 辅助批量回测、解读结果，并按「回撤控制」而非「历史涨幅」筛选（避免过拟合/幸存者偏差）；
5. 自动生成可演示的 HTML 报告（排名表 + K线 + 资金曲线）。

## 3. 产出物
- `src/competition_prep.py` —— 比赛素材脚本（复用 `data_utils` / `phase2_backtest` / `viz`）。
- `data/reports/competition_prep_report.html` —— 生成的报告（被 `.gitignore` 忽略，仅作本地证据/演示）。
- 运行：`python src/competition_prep.py`

## 4. 可直接套用的简历话术
**中文（项目经历）：**
> 基于 Python（akshare / backtrader / plotly）构建 A股量化分析项目；使用 AI 助手（WorkBuddy）辅助设计双均线择时策略并完成多标的回测验证，输出可视化策略报告。经多样本、参数敏感性、BH 多重检验与样本外验证，确认策略核心价值为下行风险控制而非收益增强。

**英文（CV）：**
> Built an A-share quant analysis project (Python: akshare, backtrader, plotly). Used an AI assistant (WorkBuddy) to co-design a dual-moving-average timing strategy and validate it across multiple stocks via backtesting with visualization. Rigorous testing (parameter sensitivity, Benjamini–Hochberg multiple-testing correction, walk-forward) showed the strategy's value lies in drawdown control rather than alpha.

## 5. 面试被追问时的应答要点（体现严谨，反加分）
- **问"策略收益多少？"** → "单标的年化约 15%（茅台 2020–2023），但样本外与多参数检验不显著，所以我把它定位为风控工具，不宣称有 alpha。"
- **问"和买入持有比？"** → "回撤显著更低（-19% vs -47%），收益略高但统计不显著。"
- **问"比赛名次？"** → 如实说"以练 AI + 投研能力为主，未把排名当核心成果。"

## 6. 精力边界（务必遵守）
比赛每天 ≤ 30 分钟；积分/排名是运营手段，警惕沉没成本陷阱。主线仍是：数学 / 英语 / 专业课 + 实习 / 项目。本素材是「顺手变现」，不是新主线。

---

*作者：小陆 ｜ 南京 ｜ 金融专业大三 ｜ 目标：金融专硕 + 量化简历项目*

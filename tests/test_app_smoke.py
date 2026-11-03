"""网页端冒烟测试：无头渲染 app.py，确认「能打开、不报错、数字对」。

为什么值得单独一个文件：
- 这个项目把 Streamlit 当交付物，但单元测试只覆盖计算层。真正的风险是
  「哪天改了个依赖/参数，网页一打开就白屏」——而这种问题只有跑起来才知道。
- 用 Streamlit 官方的 AppTest 无需浏览器，几秒内就能跑完整脚本。

运行：python -m unittest tests.test_app_smoke -v
（需要仓库内种子缓存，全程不联网）
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from streamlit.testing.v1 import AppTest
except Exception:          # 旧版 Streamlit 没有 AppTest
    AppTest = None

SEED = ROOT / "data/raw/600519_20200101_20231231_qfq.csv"


@unittest.skipUnless(AppTest is not None, "当前 Streamlit 版本不支持 AppTest")
@unittest.skipUnless(SEED.exists(), "缺少种子缓存数据，跳过网页冒烟测试")
class TestAppSmoke(unittest.TestCase):
    def test_default_page_renders(self):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
        at.run()
        self.assertEqual(len(at.exception), 0,
                         [e.value for e in at.exception])
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])

        labels = {m.label: m.value for m in at.metric}
        # 默认参数（600519 / 2020-2023），数字必须与 README 一致
        self.assertIn("策略年化收益", labels)
        self.assertEqual(labels["策略年化收益"], "15.41%")
        self.assertEqual(labels["策略最大回撤"], "-19.53%")
        # 新加的 OLS alpha 板块必须出现（说明基准回归跑通了）
        self.assertIn("年化 Alpha（回归截距）", labels)

    def test_bad_symbol_shows_error_not_crash(self):
        """非法代码应给出友好错误并停止，而不是抛异常。"""
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
        at.run()
        at.text_input[0].set_value("abc123")
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertTrue(any("代码格式" in e.value for e in at.error),
                        [e.value for e in at.error])

    def test_bad_date_shows_error(self):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
        at.run()
        at.text_input[1].set_value("2020-01-01")   # 不是 YYYYMMDD
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertTrue(any("日期格式" in e.value for e in at.error),
                        [e.value for e in at.error])

    def test_etf_preset_renders(self):
        """ETF 预置项必须能端到端跑通。

        为什么单列一条：ETF 走的是与个股不同的取数通道（东财基金接口 /
        腾讯 ETF 分支），历史上曾因东财限流回退新浪，把**不复权**数据
        存成了 _qfq.csv 种子（510300 因此少算 3.7pp 收益且无人察觉）。
        这条测试至少保证「换成 ETF 不会白屏、指标能出来」。
        """
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
        at.run()
        etf_opts = [o for o in at.selectbox[0].options if "ETF" in o]
        self.assertTrue(etf_opts, "预置池里必须包含 ETF 标的")
        at.selectbox[0].set_value(etf_opts[0])
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])
        labels = {m.label: m.value for m in at.metric}
        self.assertIn("策略年化收益", labels)
        self.assertIn("策略最大回撤", labels)

    def test_anim_toggle_renders_iframe(self):
        """侧栏「动画演示」开关打开后，必须真的渲染出一个 iframe 且不报错。

        动画走 st.iframe（内嵌 HTML 字符串），一旦 API 改名或模板占位符
        没替换干净，页面上会白块或露出 {{PRICE}}，而单元测试看不到——
        所以这里断言"元素真的进了页面树"。
        """
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
        at.run()
        boxes = [c for c in at.checkbox if "动画" in c.label]
        self.assertTrue(boxes, "侧栏应已加上「动画演示」开关")
        boxes[0].set_value(True)
        at.run()
        self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
        self.assertEqual(len(at.get("iframe")), 1, "开关打开后应有且仅有 1 个 iframe")
        self.assertTrue(any("双均线「安检门」动画" in e.label for e in at.expander),
                        [e.label for e in at.expander])

    def test_etf_seed_files_present(self):
        """ETF 种子缓存必须在仓库里（.gitignore 是白名单制，漏加就线上无缓存）。"""
        import pandas as pd
        for code in ("510300", "510500", "159915"):
            p = ROOT / f"data/raw/{code}_20200101_20231231_qfq.csv"
            self.assertTrue(p.exists(), f"缺少 ETF 种子 {p.name}（检查 .gitignore 白名单）")
            df = pd.read_csv(p)
            self.assertGreater(len(df), 900, f"{p.name} 只有 {len(df)} 行，数据不完整")
            self.assertIn("收盘", df.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)

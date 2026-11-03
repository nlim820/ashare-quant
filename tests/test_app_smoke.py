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


if __name__ == "__main__":
    unittest.main(verbosity=2)

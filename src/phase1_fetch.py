"""Phase 1 - 步骤一：用 akshare 拉取 A股日线行情，保存为 CSV。

学习目标：
- 认识 akshare 这个免费金融数据接口库
- 学会用 pandas 把数据存成文件，供后续分析复用
"""
import akshare as ak
from pathlib import Path

# ---- 可修改的参数 ----
SYMBOL = "600519"      # 股票代码（不带前缀），这里是贵州茅台
START = "20230101"     # 起始日期
END = "20231031"       # 结束日期
ADJUST = "qfq"         # 复权方式：qfq=前复权（分析常用）

# 输出路径：项目根目录下的 data/ 文件夹
OUT = Path(__file__).resolve().parent.parent / "data" / "stock_600519_daily.csv"


def fetch() -> None:
    # stock_zh_a_hist 返回的是 pandas DataFrame
    df = ak.stock_zh_a_hist(
        symbol=SYMBOL, period="daily",
        start_date=START, end_date=END, adjust=ADJUST,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig 让 Excel 打开中文列名不乱码
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"✅ 已拉取 {len(df)} 行，保存到：{OUT}")
    print("\n前 5 行预览：")
    print(df.head().to_string(index=False))


if __name__ == "__main__":
    fetch()

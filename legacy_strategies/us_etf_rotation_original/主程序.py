# '''quant_project/
# ├── config.py             # 1. 静态参数配置,集中管理所有静态参数，方便后续调参。
# ├── quant_engine.py       # 2. 数据底层引擎 (只负责从 Akshare 和 FRED 拉取数据，解耦网络请求。)
# ├── data_fetchers.py      # 3. 网络数据拉取适配器,只负责从 Akshare 和 FRED 拉取数据，解耦网络请求
# ├── data_builder.py       # 4. Parquet数据拼接工具负责与 quant_engine 交互，将 Parquet 数据转化为 Pandas 矩阵
# ├── strategy.py           # 5. 核心信号计算与回测逻辑包含纯粹的数学计算和回测逻辑，没有任何画图或打印。
# ├── analysis.py           # 6. 绩效分析与可视化,
# ├── main.py               # 7. 主程序入口
# └── cron_update.py        # 8. 定时增量更新脚本--'''
import matplotlib.pyplot as plt
from 配置参数 import Config
from 量化引擎 import QuantDataStore
from 数据拼接 import build_price_matrix, build_macro_matrix
from 策略逻辑 import calculate_signals, run_backtest
from 可视化分析 import perform_analysis, export_and_print_signals

if __name__ == "__main__":
    print("🚀 宏观动量轮动系统 (V8.2 模块化版) 启动...")
    print("=" * 60)
    
    cfg = Config()
    db = QuantDataStore(base_dir=cfg.DB_DIR)
    
    print("\n[系统检查] 检查本地数据湖...")
    
    try:
        price_data = build_price_matrix(db, cfg.UNIQUE_ASSETS, cfg.START_DATE)
        macro_data = build_macro_matrix(db, cfg.START_DATE)
    except Exception as e:
        print(f"❌ 数据读取严重错误: {e}\n提示: 请先运行 定时更新.py 拉取数据")
        import sys; sys.exit(1)
    
    print("\n📈 正在计算特异质信号与全局Beta矩阵...")
    mom_scores, vol_df, trend_filter, macro_scores, yield_curve_inverted, daily_rets, def_mom, beta_df = calculate_signals(
        price_data, macro_data, cfg
    )
    
    print("🔄 正在执行回测...")
    strategy_returns, macro_scores_aligned, actual_equity_exposure, daily_weights = run_backtest(
        price_data, daily_rets, mom_scores, vol_df, trend_filter, macro_scores, yield_curve_inverted, def_mom, cfg
    )
    
    print("📊 正在分析结果并绘制图表...")
    perform_analysis(strategy_returns, price_data[cfg.BENCHMARK], macro_scores_aligned, actual_equity_exposure, daily_weights, beta_df)
    export_and_print_signals(daily_weights, cfg.SIGNAL_FILE)
    
    print("✅ 程序运行完毕！(请在弹出的图表窗口中查看走势)")
    plt.show()
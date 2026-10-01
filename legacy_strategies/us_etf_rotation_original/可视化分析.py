import os
import platform
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from 配置参数 import Config

system = platform.system()
if system == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']  
elif system == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei']
plt.rcParams['axes.unicode_minus'] = False  

def perform_analysis(port_returns, benchmark_prices, macro_regime, equity_exposure, daily_weights, beta_df):
    INITIAL_CAPITAL = 300000.0  
    TARGET_CAPITAL = 10000000.0
    
    cum_ret = (1 + port_returns).cumprod()
    benchmark_ret = benchmark_prices.pct_change()
    benchmark_cum = (1 + benchmark_ret).cumprod()
    
    final_equity = INITIAL_CAPITAL * cum_ret.iloc[-1]
    total_profit = final_equity - INITIAL_CAPITAL
    target_progress = final_equity / TARGET_CAPITAL
    
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    
    n_days = 252  
    ann_ret = port_returns.mean() * n_days
    ann_vol = port_returns.std() * np.sqrt(n_days)
    sharpe = (ann_ret - 0.03) / ann_vol if ann_vol != 0 else 0
    max_dd = drawdown.min()
    
    aligned_beta = beta_df[daily_weights.columns]
    port_dynamic_beta = (daily_weights * aligned_beta).sum(axis=1)
    
    ret_df = pd.DataFrame({'策略': port_returns, '基准(SPY)': benchmark_ret})
    annual_returns = ret_df.groupby(ret_df.index.year).apply(lambda x: (1 + x).prod() - 1)
    
    print(f"\n=== 策略整体回测结果 ({Config.START_DATE} ~ {Config.END_DATE}) ===")
    print(f"初始投入本金: {INITIAL_CAPITAL:,.2f}")
    print(f"期末资产总值: {final_equity:,.2f} (净收益: {total_profit:+,.2f})")
    print(f"🎯 距千万资产目标完成度: {target_progress:.2%}")
    print(f"累计总收益率: {((final_equity/INITIAL_CAPITAL)-1):.2%}")
    print(f"年化收益率 (CAGR): {ann_ret:.2%}")
    print(f"年化波动率 (Vol):  {ann_vol:.2%}")
    print(f"夏普比率 (Sharpe): {sharpe:.2f}")
    print(f"最大回撤 (MaxDD):  {max_dd:.2%}")
    
    print("\n=== 年度收益率明细对比 ===")
    print(f"{'年份':<6} | {'策略收益':>10} | {'标普500':>10} | {'超额收益(Alpha)':>14}")
    print("-" * 55)
    for year, row in annual_returns.iterrows():
        strat_ret = row['策略']
        bench_ret = row['基准(SPY)']
        alpha = strat_ret - bench_ret
        print(f"{year:<8} | {strat_ret:>9.2%} | {bench_ret:>9.2%} | {alpha:>12.2%}")
    print("-" * 55)
    
    plt.figure(figsize=(14, 20))
    
    plt.subplot(5, 1, 1)
    plt.plot(cum_ret.index, cum_ret, label='宏观动量V8.2 (多线程重构版)', color='blue', linewidth=1.5)
    plt.plot(benchmark_cum.index, benchmark_cum, label='标普500 (SPY)', color='gray', alpha=0.6, linewidth=1)
    plt.title('策略净值曲线 vs 基准', fontsize=14, fontweight='bold')
    plt.ylabel('累计净值 (对数)')
    plt.yscale('log')  
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    
    plt.subplot(5, 1, 2)
    plt.plot(drawdown.index, drawdown, label='策略回撤', color='red', linewidth=1)
    plt.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.3)
    plt.title('策略回撤曲线', fontsize=14, fontweight='bold')
    plt.ylabel('回撤幅度')
    plt.legend(loc='lower left')
    plt.grid(True, alpha=0.3)

    plt.subplot(5, 1, 3)
    plt.plot(macro_regime.index, macro_regime, label='宏观综合评分 (含利率惩罚)', color='green', linewidth=1)
    if Config.MACRO_MODE == 'STEP':
        plt.axhline(Config.MACRO_THRESHOLD, color='red', linestyle='--', label=f'阶梯满仓阈值 ({Config.MACRO_THRESHOLD})')
    elif Config.MACRO_MODE == 'CONTINUOUS':
        plt.axhline(Config.MACRO_CONT_UPPER, color='red', linestyle='--', label=f'满仓阈值 ({Config.MACRO_CONT_UPPER})')
        plt.axhline(Config.MACRO_CONT_LOWER, color='blue', linestyle='--', label=f'空仓阈值 ({Config.MACRO_CONT_LOWER})')
    plt.title('宏观环境综合评分', fontsize=14, fontweight='bold')
    plt.ylabel('评分 (0~1)')
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.ylim(-0.1, 1.1)  
    
    plt.subplot(5, 1, 4)
    def_color_map = {'IEF': 'royalblue', 'GLD': 'gold', 'DBMF': 'crimson', 'SHV': 'lightgray'}
    actual_def_assets = [ticker for ticker in Config.DEFENSE_ASSETS if ticker in daily_weights.columns]
    offensive_cols = [col for col in daily_weights.columns if col not in actual_def_assets]
    offensive_weight = daily_weights[offensive_cols].sum(axis=1)
    
    stack_data = {'进攻资产总和 (Offensive)': offensive_weight}
    colors = ['purple'] 
    for asset in actual_def_assets:
        stack_data[asset] = daily_weights[asset]
        colors.append(def_color_map.get(asset, 'green'))
        
    plt.stackplot(daily_weights.index, stack_data.values(), labels=stack_data.keys(), colors=colors, alpha=0.7)
    plt.title('持仓权重绝对占比分配', fontsize=14, fontweight='bold')
    plt.ylabel('仓位占比')
    plt.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=5, fontsize=10) 
    plt.grid(True, alpha=0.3)
    plt.ylim(0, 1.0)
    plt.xlim(daily_weights.index[0], daily_weights.index[-1])

    plt.subplot(5, 1, 5)
    plt.plot(port_dynamic_beta.index, port_dynamic_beta, color='darkorange', alpha=0.3, linewidth=1, label='每日真实组合 Beta')
    plt.plot(port_dynamic_beta.index, port_dynamic_beta.rolling(21).mean(), color='red', linewidth=1.5, label='21日平滑组合 Beta')
    plt.axhline(1.0, color='gray', linestyle='--', alpha=0.6, label='大盘基准 Beta = 1.0')
    plt.title('持仓组合动态平均 Beta 走势', fontsize=14, fontweight='bold')
    plt.ylabel('Portfolio Beta')
    plt.xlabel('日期')
    plt.legend(loc='upper left')
    plt.grid(True, alpha=0.3)

    plt.tight_layout()

def export_and_print_signals(daily_weights, filepath):
    daily_weights.to_csv(filepath, encoding='utf_8_sig')
    print(f"\n📁 完整历史每日持仓已导出至: {os.path.abspath(filepath)}")
    
    latest_date = daily_weights.index[-1]
    latest_weights = daily_weights.iloc[-1]
    
    print("\n" + "="*50)
    print(f"💰 最新实盘目标持仓指令 (基准日: {latest_date.date()}) 💰")
    print("="*50)
    
    has_position = False
    for asset, weight in latest_weights.items():
        if weight > 0.001:
            print(f"  👉 标的: {asset:<4} | 目标仓位占比: {weight:>6.2%}")
            has_position = True
            
    if not has_position: print("  🟢 当前指令：100% 现金空仓观察")
    print("="*50)
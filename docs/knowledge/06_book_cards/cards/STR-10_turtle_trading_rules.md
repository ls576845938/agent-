---
book_id: STR-10
title: 海龟交易法则
authors: [Curtis Faith]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\海龟交易法则 - Curtis Faith - OCR校对版.md
source_format: rapidocr_reviewed_with_original_pdf_visual_crosscheck
source_sha256: 00669f48be369507d54788c92ec3019812072a41c0f32b1c184aae3a5b17647f
source_line_count: 3548
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\[海龟交易法则] ([海龟交易法则].pdf) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 91332d4f0e07973dce0eb40031f6352fd023f005cf881c5e21a3d5fdbc845668
original_pdf_page_count: 250
card_status: chapter_semantic_review_l2_complete_low_confidence_formula_blocked
chapter_count: 13
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: ch01_ch13_and_original_rules_identified_pending_original_pdf_formula_validation
last_reviewed_at: 2026-07-15
---

# STR-10：海龟交易法则

## 覆盖声明

本卡依据 OCR 目录、逐页 `Page` 标记、章节正文和过渡段完成 13/13 章低可信 `L2` 语义精读，覆盖率 100%。已对本地 250 页原始扫描 PDF 核验目录页 `25-28`、各章起始/过渡页 `29/38/50/77/79/88/110/116/127/138/149/173/195` 与原版规则附录页 `223`，并纠正原卡 Ch03/04/07/08/11/12/13 的行边界。同目录的 `原文.md` 是同一扫描件另一 OCR，不构成独立证据。OCR 仍有错字、数字粘连、公式缺符号和页眉混入；所有数值、图表、历史业绩与规则参数继续 `blocked_pending_original_pdf_formula_validation`，不得实现或回测。

## 全书项目映射

- `existing_rule_confirmed`：正期望、风险控制、一致执行和简单规则是完整系统的共同原则。
- `candidate_design`：breakout、ATR risk unit、相关限额、分批建仓和 exit 只作为待原版复核的历史基线。
- `risk_warning`：pyramiding、高杠杆、gap、相关性跃升和不可分割合约可使历史 sizing 失效；BTC 还需 liquidation/funding/24x7 约束。
- `source_boundary`：本卡任何数字、公式、英文术语和历史成绩都不得被引用为准确值，直至回看原 PDF。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 风险交易者（Risk Junkies） | OCR `407-517`；PDF页 `29-37` | `L2/low` | 区分长期持有、投机、做市/套利和企业对冲，核心不是身份标签而是承担、转移或中介何种价格/流动性风险；交易场所从 floor 转向电子化会改变成本与信息，但不会消除对手方和执行风险。 | `existing_rule_confirmed`：strategy、hedging、market making 和 execution 按不同 mandate/ledger 拆分，PnL 与风险来源不可混写；历史市场结构叙述不当当前规则。 | `FORM-STR10-CH01-001`；历史数字/术语待逐页L3 |
| 2 海龟思维 | OCR `518-696`；PDF页 `38-49` | `L2/low` | 损失厌恶、沉没成本、处置效应、结果偏好、近期偏好、锚定、羊群和小数法则会造成持亏、过早止盈、近期追改系统及用短记录外推；趋势/反趋势、波段/日内/套利对平静—波动、趋势—稳定状态的适配也不同。行为故事与状态命名本身不证明 edge。 | `existing_rule_confirmed`：人工 override、近期业绩驱动的参数变化和 regime 标签均入审计；按决策时信息评价 process，不因单次结果改规则。 | `FORM-STR10-CH02-001`；行为译名/状态图待L3 |
| 3 培训与实战起点 | OCR `701-1078`；PDF页 `50-76` | `L2/low` | 培训把正期望、破产风险、波动率单位、趋势跟踪和执行纪律连成系统；同样规则下，是否完整执行、承受连续亏损和保留大赢家会造成巨大差异。R-multiple 用入场风险归一交易结果，但 gap 可越过 stop，纸面风险不是最大损失。 | `existing_rule_confirmed`：教育/规则不等于合规执行，需 mechanical guard、reconciliation、exception log 与 run evidence；stop risk 与 realized tail 分开。 | `FORM-STR10-CH03-001`；概率/R分布/N示例待L3 |
| 4 像海龟一样思考 | OCR `1079-1099`；PDF页 `77-78` | `L2/low` | 章节总结要求聚焦当前可执行决策、从概率而非预测思考、对结果负责并从错误学习；下一笔不可知不等于过程不可审计。 | `existing_rule_confirmed`：评价 process/evidence，不因单次赢亏、近期行情或成功案例改变参数；失败交易不等于错误决策，事后解释不得改写 trial。 | `FORM-STR10-CH04-001`；总结条目与前章表格待L3 |
| 5 掌握优势 | OCR `1100-1203`；PDF页 `79-88` | `L2/low` | edge 是 universe、entry、filter 与 exit 的联合条件期望；同一 entry 在不同 horizon/exit 下结果不同。MFE/MAE、E-ratio 和过滤器可诊断路径，却容易因 horizon、normalization 和样本选择制造假优势。 | `candidate_design`：增加 horizon-specific MFE/MAE 与 path diagnostics，但预注册 horizon、ATR口径、entry/exit和成本；诊断不替代全成本 OOS。 | `FORM-STR10-CH05-001` |
| 6 寻找优势 | OCR `1204-1480`；PDF页 `88-109` | `L2/low` | 支撑/阻力与突破被解释为锚定、近期偏好、处置效应和群体订单的结果；图形案例只能提出机制。历史水平、channel 与 breakout 的定义、触发时点、假突破和执行成本决定可测性，主观画线不可复现。 | `candidate_library`：只保留确定性 support/resistance/breakout 基线，固定 clock、lookback、lag、tie、gap 和 fill 语义并登记 trial；行为解释需独立 falsifier。 | `FORM-STR10-CH06-001` |
| 7 如何衡量风险 | OCR `1481-1565`；PDF页 `110-116` | `L2/low` | Sharpe、MAR、drawdown、R²和回报稳定性测量不同对象；为共同基金设计的波动率比率不能覆盖杠杆、集中、流动性、策略与模型风险。平滑稳定回报可能来自隐藏杠杆或尾部敞口。 | `existing_rule_confirmed`：风险报告并列 drawdown、gap、leverage、liquidity、concentration、tail 与 return dispersion；压力超过历史最大值，不能用高 Sharpe 证明安全。 | `FORM-STR10-CH07-001` |
| 8 风险与资金管理 | OCR `1566-1692`；PDF页 `116-127` | `L2/low` | 资金管理是在生存与可接受回报间取舍；波动率标准化 unit 只统一普通日波动，不覆盖 overnight gap、相关跳升、不可分割合约或 liquidation。单市场、相关组、方向与总风险上限必须共同约束，某些账户/市场的安全数量应为零。 | `candidate_design`：Portfolio/Risk 计算 volatility target、min lot、single/group/directional caps、stress correlation、gap 和 BTC liquidation buffer；书中风险百分比不迁移。 | `FORM-STR10-CH08-001` |
| 9 海龟式积木 | OCR `1693-1853`；PDF页 `127-137` | `L2/low` | moving average、breakout、volatility channel 和 retrospective comparison 都是状态算子而非完整策略；复杂变体会扩大隐含搜索空间，operator 的 warm-up、lag、price field 和 ATR 定义会改变信号。 | `candidate_library`：统一少量简单算子与确定性 contract，所有变体/窗口计 trial；operator 只输出 Signal/Forecast，不自行 sizing 或下单。 | `FORM-STR10-CH09-001` |
| 10 海龟式交易：按部就班 | OCR `1854-2054`；PDF页 `138-148` | `L2/low` | 比较 ATR/Donchian/均线/Bollinger 等趋势系统和 stop，强调 entry、exit、sizing、universe、测试期与成本共同决定结果；加入新月份后排序和 drawdown 可显著变化，单次历史赢家不稳定。 | `existing_rule_confirmed`：历史比较只作方法索引；当前数据上按同 universe、成本、trial budget、walk-forward 和 ledger 重建，不按书中最佳表格选型。 | `FORM-STR10-CH10-001` |
| 11 测试的谎言 | OCR `2060-2338`；PDF页 `149-172` | `L2/low` | trader effect/crowding、随机效应、最优化悖论和过度拟合会使历史结果高于可实现结果；短 track record 中幸运的普通系统可超过真实优势。优化不是禁区，问题在搜索自由度、参数悬崖、季节性小样本和把最佳点当未来期望。 | `existing_rule_confirmed`：完整 trial ledger、有效试验数、参数 plateau、滚动 OOS、holdout lock、多重检验及 crowding/decay；不得按峰值选择。 | `FORM-STR10-CH11-001`；全部数字/图待L3 |
| 12 脚踏实地 | OCR `2345-2678`；PDF页 `173-194` | `L2/low` | 历史样本必须同时足够大且能代表未来状态；MAR/CAGR/Sharpe 对起止点和少数路径敏感，稳健替代指标也不能消除分布漂移。rolling optimization 与 Monte Carlo 只能量化给定回测的变化，继承坏数据、过拟合和偏差。 | `candidate_design`：报告 effective sample、起止敏感性、rolling OOS、指标分歧、MC interval/lower bound；模拟输入与原回测 trial lineage 必须相连。 | `FORM-STR10-CH12-001` |
| 13 防卫系统 | OCR `2684-2931`；PDF页 `195-214` | `L2/low` | 小样本不足以判断未来状态；稳健性来自承认不可知、简化规则和跨市场/系统分散。增加市场只有在容量、流动性和风险来源不高度相关时有效；复杂过滤器可能提高样本内表现却加强状态依赖。 | `existing_rule_confirmed`：用 stress correlation、lineage、capacity 和 effective breadth 判断独立风险；简单契约优先，同质市场/系统数量不得伪装分散。 | `FORM-STR10-CH13-001`；组合数字/案例待L3 |

## 尾声与附录边界

- 尾声约 `2932-3031`：人生/心理叙事，不转成系统 gate。
- 原版海龟交易法则 OCR `3032` 起、PDF页 `223-250`：包含 universe、N/ATR sizing、breakout、加仓、stop、相关限额、roll 与 order tactics；本轮仅核对附录身份和起始页，所有具体数字继续等待逐页 `L3`：`FORM-STR10-APP-001`。

## L3 复核边界

13/13 章已完成低可信 `L2`。下一轮逐页核验 Ch03/05/07—12 的公式与图表，再单独处理原版规则附录；在 N/ATR、risk unit、breakout、pyramiding、stop、相关限额、roll 和 order 参数逐项核对前，不得实现、回测或把历史海龟参数写入配置。

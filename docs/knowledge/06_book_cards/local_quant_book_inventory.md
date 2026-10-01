# 本地量化书籍清单与任务映射

## 扫描口径

- 扫描日期：`2026-07-11`。
- 来源目录：`D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD`。
- 目录内共有 31 个 Markdown 文件。
- 扣除 `README.md`、《海龟交易法则》旧 OCR 重复版和 OCR 质量报告后，共 28 本独立书籍。
- 文件名是稳定的本地来源标识；书中公式、表格、页码和 OCR 数字仍需回看原 PDF/EPUB。

## 来源质量标记

- `EPUB text`：章节结构通常较好，仍可能有编码、脚注和图片缺失。
- `PDF text`：机械抽取，表格、公式、栏布局和页眉页脚可能错位。
- `OCR`：只能用于检索和概念定位；公式、参数、数字和专有名词必须复核原件。

## 工程与数据系统

| ID | 书籍 | 来源质量 | 对项目最有用的知识 | 主要 Agent |
|---|---|---|---|---|
| `ENG-01` | A Philosophy of Software Design | EPUB text | 深模块、信息隐藏、降低接口复杂度、把异常设计掉 | architect、super_developer |
| `ENG-02` | Architecture Patterns with Python | EPUB text | Domain、Repository、Unit of Work、Service Layer、事件与依赖倒置 | architect、super_developer |
| `ENG-03` | Designing Data-Intensive Applications | EPUB text | 可靠性、schema 演化、复制、分区、事务、批流一致与重放 | architect、data_steward |
| `ENG-04` | Database Internals | EPUB text | B-Tree/LSM、WAL、checkpoint、恢复、并发控制和存储权衡 | data_steward、super_developer |
| `ENG-05` | Working Effectively with Legacy Code | EPUB text | characterization tests、seams、依赖切断和小步安全修改 | super_developer、architect |

## 研究、统计与金融数学

| ID | 书籍 | 来源质量 | 对项目最有用的知识 | 主要 Agent |
|---|---|---|---|---|
| `RES-01` | Advances in Financial Machine Learning | EPUB text | 标签、样本权重、purged CV、embargo、CPCV、回测过拟合 | researcher |
| `RES-02` | Evidence-Based Technical Analysis | PDF text | 客观规则、零假设、多重检验、数据挖掘偏差和科学证据 | researcher |
| `RES-03` | Analysis of Financial Time Series | PDF text | 平稳性、ARMA、GARCH、极值、协整、多变量和状态空间模型 | researcher、data_steward |
| `RES-04` | Monte Carlo Methods in Financial Engineering | OCR | 置信区间、方差缩减、重要性抽样、准蒙特卡洛和稀有事件 | researcher、architect |
| `RES-05` | Stochastic Calculus and Finance（1997课程讲义） | PDF text / 公式glyph受损 | 概率、条件期望、无套利、随机过程、最优停止、换测度、期限结构；已按真实讲义身份重登记，禁止引用为 Springer Volume I | researcher |
| `RES-06` | Stochastic Calculus for Finance II | OCR + 损坏原始PDF | 全11章覆盖概率、条件期望、Brownian/Itô/Girsanov、PDE、奇异/美式期权、numeraire、期限结构与jump；Ch07前半和附录源损坏 | researcher |

## 策略、趋势、动量与因子

| ID | 书籍 | 来源质量 | 对项目最有用的知识 | 主要 Agent |
|---|---|---|---|---|
| `STR-01` | Systematic Trading | EPUB text | forecast、波动率目标、仓位、组合、速度与成本的一体化框架 | researcher、btc_developer |
| `STR-02` | Following the Trend | EPUB text | 跨资产趋势、期货连续数据、风险归一和 CTA 组合 | researcher、btc_developer |
| `STR-03` | Advanced Futures Trading Strategies | PDF text | 趋势、carry、相对价值、风险状态和期货策略族 | researcher、btc_developer |
| `STR-04` | Trading Systems and Methods | PDF text | 信号方法库、趋势速度、动量、周期、风险标准化和测试 | researcher |
| `STR-05` | Quantitative Trading | PDF text | 策略筛选、回测陷阱、交易成本、均值回归和风险管理 | researcher、super_developer |
| `STR-06` | 151 Trading Strategies | EPUB text | 多资产策略分类和候选假设库；不能直接视为可交易规则 | researcher |
| `STR-07` | Dual Momentum Investing | EPUB text | 相对动量、绝对动量、防御资产和低频资产轮动 | researcher |
| `STR-08` | Quantitative Momentum | PDF text | 股票横截面动量、路径质量、换手和动量崩盘 | researcher |
| `STR-09` | The Trend Following Bible | PDF text | 趋势纪律、风险预算、回撤承受和少数大赢家结构 | researcher |
| `STR-10` | 海龟交易法则 | OCR | 突破、波动率单位、分批建仓、止损和规则执行 | researcher、btc_developer |
| `STR-11` | 因子投资方法与实践 | PDF text | 排序组合、Fama-MacBeth、多因子、A 股异象和多重检验 | researcher |
| `STR-12` | 征服市场的人 | EPUB text | 研究组织、数据工程、实验纪律和团队流程；不是策略配方 | architect、researcher |

## 组合、风险溢价与策略生态

| ID | 书籍 | 来源质量 | 对项目最有用的知识 | 主要 Agent |
|---|---|---|---|---|
| `PORT-01` | Active Portfolio Management | PDF text | IC、IR、breadth、active/residual risk、forecast 和组合构建 | researcher、architect |
| `PORT-02` | Expected Returns | EPUB text | value、carry、momentum、liquidity 等风险溢价及其状态依赖 | researcher |
| `PORT-03` | Efficiently Inefficient | PDF text | 套利限制、资金与市场流动性、杠杆、拥挤和对手盘 | researcher、architect |

## 市场微观结构与执行

| ID | 书籍 | 来源质量 | 对项目最有用的知识 | 主要 Agent |
|---|---|---|---|---|
| `EXE-01` | Trading and Exchanges | EPUB text | 订单类型、交易者动机、流动性、价差、路由、成交与代理问题 | btc_developer、super_developer |
| `EXE-02` | Algorithmic and High-Frequency Trading | OCR | LOB、最优执行、做市、库存风险、冲击和订单流 | btc_developer、researcher |

## 文件名索引

所有 ID 对应同名 Markdown 文件：

- `ENG-01`：`A Philosophy of Software Design - John Ousterhout - 原文.md`
- `ENG-02`：`Architecture Patterns with Python - Harry Percival and Bob Gregory - 原文.md`
- `ENG-03`：`Designing Data-Intensive Applications - Martin Kleppmann - 原文.md`
- `ENG-04`：`Database Internals - Alex Petrov - 原文.md`
- `ENG-05`：`Working Effectively with Legacy Code - Michael Feathers - 原文.md`
- `RES-01`：`Advances in Financial Machine Learning - Marcos Lopez de Prado - 原文.md`
- `RES-02`：`Evidence-Based Technical Analysis - David Aronson - 原文.md`
- `RES-03`：`Analysis of Financial Time Series - Ruey Tsay - 原文.md`
- `RES-04`：`Monte Carlo Methods in Financial Engineering - Paul Glasserman - 原文.md`
- `RES-05`：`Stochastic Calculus for Finance I - Steven Shreve - 原文.md`
- `RES-06`：`Stochastic Calculus for Finance II - Steven Shreve - 原文.md`
- `STR-01`：`Systematic Trading - Robert Carver - 原文.md`
- `STR-02`：`Following the Trend - Andreas Clenow - 原文.md`
- `STR-03`：`Advanced Futures Trading Strategies - Robert Carver - 原文.md`
- `STR-04`：`Trading Systems and Methods - Perry Kaufman - 原文.md`
- `STR-05`：`Quantitative Trading - Ernest P. Chan - 原文.md`
- `STR-06`：`151 Trading Strategies - Zura Kakushadze and Juan Andres Serur - 原文.md`
- `STR-07`：`Dual Momentum Investing - Gary Antonacci - 原文.md`
- `STR-08`：`Quantitative Momentum - Gray and Vogel - 原文.md`
- `STR-09`：`The Trend Following Bible - Andrew Abraham - 原文.md`
- `STR-10`：`海龟交易法则 - Curtis Faith - OCR校对版.md`
- `STR-11`：`因子投资方法与实践 - 石川 刘洋溢 连祥斌 - 原文.md`
- `STR-12`：`征服市场的人 - Gregory Zuckerman - 原文.md`
- `PORT-01`：`Active Portfolio Management - Grinold and Kahn - 原文.md`
- `PORT-02`：`Expected Returns - Antti Ilmanen - 原文.md`
- `PORT-03`：`Efficiently Inefficient - Lasse Heje Pedersen - 原文.md`
- `EXE-01`：`Trading and Exchanges - Larry Harris - 原文.md`
- `EXE-02`：`Algorithmic and High-Frequency Trading - Cartea Jaimungal Penalva - 原文.md`

## 已发现来源问题

- `RES-05` 本地文件名仍误称 Shreve Volume I；标题页、原PDF和34章目录已把它重登记为 Chalasani/Jha 整理、Shreve 课程与版权归属的 1997 年讲义。现已完成34/34章`L1`，但不得按 Springer Volume I 引用；公式glyph损伤使`L2/L3`仍待原PDF逐项复核。
- `RES-06` 来源身份通过；完整目录为11章而非8章，已完成11/11章`L1`。原PDF对象流损坏，物理页230出现黑块并跳至Ch07 §7.4.3，Ch07前半、附录和全部公式继续阻塞。

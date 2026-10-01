# 本地量化书库覆盖清单

## 当前状态

- 统计日期：`2026-07-15`
- 书籍总数：`28`
- `L0` 来源登记：`28/28`
- `L1` 章节结构处理：`28/28`
- `L2` 全章节语义精读：`27/28`
- Agent 手册书目反向链接：`28/28`
- 单书完成：`15/28`
- 全库状态：`in_progress_not_complete`

覆盖率分开记录；`L1=100%` 不得解释为全文精读完成。

## 覆盖表

| ID | 书籍 | 来源质量 | 章节数 | L0 | L1 | L2 | 公式复核 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|---|
| `ENG-01` | [A Philosophy of Software Design](cards/ENG-01_a_philosophy_of_software_design.md) | EPUB text + 原EPUB核对 | 21 | 100% | 100% | 100% | Ch02复杂度关系、Ch12成本估算、Ch20历史性能共3项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `ENG-02` | [Architecture Patterns with Python](cards/ENG-02_architecture_patterns_with_python.md) | EPUB text | 13 | 100% | 100% | 100% | 不适用 | `complete_l2_no_quantitative_formula` |
| `ENG-03` | [Designing Data-Intensive Applications](cards/ENG-03_designing_data_intensive_applications.md) | EPUB text + 原EPUB核对 | 12 | 100% | 100% | 100% | 第1—12章各10项，共120项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `ENG-04` | [Database Internals](cards/ENG-04_database_internals.md) | EPUB text + 原EPUB核对 | 14 | 100% | 100% | 100% | 第1—14章各5项，共70项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `ENG-05` | [Working Effectively with Legacy Code](cards/ENG-05_working_effectively_with_legacy_code.md) | EPUB text + 原EPUB核对 | 25 | 100% | 100% | 100% | Ch02测试聚合、Ch06变更成本、Ch07反馈延迟共3项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `RES-01` | [Advances in Financial Machine Learning](cards/RES-01_advances_in_financial_machine_learning.md) | EPUB text + 原EPUB视觉/正文核对 | 22 | 100% | 100% | 100% | 第1章无定量公式；Ch02 50项、Ch03—Ch22各30项，共650项均为`verified_concept_only` | `original_epub_formula_review_complete_concept_only` |
| `RES-02` | [Evidence-Based Technical Analysis](cards/RES-02_evidence_based_technical_analysis.md) | PDF text + 原PDF视觉核对 | 9 | 100% | 100% | 100% | Ch01—Ch09各30项，共270项均由原PDF核为`verified_concept_only`；附录证明已纳入Ch01 | `original_pdf_formula_review_complete_concept_only` |
| `RES-03` | [Analysis of Financial Time Series](cards/RES-03_analysis_of_financial_time_series.md) | PDF text + original PDF | 12 | 100% | 100% | 100% | Ch01—Ch12 各30项，共360项均由原PDF核为 `verified_concept_only` | `original_pdf_formula_review_complete_concept_only` |
| `RES-04` | [Monte Carlo Methods in Financial Engineering](cards/RES-04_monte_carlo_methods_in_financial_engineering.md) | OCR + 原始扫描PDF视觉核对 | 9 | 100% | 100% | 100% | Ch01 10项、Ch02 18项、Ch03 31项、Ch04 14项、Ch05 26项、Ch06 14项、Ch07 28项、Ch08 29项、Ch09 17项、Appendix A 6项、B 12项、C 12项已核为`verified_concept_only`；仅Ch08页421一项`blocked_source_gap` | `chapter_semantic_review_l2_complete_low_confidence_formula_pending` |
| `RES-05` | [Stochastic Calculus and Finance（1997课程讲义）](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md) | PDF text + 原始PDF视觉核对 / 真实讲义已重登记 | 34 | 100% | 100% | 100% | Ch01 37页/30项、Ch02 10页/17项、Ch03 7页/16项、Ch04 10页/19项、Ch05 7页/20项、Ch06 6页/21项、Ch07 5页/14项、Ch08 14页/29项、Ch09 8页/25项、Ch10 4页/17项、Ch11 8页/26项、Ch12 8页/28项、Ch13 13页/35项、Ch14 14页/33项、Ch15 9页/37项、Ch16 11页/40项、Ch17 7页/28项、Ch18 5页/29项、Ch19 5页/28项、Ch20 10页/36项、Ch21 4页/30项、Ch22 9页/52项、Ch23 5页/33项、Ch24 8页/52项、Ch25 16页/83项、Ch26 4页/32项、Ch27 8页/48项、Ch28 9页/67项、Ch29 7页/58项、Ch30 9页/96项、Ch31 16页/142项、Ch32 5页/66项、Ch33 9页/113项、Ch34 13页/124项均为`verified_concept_only` | `original_pdf_formula_review_complete_concept_only` |
| `RES-06` | [Stochastic Calculus for Finance II](cards/RES-06_stochastic_calculus_for_finance_ii_ocr_blocked.md) | OCR + 损坏原始PDF | 11 | 100% | 100% | 91% | Ch01—06、Ch08—11低可信语义L2完成；仅Ch07前半、附录及全部公式受结构性损坏阻塞；570页目录仅存446组Page/Resources，缺124页且不可由149个孤儿条带重建 | `chapter_semantic_review_l2_partial_10of11_low_confidence_ch07_source_structurally_corrupt` |
| `STR-01` | [Systematic Trading](cards/STR-01_systematic_trading.md) | EPUB text + 原EPUB核对 | 15 | 100% | 100% | 100% | 第1—15章各5项，共75项均为`verified_concept_only`；附录B—D已核 | `complete_l2_l3_items_verified_concept_only` |
| `STR-02` | [Following the Trend](cards/STR-02_following_the_trend.md) | EPUB text + 原EPUB核对 | 10 | 100% | 100% | 100% | 第1—10章各5项，共50项均为`verified_concept_only`；1990—2011共22个年度案例已覆盖 | `complete_l2_l3_items_verified_concept_only` |
| `STR-03` | [Advanced Futures Trading Strategies](cards/STR-03_advanced_futures_trading_strategies.md) | PDF text + 原PDF核对 | 34 | 100% | 100% | 100% | S01—S30、T01—T04及Appendix B 11个计算族共45项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-04` | [Trading Systems and Methods](cards/STR-04_trading_systems_and_methods.md) | PDF text + 原PDF书签核对 | 24 | 100% | 100% | 100% | 24章原PDF页码与方法簇结构已核；高密度公式/表格/参数仍待原子化L3 | `chapter_semantic_review_l2_complete_original_pdf_structure_verified_formula_pending` |
| `STR-05` | [Quantitative Trading](cards/STR-05_quantitative_trading.md) | PDF text + 原PDF核对 | 8 | 100% | 100% | 100% | 回测/执行/Kelly/协整/factor/PCA/OU/季节/HFT共27项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-06` | [151 Trading Strategies](cards/STR-06_151_trading_strategies.md) | 修复后 EPUB text + 原EPUB local-header恢复核对 | 20 | 100% | 100% | 100% | Ch01—20、151个正式编号及20个章节级策略族条目均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only_source_recovered` |
| `STR-07` | [Dual Momentum Investing](cards/STR-07_dual_momentum_investing.md) | EPUB text + 原EPUB核对 | 10 | 100% | 100% | 100% | 第1—10章及Appendix B共11项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-08` | [Quantitative Momentum](cards/STR-08_quantitative_momentum.md) | PDF text + 原PDF核对 | 9 | 100% | 100% | 100% | 第1—9章及Appendix A/B共11项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-09` | [The Trend Following Bible](cards/STR-09_the_trend_following_bible.md) | PDF text + 原PDF核对 | 10 | 100% | 100% | 100% | 第1—10章共10项风险/计划/突破/回撤/日志规则均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-10` | [海龟交易法则](cards/STR-10_turtle_trading_rules.md) | OCR校对版 + 原始扫描PDF视觉核对 | 13 | 100% | 100% | 100% | Ch01—13全章L2；公式、图表、历史数字与原版规则附录待逐页L3 | `chapter_semantic_review_l2_complete_low_confidence_formula_blocked` |
| `STR-11` | [因子投资方法与实践](cards/STR-11_factor_investing_methods_and_practice.md) | PDF text + 原PDF核对 | 7 | 100% | 100% | 100% | 方法/模型/异象/实践共36项均为`verified_concept_only` | `complete_l2_l3_items_verified_concept_only` |
| `STR-12` | [征服市场的人](cards/STR-12_the_man_who_solved_the_market.md) | EPUB text | 15 | 100% | 100% | 100% | 不适用（传记，无定量公式） | `complete_l2_no_quantitative_formula` |
| `PORT-01` | [Active Portfolio Management](cards/PORT-01_active_portfolio_management.md) | PDF text + original PDF | 22 | 100% | 100% | 100% | Ch01 3项、Ch02 6项、Ch03 9项、Ch04 5项、Ch05 8项、Ch06 8项、Ch07 7项、Ch08 9项、Ch09 11项、Ch10 10项、Ch11 8项、Ch12 11项、Ch13 10项、Ch14 14项、Ch15 8项、Ch16 12项、Ch17 12项、Ch18 10项、Ch19 10项、Ch20 7项、Ch21 6项、Ch22 4项，共188项均由原PDF核为 `verified_concept_only` | `original_pdf_formula_review_complete_concept_only` |
| `PORT-02` | [Expected Returns](cards/PORT-02_expected_returns.md) | EPUB text + original EPUB | 29 | 100% | 100% | 100% | 29章1038项＋Appendix B 1项，共1039项；Ch01 10项、Ch02 9项、Ch03 10项、Ch04 11项、Ch05 25项共65项已由原EPUB/XHTML/表图核为 `verified_concept_only`，Ch06—Ch29 973项及Appendix B 1项待L3 | `original_epub_ch01_ch05_formula_review_in_progress_concept_only` |
| `PORT-03` | [Efficiently Inefficient](cards/PORT-03_efficiently_inefficient.md) | PDF text | 16 | 100% | 100% | 100% | 全16章491项待L3复核；无分组占位 | `chapter_semantic_review_l2_complete_formula_pending` |
| `EXE-01` | [Trading and Exchanges](cards/EXE-01_trading_and_exchanges.md) | EPUB text | 29 | 100% | 100% | 100% | 第1章18项、第2章25项、第3章30项、第4章22项、第5章30项、第6章21项、第7章28项、第8章30项、第9章30项、第10章23项、第11章30项、第12章30项、第13章30项、第14章29项、第15章30项、第16章24项、第17章36项、第18章30项、第19章23项、第20章20项、第21章39项、第22章35项、第23章24项、第24章30项、第25章26项、第26章34项、第27章26项、第28章30项、第29章30项待L3 | `chapter_semantic_review_l2_complete_formula_pending` |
| `EXE-02` | [Algorithmic and High-Frequency Trading](cards/EXE-02_algorithmic_and_high_frequency_trading.md) | OCR + 原始扫描PDF | 12 | 100% | 100% | 100% | 第1—4章140项低可信待原PDF/当前venue复核；第5—12章原页语义核对完成、各30项公式待验证；附录数学阻塞 | `chapter_semantic_review_l2_complete_formula_pending` |

## 验收规则

- 本表只统计当前实际存在且符合 `knowledge_card_schema.md` 的卡片。
- 未建立标准卡片的旧摘要不计入 `L1` 或 `L2`。
- 后续每完成一本书，必须同步更新本表、公式队列和 Agent 手册反向引用。
- 任何来源文件 SHA-256 变化，相关卡片自动退回 `source_changed_revalidation_required`。

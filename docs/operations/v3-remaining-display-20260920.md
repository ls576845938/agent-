# V3 限定缺证展示修复

## 范围与状态

- 角色 super_developer；change_risk=research_readonly_release。
- 基线/回退参考：ea5d62324caf28fb8087f915ef35e08a2d411a30。
- 票据 V3-REMAINING-DISPLAY-20260920；独立 planner sparse 工作树、初始限定 dirty 为空。
- 仅改 CryptoWorkspace.tsx、StrategyTesterReport.tsx、对应新回归脚本、本报告、派生 frontend-identity.json 与本票据 handoff。
- 账户底部订单/成交/仓位显示复用既有 accountFactsView 的时间与对账条件；未获取、读取失败、无效数量和未对账显示未知。只有有效明确空数组可显示零或空仓。
- 同一文件费用/资金费/审计的缺失不再转换为零。非 USDT 或非有限费用不汇总成 USDT。缺失 depth/native 证明不再由没有 blocker 或仅有成交数推断验证通过。
- 策略测试器两处边界面板保留收到的阻断项，无来源标未知，不再由空列表断言研究完整。
- 未改请求、按钮权限、策略、仓位、退出、风险、OMS、保护、账本、启动器、治理或历史证据；没有生成账户或成交记录。

## 本地验证

- 失败优先：BTC_DISPLAY_TEST_REF=ea5d62324caf28fb8087f915ef35e08a2d411a30 运行新脚本，因旧源码“当前 run 已公开的研究证据完整”断言失败；未改旧基准。
- node frontend/scripts/test-btc-missing-evidence.mjs：实际命名展示函数的 SSR，缺失/错误/未对账/空数组/非法数量/已有仓位/费用/审计/研究边界通过。只 mock 图标，不 mock 展示逻辑。
- node frontend/scripts/test-btc-account-facts-view.mjs：通过。
- node frontend/scripts/test-offline-execution-summary.mjs：通过，精确研究运行关联与历史零成交说明保持。
- node frontend/scripts/test-btc-demo-start-feedback.mjs：通过。
- node frontend/scripts/test-research-read-request.mjs：5 项通过。
- node frontend/scripts/test-research-rollback.mjs：通过。
- frontend npm run build：通过，既有大 bundle 提示，不以本票据扩展性能重构。
- frontend npx tsc --noEmit 与 node node_modules/typescript/bin/tsc --noEmit：均 exit 0。独立集成/正式页面验收结果由后续记录补齐；当前不声称正式发布通过。
- 本次纯展示未重跑策略/后端全仓；历史 test-research-portfolio-contract.mjs 的旧冻结依赖失败不属于本次修改，保留既有报告，不更改预期。

## 治理与安全

已读取预检、交付和证据审查 skills；knowledge README、non-negotiables、shared_pitfalls、super_developer_pitfalls、角色配置和 research_readonly_release 合同。

catalog_hash=6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
命中 GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001。

无他人 dirty 覆盖或未提交文件消费；旧未合入工作树仍保留，不清理。未创建/修改 artifact、manifest 来源或 ledger；派生前端版本清单独立刷新。

独立 integrator 须校验提交态 handoff、文件 hash、完整 diff、源与主版本身份及正式页面。原有 BTC 领域证据 503/注册表冲突不由 UI 消除。历史离线摘要仍绑定真实源版本，不宣称 current-HEAD 运行验证。

promotion、Demo 控制、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 均 false；fixture fallback=false。研究展示不授予交易权限；M3—M4 和其他工程不启动。

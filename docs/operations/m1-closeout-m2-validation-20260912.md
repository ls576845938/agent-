# M1 有限结项与 M2 样本准入：生产者交付

日期：2026-09-12；票据：`M1-CLOSEOUT-M2-VALIDATION-20260912`。

## 结论和范围

M1 的 5 项页面回归失败已复现并修正，旧研究/组合冻结合同已恢复通过；本轮生产者的定向浏览器矩阵为 **27/27**。M2 完成协议登记与元数据准入检查，**未通过新独立样本准入，0 次 fit，无效果结论**。等待独立集成者最终复核；本报告不自批 M1 结项，不声称完整仓库所有测试通过。

- role=`super_developer`；change_risk=`research_readonly_release`。
- base/已运行 main：`2eafaf5220a5527962874e02fc04c1674e379ce8`，本票回退基准也是该提交。
- planner sparse worktree：`agent/super_developer/m1-closeout-m2-validation-20260912`，位于 registered main 同级 `worktrees/`；仅在 planner 实际输出路径写入。
- 本报告形成时 registered main、业务源码、运行服务没有改变。测试驱动已经运行的 canonical main 3000，不在任何 worktree 启动前端。
- 只复用现有依赖，工作树自有 ignored `frontend/node_modules` junction 指向已核对的 canonical node_modules。没有安装、升级依赖、读取秘密或访问交易网络。

## 实际 touch set

1. `frontend/e2e/research-layout.spec.ts`：按确切标题定位原研究来源折叠区，与 M1 环境折叠区分开；同步已经发布的 Factory 折次标题。增加唯一匹配、独立折叠状态检查，保留七层、缺证、版本不匹配、无替代 run、导航、回退、禁止请求等原断言。
2. `frontend/scripts/test-research-portfolio-contract.mjs`：保持原 rollback base `13486a7802628e93dd624213ba6c317c5deb4ddf`，只允许提交 `5a400ebc1...` 的那一个精确 Qlib pipeline helper；负对照拒绝 endpoint 改写、旧方法改名和额外 helper。用 mock 验证导入无提交、副作用仅在显式调用发生、路径和 payload 精确；没有实际 POST。
3. 同一冻结合同在 task-api 失败移除后暴露另一个已存在的 CSS 前缀断言失配：sticky 导航曾在中间插入规则和引入等值 padding 变量。改为逐一比较原 CSS 规则及其 media 上下文，只接受三处已审定的 padding 替换，其他旧声明必须一致，并增加旧标题样式突变拒绝。没有改 CSS 文件，未简单把整个基准移到当前 HEAD。
4. `docs/research/m2-trend-environment-protocol-20260912.md`：固定假设、两臂、特征、模型、预算、成本边界、停止条件与必须预先绑定的输入。
5. `docs/research/m2-trend-environment-input-audit-20260912.json`：提交态元数据准入事实，明确不是 payload 质量证书、不是全系统无 holdout 的断言。
6. 本报告及 `.agent/handoffs/M1-CLOSEOUT-M2-VALIDATION-20260912/` append-only 交付事件。

所有声明路径初始 `safe_status=clean`。没有覆盖、回滚、删除其他工作树；无并行写代理。研究只读探索代理只反馈元数据和源码锚点，没有新数据/模型产物供跨工作树消费。

## 失败优先与本轮验证

命令在专属 worktree 执行，浏览器 baseURL 始终为已核对 source/main `2eafaf52`、canonical=true、runtime_stale=false 的 3000。三份 spec 的业务 `/api/**` 全部 mock；不训练、不 resume、不晋级、不调用交易。

| 检查 | 结果 |
| --- | --- |
| `node frontend/scripts/test-research-portfolio-contract.mjs`，修改前 | FAIL：task-api 比 frozen base 多出既有 `submitQlibPipelineTask` |
| 同合同，首次修正 task-api 后 | FAIL：`Old styles preserved; additions scoped`，原前缀比较已被既有 sticky CSS 插入破坏 |
| Playwright `research-layout.spec.ts --grep 'exact Qlib deep link\|factory detail is readonly\|Qlib URL version hints' --workers=1`，修改前 | **5 failed**：4 个多匹配 selector、1 个旧标题超时 |
| 同冻结合同，最终 | **PASS**，含新增突变负对照；原动作权限/来源/配置/重复提交锁测试全部执行到底 |
| `npx.cmd --no-install playwright test e2e/research-layout.spec.ts e2e/alpha-factory.spec.ts e2e/m1-archive-compat.spec.ts --workers=1 --reporter=line --output=output/playwright/m1-closeout-after`（frontend CWD） | **27 passed / 1.6m**：Research Layout 16、Factory 7、M1 compatibility 4 |
| `node frontend/scripts/test-trend-environment.mjs` | PASS，实际 SSR missing/stale/mismatch/unsafe 与三页复用 |
| `node frontend/scripts/test-m1-archive-compat.mjs` | PASS，精确来源、顺序读、取消与 StrictMode |
| `node frontend/scripts/test-research-rollback.mjs` | PASS，原版回退源未变 |
| `npm.cmd --prefix frontend run lint` | PASS（tsc --noEmit） |
| `git diff --check -- <two test files>` | PASS，仅 LF/CRLF 常规提示 |
| `git diff --exit-code 2eafaf52 -- frontend/src backend quant_crypto quant_shared integrations configs` | PASS，无业务源/模型/执行/配置变更 |

生产者本轮未重跑 25+169 Python 行为矩阵或生产构建：业务代码字节没有变化，相关独立旧证据引用如下；交由本票独立集成复核是否需要定向复跑。不将上轮结果冒称本轮重跑。没有新的真实市场重训、runtime/promotion artifact 或交易端到端测试。

## M1 原定验收矩阵与结项边界

| 原定组 | 可复用的已提交证据 | 本轮关闭的缺口 |
| --- | --- | --- |
| 因果/资产中性 | `m1-trend-environment-review-20260911.md`：25 项环境/sidecar/freeze 测试；当前对应源与已审版本相同 | 不新增算法、数据或资产，不冒称 US/CN 实际市场接入 |
| 兼容/行为保护 | 同报告：169 项 Context/composition/risk/OMS/Guardian/ledger 合同；三态组件对照，不是真实 exchange fill E2E | 旧冻结前端合同恢复通过；不能据此关闭原登记执行安全疑点 |
| 生产者/证据/API | `m1-research-readonly-release-integration-20260912.md`：76 项 API/工厂合同、固定 manifest 全文件 hash、source/stale 严格绑定 | 本轮不重训或改封印；M1 archive compatibility 4/4 保持 |
| 安全/前端 | `m1-archive-compat-canonical-acceptance-20260912.md` 位于已提交 `6f864d452`：真实普通/factory四折/缺证/旧run切换验收 | 原旧页面 5 项断言全部修复、合并矩阵27/27；等待独立本票结项/发布记录 |

M1 工程目标只有“增加历史因果旁路、证据贯通、默认 BTC 行为不变”，不以 alpha 盈利、503消失、所有历史事故修复或真实下单为结项条件。旧架构地图的“M1未启动”是历史快照，不据此继续全仓重构；本报告与后续独立结项事件提供增量状态，不改写原历史记录。

## M2 实际准入与停止

只读审查确认：当前可直接绑定的 OKX 永续 1h 数据已用于普通 Qlib/M1/Factory；当前 profile 和 registry 强制 `previously_observed_audit=True`。其他 Binance spot 新日期或既存 5m 候选锁的保留尾段不能无声替代本轮样本。

因此固定两臂/8-fit 协议后停在 `independent_okx_1h_confirmation_window_not_verified`。没有从测试结果反向挑窗口、没有查看新保留尾段表现、没有运行旧数据 A/B 来充当未见样本，也没有因数据缺口建立另一套评价引擎。独立数据/研究负责人应先提供同市场不可变输入、未见性用途记录和精确日期切分，再审核最小离线编排。M2 效果验收未完成，M3/M4 未启动。

## 证据、权限与治理

- M1 immutable manifest：`.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`；aggregate=`593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`；计算源码仍为 `59f5eb861...`，相对当前代码 stale 如实保留。Factory rejected/0 candidate 不变。
- 本轮无新数据、artifact、manifest、ledger、latest 或 schema 变更，只有测试和文档。BTC runtime artifact root 503、4 类静态安全疑点和其他历史债原样保留，不自动新建修复任务。
- 读取：AGENTS、knowledge README、non-negotiables、shared/super_developer playbook、角色 TOML、research_readonly_release、financial_ml_validation_rules、data_reliability_rules、point_in_time_data，以及 quant preflight/handoff/evidence review 和 Playwright skills。
- catalog=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；active IDs：GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001。未全文读原事故日志。
- Team Context 有 14 个历史 invalid handoff，未扩为本票工作。已引用 M1 三份独立交付在主会话只读复核中 validate=valid；本票提交后再发布独立 append-only envelope。
- `demo_control_enabled=false`；promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed 全 false。保持 `research_readonly`，不触及 secret/private/order/live，不以研究完成授予交易权限。
- 生产者 readiness 上限 `quality_checked`；独立集成、最终用户发布权限/实际 main 状态须由后续事件单独证明。本票不走 Demo fastpath、不更改治理。

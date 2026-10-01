# Research Readonly UI Loading 限定修复验收

- 票据：`RESEARCH-READONLY-UI-LOADING-20260914`
- 角色：`super_developer`
- 分类：`research_readonly_release`
- 基线：`9735b6e46e21c6818c99699bddccdb26bc383e3e`
- 就绪上限：`quality_checked`

## 范围与结果

本票只修复研究台 GET 读取的页面生命周期、在途去重、12 秒截止、来源切换隔离和 Evidence Registry 状态字段显示。没有建立持久缓存，没有延长超时，没有修改 POST 语义、后端、索引、数据、研究模型、BTC 交易或任何权限。

实现边界：

- 相同的 `dataRoot + qlibRoot + portfolioRoot` 只共享当前在途读取；结果一旦完成立即移除，手动刷新仍读取服务。
- React StrictMode 瞬时卸载/重挂在 1ms 释放宽限内复用同一请求；来源离开后取消旧请求。
- 12 秒截止覆盖响应头、正文下载和 JSON 解析。页面区分截止、取消、HTTP、网络和未分类错误；失败不显示成空记录。
- 读取序列与请求 key 同时防止迟到结果串到新 root/run 上。
- 注册表优先使用真实的 `registry_integrity_status` / `registry_status` / `registry_notes`；`CONFLICT` 显示为可读但受阻，有限展示前 3 条并标明总数，不把冲突当成合格或晋级。

## 失败优先与验证

1. 在 helper 存在前运行 `node frontend/scripts/test-research-read-request.mjs`，确认失败为 `ENOENT frontend/src/lib/research-read-request.ts`。这只证明旧实现缺少统一读取生命周期模块，不声称已逐项复现所有旧页面行为。
2. `$env:NODE_PATH='<registered-main>/frontend/node_modules'; node frontend/scripts/test-research-read-request.mjs` → `5/5 passed`。覆盖同源在途去重、StrictMode 重挂复用、旧来源 abort、大 JSON 正文未完成时的 12 秒 deadline/错误分类，以及 `200 + CONFLICT + 57 notes` 状态映射。
3. 使用 registered-main 的已安装 `esbuild` 对 `ResearchPortfolioWorkspace.tsx` 执行 `--bundle --format=esm --packages=external` → 通过，本地 TSX 依赖图完整编译。
4. TypeScript 全项目检查在 producer worktree 因不允许复制/Link `node_modules` 而只到达外部包解析阶段，精确失败为 `react-router-dom` / `@phosphor-icons/react` / `recharts` / `lightweight-charts` 无法从隔离 worktree 解析；未发现本票文件的额外 TS 诊断。这不写成全量 typecheck 通过。
5. `frontend/e2e/research-readonly-loading.spec.ts` 已编写，覆盖 StrictMode 下单次 Registry GET、`CONFLICT / 57 notes` 真实显示、交易锁定和无 POST/private/order。producer 按治理禁止启动非 canonical 页面，故此 E2E 留给独立 integrator 在合入后的 canonical main 执行。

## 停止条件与全局优先级

本票的关闭条件只有四项：`research_readonly` 读取在页面截止内可用、注册表冲突真实可见、来源切换不串数据、所有交易权限继续阻断。独立集成验收达标后冻结研究页面，不再追求更低毫秒数，不把旧测试环境失败、BTC 历史 blocker 或其他页面全绿加入本票。

这项 UI 修复不是 BTC 原策略“账户事实 / 账本恢复 / 只读对账”的全局前置。若 canonical 验收失败，只登记具体的只读页面降级，不自动阻塞独立主线、派生后端票或扩大页面重构。只有风控、账本、private/order/live 自身门禁保持独立 fail-closed。本轮确认后主线回到账户事实、账本恢复和只读对账，不开新因子、模型或页面重构。

## 交付边界

- 未生成或修改 data/artifact/manifest/ledger。
- 未访问 secret、broker、private、order 或 live endpoint。
- 未改变 schema、策略信号、仓位、退出、Risk、OMS、保护单或账本语义。
- `demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 `false`。
- 独立 integrator 仍必须审查 committed diff，运行 canonical main 构建/E2E/真实页面验收，并处理 frontend identity、重启和回退点。producer 不自批、不合入 main。

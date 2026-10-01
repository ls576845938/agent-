# ALPHA-READ-CHAIN-FIX-20261002 交付说明

## 范围与边界

- 基线：`23aab6e5a948dc611e762c3193d3f692b896a314`
- 变更风险：`research_readonly_release`
- 目标：修复 Alpha 工厂页面读取链的重复请求、旧请求不可取消以及旧错误覆盖新状态问题。
- 保留：Alpha 原有 `20_000 ms` 预算，完整 owner/revision/hash/path/seal 校验，以及所有 `research_readonly` 和交易禁用边界。
- 未改：后端校验、候选目录合同、Vite 代理、通用 API 超时、启动器、认证、策略、风控、OMS、账本和任何交易权限。

## 闭合证据与根因

已封闭证据根：

`D:/quantstation-runtime/btc-system-intake-formal-20261001-23aab6e5e`

测量结果：

| 项目 | 结果 |
| --- | ---: |
| 已封闭正式 UI overview GET | `200 / 7603.315 ms`，其中 wait `7596.294 ms` |
| 上轮独审记录的 detail GET（本票未重新解析该条） | 一次 `200 / 15596 ms`，同时请求被取消，页面最终呈现 `timeout after 20000ms` |
| `git worktree list --porcelain` | `6025.4112 ms`，`2691` 行 |
| `git rev-parse HEAD` | `266.416 ms` |
| 外置 catalog SHA-256 | `118.0533 ms` |
| `factory-a` 封存规模 | `5` 个小文件 |

结论：当前外置 catalog 每次完整校验都会读取 Git worktree 元数据。本票的 fresh 本机测量确认该单次命令为 `6.025 s`；`15.596 s` 的 detail 数字来自上轮独审记录，不冒充本票重新独立实测。该校验不能删除或用 stale cache 替代；但 Alpha 前端在 React StrictMode 重放和 overview/detail 同时启动时，会重复、并发地调用同一条完整校验链，形成资源争用。页面只用 `stopped` 布尔值忽略旧结果，没有中止旧 HTTP 请求，且 overview/detail/action 共用一个错误状态，因此旧错误可以覆盖已成功的新读取。

## 修复内容

1. Alpha overview/detail 读取接入现有 `research-read-request` 租约，相同 key 在 StrictMode 重放时共享一次 GET；最后一个消费者释放后中止底层请求。
2. 首次 detail 在同一个已校验 overview 租约结束后发起，避免两条昂贵封存校验链互相争用；已有 overview 时切换 run 不再重读 overview。overview 的等待时间使用单调时钟计入同一个 `20_000 ms` 页面预算，detail 只使用剩余预算，不会串行扩大为近 `40 s`，也不会因系统时钟回拨扩大。
3. 切换 run 会取消旧 detail，并用 sequence 阻止旧结果或错误回写。
4. overview/detail/action 错误状态分离；成功读取只清除对应错误。
5. 只有当本次 detail 确实观察到 `running/queued` 后转为终态，才刷新 overview；已完成历史 run 不会因 detail 读取再触发一次封存校验。
6. overview effect 使用本 effect 的 active/sequence 代际保护；`readOnly` 切换或 StrictMode cleanup 后，旧 abort/catch 不能写入新模式的错误状态。取消尚在等待 overview 的 selected effect 不会发起 detail GET。

## 验证

### 失败优先

修复前新增合同测试失败：

```text
AssertionError: Expected values to be strictly equal
actual: undefined
expected: function
```

失败点是尚不存在 `acquireAlphaFactoryOverview`，证明测试覆盖本次新增的同键合流能力。

独审指出串行化不得把原 `20 s` 页面预算扩大为两段 `20 s`。追加剩余预算合同后，修复前如预期失败：

```text
AssertionError: serialized initial detail must use the remaining Alpha page budget
20000 !== 12345
```

实现后同一测试确认 detail 的 HTTP 超时和租约截止都使用从 selected 读取开始计算的剩余预算。

### 修复后

| 命令 / 检查 | 结果 |
| --- | --- |
| `node frontend/scripts/test-research-read-request.mjs` | `17/17` 通过 |
| Alpha API + read lease 严格 TypeScript 检查 | 通过 |
| `AlphaFactoryConsole.tsx` TypeScript 语法转译 | 通过 |
| `frontend/e2e/alpha-factory.spec.ts` TypeScript 语法转译 | 通过 |
| `git diff --check` | 通过（仅 Git 的 LF/CRLF 提示） |

新增浏览器用例覆盖：StrictMode 重放仅发一次 overview GET，切换 run 取消旧读取，旧错误不能覆盖新 detail，以及离开 Alpha 页面时尚在等待 overview 的 effect 不会追加 detail GET。根据仓库规则，正式 Playwright 必须在合入后、主工作树的提交态前端上执行，因此未在 producer worktree 启动页面或声称 GUI 已验收。

一次完整前端 TypeScript 检查在约 `150 s` 无输出后人工终止，未记为通过。将控制台单文件纳入脱离项目配置的严格类型命令时，会命中既有 `Object.entries(budget)` 的 `unknown >= number` 错误；该行未由本票据修改，本票据只以语法转译检查锁定新代码的语法正确性，正式项目构建由后续独立集成验收执行。

## 交付与未完成项

- producer 仅交付源码候选和追加式 handoff；不合入 main、不重启正式服务、不发布页面。
- 独立 integrator 须核验提交、touch set、测试和 handoff，然后在 `research_readonly` 正式 main 上运行构建与 Alpha 页面 Playwright 验收。
- 正式浏览器验收未通过前，不能宣布“状态读取失败”已完全解除。
- 真实候选 R2 研究仍是单独未完成项；本票据不修改候选质量、准入或交易状态。
- `demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 继续为 `false`。

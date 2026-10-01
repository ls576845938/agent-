# 策略源码首屏、报告来源与真实输出修复

## 范围与根因

- Ticket：STRATEGY-SOURCE-PROVENANCE-02；role=super_developer；base=bbc39bec1449c5ea6947c200be1541988d34db2c。
- change_risk=unclassified，gate_impact=none；一个 planner sparse producer + 一个独立 integrator。独立架构审查 APPROVED，不修改 backend/API，不重建无关 promotion gate。
- 首屏/刷新从历史 catalog 恢复 selection 时没有 canonicalSignalAvailable，源码 effect 把未知当 false 而不发 GET。相同 exact candidate 的真实只读 source API 为 200、canonical=true、3751 字符；点击目录再次选择才偶然恢复。此次改为未知也由 exact-ID 只读 API 决定，明确 false 跳过；409/error 保持不可编辑，提供 retry。ID、完整正文及各 section SHA-256、所有 source safety=false 验证通过后才展示；旧异步响应不能恢复其他候选源码。
- 历史 source.data 实际字段是 exchange、source_interval、decision_interval、bar_4h_start/end，旧 commandbar 查 date_range/timeframe，因此显示未发布。新 UI 正确读取，并区分历史报告代码版本与当前注册源码。
- 原报告 canonical series 的 equity、drawdown、monthly_returns、trades、costs 均为空；历史 adapter 不提供连续 fills/ledger。不能凭总收益或年表重构这些序列。原 K 线则来自另一个本机 OKX 参考端点，不是 Binance 历史研究的输入。

## 实现与职责

- `frontend/src/workspaces/StrategyExplorer.tsx`：修首屏 source 请求、校验、loading/retry/stale-response；历史 provenance、显示区间/来源控件、已有聚合输出、新回测数据绑定说明。旧 runner 请求合同不变。
- `frontend/src/workspaces/crypto/strategy-history-provenance.ts`：未知能力请求规则、exact-ID/source hash/safety、UTC 元数据、仅本地显示区间切片；未发布字段不补值。
- `frontend/src/workspaces/strategy-workbench.css`：只在 strategy-workbench 范围布局，移除固定五行空图占位，来源卡、图表视窗、已发布输出独立滚动；不改共享全局样式。
- `frontend/scripts/test-strategy-history-provenance.mjs`：纯函数及哈希负向回归。
- `frontend/e2e/strategy-source-provenance.spec.ts`：9 项 mock-only UI 回归，使用 canonical main 的 3000 服务；producer 不启动 worktree Vite。
- 本报告及 `.agent/handoffs/STRATEGY-SOURCE-PROVENANCE-02/` append-only 交付；integrator 自有 frontend identity。

## 三种数据语义

1. 历史报告：Binance spot BTCUSDT completed 1h→4h，首个完整决策 bar 为 2024-01-01 03:59:59.999 UTC，最后为 2026-06-28 23:59:59.999 UTC；报告生成 2026-06-30 02:18:57.769234 UTC。180/12 候选总收益98.879381%、年化31.760721%、回撤-12.822698%、Sharpe1.691778、Sortino0.917441。report SHA=e0fed490008cf885c44e378369ffd0336d3bf9eabcae7b98b123c86725ca8026。historical_not_current_head，已参与选参；不是当次新回测。
2. K线视窗：优先该 run 已发布图，否则明确显示本机独立参考行情。来源/UTC开始结束控件只过滤已载入 rows，不能下载、更改收益或补缺失日期。参考图不叠加历史交易标记；现有图层 Donchian=120根，明确为参考通道，非当前策略参数。真实旧页面参考行情为 OKX swap，stale 样本；不会伪称历史 Binance 输入。
3. 新回测：既有版本 runner 请求固定 source=sqlite、BTCUSDT、1h，读取已配置本机库的 binance_spot 行，用户指定 UTC start/end，capital=100000、leverage=1。空 data_version 生成描述性ID而非内容哈希；当前可变库不保证重现旧报告。当前 UI 不伪造可切换的在线 provider。编辑草稿不执行，只有注册源码版本可运行；没有新增回测执行、下载或数据写入。

底部显示真实已发布逐年表现、成本压力、holdout/walk-forward 聚合以及可展开历史交易复核。所有标签保留 research-only/非完整账本语义；部分 series 只展示实际存在的部分，连续曲线仅在对应真实序列存在时显示。缺失完整曲线是原产物缺项，不能把 UI 修复等同补齐历史证据。

## 验证与剩余验收

- failure-first：新增 Node 测试在 helper 尚未实现时 ENOENT，exit 1；实现后 PASS。覆盖未知/false、错误ID/权限/缺失安全字段、伪造SHA、正文/section哈希、UTC时区、非法/反向/空日期、空切片不fallback。
- `node frontend/scripts/test-strategy-history-provenance.mjs`：PASS。
- 独立提交态审查追加纠正：逐项披露 equity/drawdown/monthly_returns/trades/costs 缺项，不因已有曲线而隐藏账本/成本缺口。新增 partial-series 断言 failure-first 得到 TypeError（helper 未实现），实现后重新验证；E2E 同时要求曲线可见与缺项提示。首屏 pending 派生状态避免 effect 前短暂误报不可用。
- 上述纠正后：Node PASS、tsc exit 0、Vite build PASS（5225 modules，13.16s）、9项 E2E discovery PASS、diff check PASS；浏览器执行仍待 canonical 集成。
- `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`：最终源码 PASS，无诊断、exit 0。
- `node node_modules/vite/bin/vite.js build`（producer/frontend）：PASS，5225 modules，56.39s；既有单bundle>500kB提醒。
- `node frontend/node_modules/@playwright/test/cli.js test --config frontend/playwright.config.ts e2e/strategy-source-provenance.spec.ts --list`：9 tests，PASS发现/解析。
- `git diff --check -- <声明路径>`：PASS。
- 待集成至 canonical main 后执行9项新测试+3项已有Alpha热力图回归、1131×975/桌面真实浏览器检查、身份检查。未运行全仓套件，未重跑真实回测、下载、paper/live或promotion artifact。
- 首次 canonical main 79a70d459b 浏览器执行为10 passed / 2 failed（48.8s）。两项失败均为 innerText 捕获换行与默认 textContent 断言口径不同，显示数值未变化；仅在 producer 将两处断言设为 useInnerText:true，与原始采集一致，不修改业务源码。原始失败记录保留于外部本票据 playwright 输出。
- 两项测试纠正后在 canonical 3000 上复跑2 passed（6.6s）。第一次纠正验证误从 producer 根目录运行，现有 fixture 的 cwd='..' 因而找不到 Git；改从 producer/frontend 运行即通过。未启动任何非 main 页面；不同输出目录保留失败记录。
- 真实窄屏另发现长 source_ref 把文件标题状态挤成单字竖排；原短路径 fixture 未覆盖。existing cold-load 测试改真实长路径并要求 filetab 高度<120px，canonical 旧CSS failure-first 为134.234375px。仅在 strategy-workbench 的 max-width:1279px 内改标题块换行，状态独占一行，不改桌面布局与交易逻辑；成功浏览器验收待同票据最终集成。
- Canonical 窗口当前由另一独立 ResearchDashboard 任务使用；等待明确释放后再集成/刷新identity/重启，不能覆盖其工作。

## 治理与安全

- 已读：quant-agent-preflight、quant-agent-handoff、AGENTS、knowledge README、non-negotiables、shared/super_developer pitfalls、角色profile、delivery risk policy、data reliability、backtest evidence contract；computer-use及guidance/confirmations用于真实浏览器验收。
- Catalog SHA：127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c。
- 命中：BACKTEST-COST-001、DATA-US-PIT-001（不涉及broker输入，无新增数据消费）、GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE-001、QSYS-ARTIFACT/BOUNDARY/GATE/LEDGER/SECURITY-001、RESEARCH-HOLDOUT-001、GOV-PROMPT/WINDOWS-001。未全文加载原始事故日志。
- 主树和 producer 声明源码范围初始 dirty_count=0；只修改专属 sparse worktree，唯一 writer，保留其他任务变更；无他人未提交交付消费。依赖通过既有 node_modules junction 复用，不安装/升级共享依赖。
- 历史 artifact root 及所有 manifest/ledger 保持未修改；前轮外部快照仍是历史研究证据，不是本次 current-HEAD promotion evidence。
- Promotion artifact unavailable、gate blocked；promotion、paper、live、private、order、real_order、transfer、withdraw=false。没有 secret、private/order/live调用、broker访问、paper队列或真实订单，无外部 push。

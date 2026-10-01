# 研究只读 Registry / Qlib 读取性能验收

日期：2026-09-14（Asia/Shanghai）  
票据：`RESEARCH-READONLY-REGISTRY-QLIB-PERF-20260914`  
角色：`super_developer`  
风险：`research_readonly_release`  
基线：`1925362a76a5c48476642373c1f26ee7196aafce`

## 结论

本票只优化 Evidence Registry 与 Qlib 的研究只读读取链。没有修改页面、策略、信号、仓位、退出、Risk、OMS、保护单、账本、broker/private transport、权限、数据源、训练参数或治理规则。

在本机现有真实只读数据上，修改后 TestClient 读取为：

- Evidence Registry：HTTP 200，`0.233s`；领域状态仍如实为 `conflict`。
- Qlib 列表：HTTP 200，11 runs，`0.573s`。

两项都低于上一轮页面单项约 12 秒、底层请求 20 秒的等待预算。本票没有发布 main、没有重启正式服务、没有启动 worktree 前端，因此 canonical main 浏览器验收仍待独立集成与限定发布后执行。

## 失败基线与定位

- 旧 Evidence Registry 冷读超过 60 秒仍未返回，按有界测量要求中断自有只读进程。
- 分段扫描显示 `data/manifests/run_*.json` 有 7,971 个文件、约 4,116,608,811 bytes；旧 GET 在得知 path/count 已变化前会解析并 SHA256 这些文件。
- 同一真实 `data` 树仅做一次候选路径 `os.walk`：90 directories、10,012 files、8,533 candidate paths，约 `0.063s`。
- 旧 Qlib 共有 11 runs、223 个 seal 声明文件、21,631,152 bytes；直接完整读取所有 run 约 `4.743s`，旧 TestClient HTTP 列表约 `3.356s`。代码检查确认列表先验证所有 locations 后才应用 `limit`，详情同一请求会重复完整 seal 校验。

## 最小修复

### Evidence Registry

- 显式 rebuild 在现有快照内增加 `evidence_registry_validation_index_v1`，包含 server-owned data root、候选路径集合、已登记证据的 SHA256/size/mtime/ctime 元数据及索引摘要。
- saved GET 先校验索引 schema、摘要、目录边界、候选 path set 和已登记文件元数据；新增/删除先返回 stale，越界或索引损坏返回 conflict，已登记文件元数据变化时仅对变化文件重新 SHA256。
- 旧快照没有验证索引时立即显式 stale；仍返回原 conflict evidence，不触发隐式 rebuild，不读取 4.12 GB manifests，也不把旧快照标成 present。
- 没有引入 TTL 或跨请求可信缓存；新增文件、缺失文件、metadata/content 变化都直接使索引失效。

### Qlib

- 列表先按 run directory mtime 排序并应用 `limit`，只验证将返回的 runs。
- seal 仍逐文件流式 SHA256；decision JSONL 在同一遍流式读取中校验全部 run identity，只保留最多 48 条详情 preview。
- 摘要模式仍校验 seal schema/version、seal identity、目录边界、完整文件 hashes、trace/decision identity 与 sidecar 的 schema/safety/source binding；不读取详情 preview 或深层 observation 投影。
- 详情在一次请求内复用已经完成的 seal 校验，不再二次读取整套 run。
- parquet 行数优先读 metadata；sealed 但 JSON/parquet 语义不可读时显式返回 blocked，且不暴露部分详情。

## 修改后性能与读取量

真实只读 Qlib TestClient，同一进程测量：

| 场景 | 耗时 | 返回 runs | hash calls | hash bytes | decision bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold-default (`limit=20`) | 0.806s | 11 | 222 | 10,150,666 | 11,480,486 |
| hot-default (`limit=20`) | 0.592s | 11 | 222 | 10,150,666 | 11,480,486 |
| bounded (`limit=3`) | 0.148s | 3 | 66 | 2,305,005 | 0 |

真实旧 Registry 快照直接读取两次均约 `0.013s`，SHA256 calls/bytes 均为 0；状态为 `conflict`，notes 同时保留验证索引缺失与既有冲突。4 个并发只读调用在 `0.0651s` 内全部返回 `CONFLICT`，没有写入或共享可变缓存。

同一 sealed Qlib run 的 4 个并发摘要读取在 `0.473s` 内全部返回 `passed`，所有 `execution_permission/runtime_observed/promotion/paper/live/private/order` 仍为 false。

这些数字是本机单次有界测量，会受 OS page cache 影响；发布验收必须重新记录 canonical main 的冷/热 HTTP 与真实浏览器等待。

## 测试证据

- 失败优先新增用例：修改前 `6 failed`；修改后 `6 passed`。
- `tests/api/test_qlib_pipeline.py`：首版 `14 passed in 11.17s`；独立 integrator 随后复现 `run_seal.json.files` 为 truthy string 时泄出 `AttributeError`。Producer 新增失败优先回归（修复前 `1 failed`），补充 files object/key/digest 类型校验后为 `15 passed in 12.71s`。
- Evidence/Qlib 聚焦兼容与安全回归（排除已确认的环境/平台基线项）：`87 passed, 4 deselected in 38.63s`。
- research-readonly 路由/投影/archive：`62 passed, 2 skipped, 1 failed in 40.57s`。唯一失败为既有 Windows UTF-8 stderr 解码问题；2 skip 为 Windows symlink 权限。
- 在未修改的 registered main 精确复跑 4 个排除项：同样 4 failed，分别为 Windows path separator 断言、陈旧锁 PID 平台判定，以及 2 个未安装可选 `pyqlib` 的真实训练用例，不是本票引入。

新增/既有验证覆盖：修改、缺失、候选 path set 变化、索引 digest、越界目录、seal 错版本、seal files 非 object/非法 digest、hash mismatch、decision identity、sealed JSON 损坏、limit 前移、详情单次校验与并发读取。没有用延长 timeout 或静默跳过损坏数据作为修复。

## 未运行与剩余阻塞

- 未安装 `pyqlib`，2 个真实 Qlib 训练测试未通过；本票不安装依赖、不训练。
- 未运行全仓回归、前端 lint/build、Playwright 或 worktree serve；本票没有前端改动，且治理禁止 worktree 前端。
- 未 merge main、未重启 8765/3000、未做 canonical identity/HTTP/browser 发布验收。
- 未重建或改写真实 Evidence Registry、BTC artifact/manifest/read-model、ledger、replay 或 latest pointer。
- 当前 readiness 上限为 `quality_checked`；`research_ready/backtest_ready/promotion_evidence_ready` 均不由本票解锁。
- 仍需独立 integrator 审查提交、逐文件 hash、执行语义不变边界与 handoff，之后再由用户限定授权 main 发布、backend restart 和 canonical main 验收。

安全旗标保持 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。

# Agent Playbooks

规则版本：`agent-governance-v2`

本目录把历史踩坑转成可执行、可筛选、可验证的代理规则。

## 三层结构

- `pitfall_catalog.json`：机器可读的当前有效规则，是任务启动时的默认入口。
- `shared_pitfalls.md` 与角色 playbook：人类可读的稳定操作约束。
- Agent workflow、BTC、美股、A 股原始踩坑日志：追加式事故历史，仅在命中 catalog source、调查事故或补 catalog 时定向读取。

默认禁止每个任务全文加载原始踩坑日志。运行：

```powershell
py -3 tools/agent_governance/context_packet.py --role <role> --scope <scope> --format markdown
```

## 当前代理映射

| 用户侧代理名 | canonical role | 角色规则 |
| --- | --- | --- |
| 架构师 | `architect` | `architect_pitfalls.md` |
| 数据师 | `data_steward` | `data_steward_pitfalls.md` |
| 超级程序员 | `super_developer` | `super_developer_pitfalls.md` |
| BTC 程序员 | `btc_developer` | `btc_developer_pitfalls.md` |
| A 股程序员 | `a_share_developer` | `a_share_developer_pitfalls.md` |
| 研究员 | `researcher` | `researcher_pitfalls.md` |

## 新增踩坑规则

新增 durable rule 时必须同时：

1. 在原始日志记录场景、风险、修复和证据。
2. 在 catalog 分配稳定 ID、roles、scopes、status、source 和 regression test。
3. 若替代旧规则，将旧规则标记为 `superseded` 并填写 `superseded_by`，禁止静默改义。
4. 运行 `tests/agent_governance/`。

## 交付要求

最终回复列出 playbook、命中 pitfall IDs、catalog hash、初始 dirty paths、测试/证据路径，以及仍然 blocked/fail-closed 的 gate。缺少这些字段的交付不能作为 promotion evidence。

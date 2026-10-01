# A-Share Development Pitfall Log

本文件是 A 股开发的追加式事故与踩坑历史。任务默认读取 active catalog 与 `a_share_developer_pitfalls.md`；只有 catalog 命中本文件条目或调查历史问题时才定向读取。

## 2026-07-13 A 股领域不能复用美股交易语义

### 场景

新增 A 股开发代理时，现有代码与治理角色只区分 BTC 和美股，容易把 A 股实现继续放进 `quant_us`，并默认继承美股交易时段、可卖数量、价格限制、整手、费用和结算假设。

### 风险

研究与回测可能在接口层看似通过，但成交可行性、持仓可卖性、成本和账本均与目标市场不一致；后续很难区分共享能力与市场专用规则。

### 固化规则

- 使用独立 `a_share_developer` 角色和 `cn_equity` domain/scope。
- A 股专用行为进入明确的领域命名空间；共享合同只能通过集成票据修改。
- 市场规则必须按来源和生效日期版本化，缺失时 fail-closed。

### 回归证据

- `tests/agent_governance/test_context_packet.py`
- `tests/agent_governance/test_handoff.py`
- `tests/agent_governance/test_governance_contract.py`

## 2026-07-13 A 股历史状态不能按当前状态回填

### 场景

universe、指数成分、ST/风险警示、停复牌、上市退市和公司行动经常只有当前快照，容易被直接用于历史回测。

### 风险

产生幸存者偏差、未来成分股、未来状态和未来复权信息泄漏，使回测收益与可执行性失真。

### 固化规则

- 所有状态记录 event time、available time、source version 和生效区间。
- 缺少 PIT 证据的数据只能标记 research-only / blocked。
- 复权价格不能替代公司行动可见时间和现金流账本。

### 回归证据

- `tests/agent_governance/test_context_packet.py`
- `tests/agent_governance/test_governance_contract.py`

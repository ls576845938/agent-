export type MindMapNodeStatus = 'source_mapped' | 'planned';

export type MindMapNode = {
  id: string;
  label: string;
  detail: string;
  moduleId: string;
  status: MindMapNodeStatus;
  testId?: string;
};

export type MindMapBranch = {
  id: string;
  label: string;
  detail: string;
  color: string;
  side: 'left' | 'right';
  y: number;
  nodes: MindMapNode[];
};

export type ArchitectureMindMap = {
  schemaVersion: string;
  title: string;
  subtitle: string;
  canvas: {width: number; height: number};
  root: {label: string; detail: string};
  branches: MindMapBranch[];
};

// A versioned assessment, not a live status feed or a replacement for catalog.json.
export const currentDevelopmentStatus = {
  schemaVersion: 'architecture_development_status_v1',
  asOf: '2026-09-29',
  reviewedHead: '3fc39879d14ecab2288368afe588385cc44c08e1',
  boundary: '这是提交态开发进度快照，不是实时权限、账户或运行监控；历史测试、合入和页面验收不会自动授予交易权限。',
  rows: [
    {
      id: 'v0-v3-closeout',
      label: 'V0—V3 冻结离线工程',
      implementation: '原 Donchian 与固定 Qlib 分别接入同一 BTC 风控／OMS／保护／账本链，冻结范围已限定结项。',
      historicalTests: 'Donchian 五阶段 5 次决策、4 笔模拟成交；旧固定 Qlib 1,392 次决策、0 笔成交。',
      publication: 'e2e7496 已完成 research_readonly 正式页面验收；最终回执为 78aaa489… 的 V3 结项记录。',
      runtimeLimit: '只证明离线软件与只读关联；不是 Demo、paper、live 或真实账户验收。',
      evidence: '78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json',
    },
    {
      id: 'donchian-history',
      label: 'Donchian 长历史与阶段基线',
      implementation: '长窗口回放、历史时钟、保护时序和离线性能改动已随 441e057e2 合入 main。',
      historicalTests: '历史能力集成记录 316 passed / 1 skip；另有新身份 800 事件、3 fills 的工程验证。自然历史阶段完成 2960 / 8760 小时、56 笔模拟成交、28 个 roundtrip、370 笔 funding。',
      publication: '阶段 selector donchian-stage-20260921 已发布，只读页面保留计算源 897d5e99… 与页面发布版本的区别。',
      runtimeLimit: '年度评估暂停；阶段结果不是全年结论、盈利确认或交易所成交。',
      evidence: 'docs/operations/donchian-history-main-integration-20260922.md',
    },
    {
      id: 'registered-candidate',
      label: '标准策略包与登记候选离线入口',
      implementation: '策略包 v3 可验证、人工审定、USDT 币种绑定并登记；默认 bootstrap／CLI／HTTP／coordinator 可按精确登记身份进入原 BTC 离线权威链。',
      historicalTests: '包损坏、币种／账户／版本错配继续拒绝；no_simulated_fills 与 research_admission_not_proven 仅允许隔离诊断。',
      publication: '8821b04e5 与 8ea90775b 已在 main；offlineRun 结果按精确身份关联只读详情。',
      runtimeLimit: 'worker 仅支持 factory_lgbm_ast_v1，默认 candidate_offline_enabled=false；旧 M1 v2 可管理诊断但不由该 worker 执行。',
      evidence: 'docs/acceptance/btc-candidate-offline-entry-20260925.md',
    },
    {
      id: 'market-environment-v2',
      label: '市场状态 v2 与 entry-only 条件政策',
      implementation: '多尺度状态合同、历史诊断与 72h 效率阈值 0.20 的 entry-only 消费已实现；默认关闭，只影响空仓新增风险。',
      historicalTests: '历史诊断 2960 bars／28 roundtrips／170 segments；A/B baseline 2960 / 2960，conditioned 1956 / 2960 后因保护双触碰歧义 fail-closed。',
      publication: '冻结计算源 f2455bf… 已进入 main 的综合验收链；页面只展示 consumer_phase/partial 与 null + missing_fields。',
      runtimeLimit: 'conditioned 保留 -0.01 张空头，完整增量效果未成立；已有仓位退出／减仓／保护不受开仓过滤阻断，M3—M4 未启动。',
      evidence: 'docs/acceptance/integrate-candidate-market-policy-closeout-20260927.md',
    },
    {
      id: 'research-read-performance',
      label: '研究注册表与 Qlib 只读读取',
      implementation: '注册表元数据扫描复用与 Qlib 并发完整校验合并已发布，未增加页面超时。',
      historicalTests: '正式矩阵 11 / 11 场景通过，每场 12 项读取均在 12 秒内完成；最慢 8.293 秒，最终定向回归 40 passed。',
      publication: '当前 main 3fc39879 已在 canonical research_readonly 页面验收。',
      runtimeLimit: 'CONFLICT、BTC 运行证据 503／runtime root 缺失及 Qlib source-context 警告继续如实显示；不是交易就绪。',
      evidence: 'D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/deployment-acceptance-report-3fc39879.md',
    },
  ],
} as const;

export const strategyDeliveryStatus = {
  asOf: '2026-09-29',
  reviewedHead: '3fc39879d14ecab2288368afe588385cc44c08e1',
  reviewedSource: 'aca55c90d82b327800e473774e22dbbeac69bd90',
  closeoutSourceHead: 'e024f42468f4d0a7c39b83fe28ed86c5688459aa',
  overallComplete: true,
  runtimeObserved: false,
  tradingAuthorized: false,
  historicalStageSourceHead: '897d5e99ebe4c898f71ac66cf33fb2d2420855d5',
  historicalStageRunId: 'donchian-effective-time-20250901-20260901',
  conclusion: '冻结范围 V0—V3 离线工程已限定结项；原 Donchian 自然历史阶段另行核账通过、全年暂停。',
  boundary: 'V0—V3 是策略统一接入工程，不是 M3—M4。技术验证、页面发布、整体结项分别记录；研究与离线模拟不授予交易权限。',
  reportPath: 'docs/architecture/system-code-map/STRATEGY-DELIVERY-STATUS-20260920.md',
  stages: [
    {
      id: 'V0', label: '冻结与准入', status: '基准已冻结',
      implementation: '原 Donchian 行为、固定 Qlib 模型、参数、单位和比较合同已固定。',
      verification: '历史验收 219 项通过；不将旧研究回测口径当作运行基准。',
      publication: '已纳入当前代码。候选完整性不等于有效性，也不等于交易授权。',
      evidence: 'docs/architecture/strategy-admission-v0.md',
    },
    {
      id: 'V1', label: 'Donchian 离线闭环', status: '限定场景已验证',
      implementation: '复用原信号与固定合约规则，经原 BTC 风控、OMS、保护和持久账本。',
      verification: '独审 11 项 V1 用例通过，覆盖原规则下的交易阶段、重复、恢复和精确证据；不是实盘验收。',
      publication: '五阶段非零模拟证据和自然历史阶段 selector 均已发布；长历史执行能力已随 441e057e2 合入 main。',
      evidence: 'docs/operations/btc-protection-parent-join-independent-review-20260915.md',
    },
    {
      id: 'V2', label: '固定 Qlib 接入', status: '推理一致性已验证',
      implementation: '封存模型、13 个特征及原校准可复现；候选仓位与退出已接入同一 BTC 离线链。',
      verification: '推理独审 28 项、关联兼容 4 项通过；不重训、不搜索，不给不合格预测补造质量。',
      publication: '当前固定候选被正确阻断；另有策略包 v3／factory_lgbm_ast_v1 的标准化离线 worker，但默认关闭且不支持旧 M1 v2。',
      evidence: 'docs/operations/strategy-v2-frozen-qlib-independent-review-20260915.md',
    },
    {
      id: 'V3', label: '验收与限定发布', status: '冻结离线范围已结项',
      implementation: '事件顺序及恢复修复已有独审；五阶段 Donchian 提交态只读关联已进入主版本，自然历史阶段 selector 也已另行核账并发布。',
      verification: '集中回归为 51 通过 / 1 失败（测试中版本移动）；固定版本独审 5 项通过，含该失败项。不是一次 52/52。',
      publication: '主版本 e2e7496 的 canonical research_readonly 页面已验收 Qlib／Donchian 精确切换；固定 Qlib 两次共 1,392 次决策、0 笔成交；Donchian 五阶段为 5 决策、4 笔模拟成交。不代表真实交易。',
      evidence: '78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json',
    },
  ],
  paths: [
    {label: 'Donchian', detail: '原方向信号 → 原固定合约／退出 → BTC 权威链 → 模拟成交／持久账本'},
    {label: '固定 Qlib', detail: '原特征／固定预测 → 原校准／仓位／退出 → 同一 BTC 权威链 → 模拟成交／持久账本'},
    {label: '自然历史阶段', detail: '冻结旧源码 897d5e99 的 2960 / 8760 小时暂停快照；56 笔模拟成交经只读核账，非全年、非实盘'},
  ],
  remaining: [
    '策略包 v3 的候选离线 worker 只支持 factory_lgbm_ast_v1，默认关闭；旧 M1 v2 仍只可管理诊断。',
    '市场条件 A/B 的 conditioned 臂在 1956 / 2960 fail-closed，不能据此宣称完整增量；V0—V3 结项不自动启动 M3—M4。',
  ],
  nonBlockers: '生产 BTC 证据 503、未完成真实账户验收、固定候选零成交，不作为冻结离线 V3 结项的前置；也不作为真实交易准入。',
  nextStep: '后续若启用候选离线 worker 或继续市场政策确认，必须单独冻结输入与验收；不重开 V3，不自动启动 Demo／paper／live 或 M3—M4。',
} as const;

export const architectureMilestoneStatus = {
  schemaVersion: 'architecture_milestone_status_v3',
  asOf: '2026-09-29',
  sourceHead: '3fc39879d14ecab2288368afe588385cc44c08e1',
  evidence: [
    {
      label: 'V0—V3 限定结项',
      path: '78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json',
    },
    {
      label: '候选离线入口与恢复',
      path: 'docs/acceptance/btc-candidate-offline-entry-20260925.md',
    },
    {
      label: '市场条件政策综合验收',
      path: 'docs/acceptance/integrate-candidate-market-policy-closeout-20260927.md',
    },
    {
      label: '研究只读读取正式验收',
      path: 'D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/deployment-acceptance-report-3fc39879.md',
    },
  ],
  rows: [
    {
      id: 'm1-environment',
      label: 'M1／市场状态 v2',
      implementation: '资产中性旁路及 entry-only 条件政策已实现；政策默认关闭。',
      tests: '2960 bars／28 roundtrips／170 segments；A/B 条件臂在 1956 / 2960 fail-closed。',
      runtime: '只证明历史诊断与受控消费边界，完整增量效果未成立。',
      trading: '不授予信号、仓位、Risk、OMS、paper 或 live 权限。',
    },
    {
      id: 'm2-historical-ab',
      label: 'M2 历史 A/B',
      implementation: '旧 M2 的 8/8 冻结探索已完成。',
      tests: '旧特征 A/B 没有稳定增量；新条件政策 A/B 也未完成两臂对齐。',
      runtime: '旧 M2 与新 entry-only 条件政策是不同验证问题，均未获得交易晋级。',
      trading: 'M3—M4 未启动；交易权限保持 false。',
    },
    {
      id: 'btc-candidate-offline',
      label: 'BTC 登记候选离线入口',
      implementation: '包验证、审定、币种绑定、登记及 factory_lgbm_ast_v1 worker 已接通原离线权威链。',
      tests: '错误包／账户／币种／版本拒绝，重复与恢复不重单、不重账。',
      runtime: '默认关闭；research_readonly 不允许写，旧 M1 v2 不由此 worker 执行。',
      trading: '离线诊断不是 Demo 或交易授权；所有交易权限保持 false。',
    },
    {
      id: 'research-read-performance',
      label: '研究读模型性能',
      implementation: '注册表与 Qlib 只读请求链已在 3fc39879 发布。',
      tests: '正式 11 / 11 场景通过，12 秒预算不变，最慢 8.293 秒；40 项定向回归通过。',
      runtime: 'CONFLICT、BTC 503 和 source-context 限制继续显示。',
      trading: '仅 research_readonly 页面验收，不改变任何运行或交易权限。',
    },
  ],
} as const;

// MINDMAP_DATA_START
export const architectureMindMap = {
  "schemaVersion": "architecture_mindmap_v1",
  "title": "QuantStation 全系统架构",
  "subtitle": "职责结构与源码证据入口",
  "canvas": {"width": 1420, "height": 920},
  "root": {
    "label": "QuantStation 共享平台",
    "detail": "共享研究底座 + 分市场执行域 + 版本化证据"
  },
  "branches": [
    {
      "id": "market-inputs",
      "label": "数据与市场输入",
      "detail": "数据版本、PIT、特征与受控导入",
      "color": "#49a6d8",
      "side": "left",
      "y": 145,
      "nodes": [
        {"id": "market-data", "label": "市场数据 / PIT", "detail": "来源、清洗、时间可见性", "moduleId": "data", "status": "source_mapped"},
        {"id": "factor-inputs", "label": "通用因子引擎", "detail": "公式、计算、横截面评价", "moduleId": "factor_engine", "status": "source_mapped"},
        {"id": "operation-entry", "label": "导入与操作入口", "detail": "账户 baseline / bills 入口已发布；真实账户验收仍未执行", "moduleId": "operation_scripts", "status": "source_mapped"},
        {"id": "data-contracts", "label": "数据 / 证据合同", "detail": "格式合格不等于内容真实", "moduleId": "evidence_schemas", "status": "source_mapped"}
      ]
    },
    {
      "id": "decision-layers",
      "label": "七层决策职责",
      "detail": "职责序列，不等于同一 runtime 已全部贯通",
      "color": "#d9a441",
      "side": "left",
      "y": 455,
      "nodes": [
        {"id": "layer-alpha", "label": "1 · Alpha", "detail": "生成预测或研究候选", "moduleId": "alpha", "status": "source_mapped"},
        {"id": "layer-environment", "label": "2 · 市场环境", "detail": "市场状态 v2 已实现；entry-only 政策默认关闭，完整 A/B 未通过", "moduleId": "forecast", "status": "source_mapped"},
        {"id": "layer-risk", "label": "3 · 风险", "detail": "硬约束与权限判断", "moduleId": "btc_decision", "status": "source_mapped"},
        {"id": "layer-portfolio", "label": "4 · 组合优化", "detail": "多条路径并存，尚非统一优化器", "moduleId": "us_decision", "status": "source_mapped"},
        {"id": "layer-position", "label": "5 · 仓位管理", "detail": "目标仓位与实际装配分开核验", "moduleId": "btc_decision", "status": "source_mapped"},
        {"id": "layer-exit", "label": "6 · 退出 / 保护", "detail": "策略退出、硬减仓、保护单分责", "moduleId": "btc_oms", "status": "source_mapped"},
        {"id": "layer-execution", "label": "7 · 执行 / 账本", "detail": "成交、持仓、现金与 PnL 权威链", "moduleId": "btc_oms", "status": "source_mapped"}
      ]
    },
    {
      "id": "evidence-governance",
      "label": "证据与安全治理",
      "detail": "版本、审计、门禁和可恢复交付",
      "color": "#ad83df",
      "side": "left",
      "y": 765,
      "nodes": [
        {"id": "strategy-context", "label": "共享策略上下文", "detail": "上下文 + 版本化决策证据；不替代领域账本", "moduleId": "context", "status": "source_mapped", "testId": "atlas-node-context"},
        {"id": "permission-evidence", "label": "权限与证据", "detail": "研究完成不授予交易权限", "moduleId": "permissions", "status": "source_mapped"},
        {"id": "quality-system", "label": "测试 / 脚本", "detail": "测试通过与运行验收分开", "moduleId": "quality", "status": "source_mapped"},
        {"id": "governance", "label": "协作治理", "detail": "worktree、handoff、单写者", "moduleId": "governance_tools", "status": "source_mapped"},
        {"id": "monitoring", "label": "监控与报告", "detail": "状态字段不替代 gate 证据", "moduleId": "us_monitoring", "status": "source_mapped"},
        {"id": "historical-cli", "label": "历史 CLI / 兼容", "detail": "演示、研究与真实运行隔离", "moduleId": "us_cli", "status": "source_mapped"},
        {"id": "legacy-code", "label": "历史与其余代码", "detail": "有消费者前不按目录名删除", "moduleId": "legacy", "status": "source_mapped"}
      ]
    },
    {
      "id": "shared-research",
      "label": "共享 Alpha / Qlib 研究",
      "detail": "共享引擎按市场注入数据与规则",
      "color": "#57b88b",
      "side": "right",
      "y": 145,
      "nodes": [
        {"id": "alpha-factory", "label": "共享 Alpha 工厂", "detail": "生成、训练、筛选、审计与完整策略包来源", "moduleId": "alpha", "status": "source_mapped"},
        {"id": "strategy-package", "label": "策略包 v3 / 管理目录", "detail": "验证、审定、USDT 绑定与登记；登记不自动启动", "moduleId": "context", "status": "source_mapped"},
        {"id": "qlib-adapter", "label": "Qlib 研究 / 固定推理", "detail": "旧固定候选与 factory_lgbm_ast_v1 能力分开", "moduleId": "qlib", "status": "source_mapped"},
        {"id": "btc-research", "label": "BTC 趋势研究", "detail": "候选研究与阶段历史模拟分开；Donchian 2960 / 8760 小时暂停，全年未完成", "moduleId": "btc_research", "status": "source_mapped"},
        {"id": "research-registry", "label": "研究服务 / 注册表", "detail": "3fc39879 读取链 11 / 11 正式场景通过；CONFLICT 保留", "moduleId": "research_api", "status": "source_mapped"},
        {"id": "legacy-audit", "label": "内嵌研究审计器", "detail": "文本评级不是交易晋级", "moduleId": "legacy_audit", "status": "source_mapped"}
      ]
    },
    {
      "id": "execution-domains",
      "label": "BTC / US / CN 执行域",
      "detail": "共享合同下保持市场规则与执行隔离",
      "color": "#e07070",
      "side": "right",
      "y": 455,
      "nodes": [
        {"id": "btc-composition", "label": "BTC 原权威链 / 离线复用", "detail": "Donchian / 固定 Qlib 分别验证；非真实运行", "moduleId": "btc_runtime", "status": "source_mapped"},
        {"id": "candidate-worker", "label": "登记候选离线 worker", "detail": "仅 factory_lgbm_ast_v1；默认关闭，按精确登记身份恢复", "moduleId": "btc_runtime", "status": "source_mapped"},
        {"id": "btc-authority", "label": "BTC OMS / 保护 / 账本", "detail": "BTC 交易执行的权威链路", "moduleId": "btc_oms", "status": "source_mapped", "testId": "atlas-node-btc_oms"},
        {"id": "us-domain", "label": "美股执行域", "detail": "回测、受控运行与 IBKR 边界", "moduleId": "us_runtime", "status": "source_mapped"},
        {"id": "cn-domain", "label": "A 股执行域", "detail": "市场规则与独立执行实现", "moduleId": "cn", "status": "source_mapped"},
        {"id": "execution-permission", "label": "共享权限门", "detail": "所有订单路径保持 fail-closed", "moduleId": "permissions", "status": "source_mapped"}
      ]
    },
    {
      "id": "frontend-services",
      "label": "前端与服务",
      "detail": "运行事实、研究证据与机制说明分开展示",
      "color": "#6f91e8",
      "side": "right",
      "y": 765,
      "nodes": [
        {"id": "workbench", "label": "统一前端工作台", "detail": "研究、组合、策略与执行安全", "moduleId": "frontend", "status": "source_mapped"},
        {"id": "backend-readmodels", "label": "后端服务 / 读模型", "detail": "Qlib、Donchian、候选与市场状态小投影已发布；读取不补算", "moduleId": "backend", "status": "source_mapped"},
        {"id": "frontend-research", "label": "研究动作入口", "detail": "API 可读不代表研究或交易就绪", "moduleId": "research_api", "status": "source_mapped"}
      ]
    }
  ]
} as const satisfies ArchitectureMindMap;
// MINDMAP_DATA_END

export const mindMapNodeCount = architectureMindMap.branches.reduce((count, branch) => count + branch.nodes.length, 0);

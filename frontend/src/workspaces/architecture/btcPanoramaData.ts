export type BtcPanoramaNode = {
  id: string;
  title: string;
  detail: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type BtcPanoramaGroup = {
  id: string;
  title: string;
  x: number;
  y: number;
  width: number;
  height: number;
  nodes: readonly BtcPanoramaNode[];
};

export type BtcPanoramaEdge = {
  id: string;
  from: string;
  to: string;
  style: 'solid' | 'dashed';
  label?: string;
  labelX?: number;
  labelY?: number;
  route?: 'direct' | 'left' | 'right';
  both?: boolean;
};

export type BtcSystemPanorama = {
  schemaVersion: string;
  asOf: string;
  sourceHead: string;
  canvas: {width: number; height: number};
  groups: readonly BtcPanoramaGroup[];
  edges: readonly BtcPanoramaEdge[];
};

// Keep this block valid JSON so the static contract test can verify the complete snapshot.
// BTC_PANORAMA_DATA_START
export const btcSystemPanorama: BtcSystemPanorama = {
  "schemaVersion": "btc_system_panorama_v1",
  "asOf": "2026-09-29",
  "sourceHead": "5542a542459f2b56eaf11035fca409422142471d",
  "canvas": {"width": 2500, "height": 2780},
  "groups": [
    {
      "id": "data",
      "title": "A．数据与事实输入",
      "x": 35, "y": 30, "width": 2430, "height": 245,
      "nodes": [
        {"id": "okx-history", "title": "OKX 历史行情、资金费", "detail": "BTC-USDT-SWAP 历史数据来源", "x": 95, "y": 90, "width": 430, "height": 130},
        {"id": "dataset", "title": "版本化数据集", "detail": "Manifest / Hash / UTC / 已完成 K 线\n可见时间、质量检查、预热区间", "x": 685, "y": 90, "width": 500, "height": 130},
        {"id": "public-market", "title": "OKX 公共实时行情", "detail": "K 线、报价、盘口", "x": 1375, "y": 90, "width": 430, "height": 130},
        {"id": "account-facts", "title": "账户事实输入", "detail": "离线：明确的模拟账户\n交易所账户：独立授权与核验", "x": 1975, "y": 90, "width": 430, "height": 130}
      ]
    },
    {
      "id": "research",
      "title": "B．共享研究基础设施：服务 BTC，不另建研究平台",
      "x": 35, "y": 330, "width": 2430, "height": 245,
      "nodes": [
        {"id": "factor-ast", "title": "基础因子、公式与遗传 AST", "detail": "因果计算、评价、去相关", "x": 95, "y": 390, "width": 430, "height": 130},
        {"id": "alpha-factory", "title": "Alpha 工厂", "detail": "有界搜索、分折训练、筛选与最终审计", "x": 685, "y": 390, "width": 430, "height": 130},
        {"id": "qlib-training", "title": "Qlib / LightGBM", "detail": "特征、训练、预测、研究指标", "x": 1280, "y": 390, "width": 430, "height": 130},
        {"id": "sealed-research", "title": "不可变研究产物", "detail": "模型、特征、预测、质量与来源证据\n研究完成不等于交易有效", "x": 1875, "y": 390, "width": 500, "height": 130}
      ]
    },
    {
      "id": "market",
      "title": "C．② 市场状态：描述、诊断与有限政策",
      "x": 35, "y": 630, "width": 2430, "height": 245,
      "nodes": [
        {"id": "market-m1", "title": "M1 环境旁路", "detail": "趋势、效率、波动、冲击\n只追加研究观测", "x": 95, "y": 690, "width": 430, "height": 130},
        {"id": "market-v2", "title": "市场状态 v2", "detail": "24 / 72 / 168 小时因果状态", "x": 685, "y": 690, "width": 430, "height": 130},
        {"id": "market-diagnostics", "title": "状态分组诊断与政策对照", "detail": "已有历史诊断\n完整条件政策对照仍受阻", "x": 1280, "y": 690, "width": 430, "height": 130},
        {"id": "market-entry-policy", "title": "冻结的 Donchian 开仓条件政策", "detail": "默认关闭；显式启用才使用\n仅空仓新增风险，不接管已有仓位退出", "x": 1875, "y": 690, "width": 500, "height": 130}
      ]
    },
    {
      "id": "delivery",
      "title": "D．策略交付与管理：不是交易权限",
      "x": 35, "y": 930, "width": 2430, "height": 245,
      "nodes": [
        {"id": "package-validation", "title": "完整策略包校验", "detail": "模型、特征、预处理、校准\n仓位、退出、成本、时间、状态版本", "x": 95, "y": 990, "width": 500, "height": 130},
        {"id": "registration", "title": "人工审定、账户与 USDT 币种绑定", "detail": "登记 / 撤销 / 精确版本解析\n管理记录不承担经济记账", "x": 735, "y": 990, "width": 500, "height": 130},
        {"id": "offline-job", "title": "显式离线任务入口", "detail": "HTTP / CLI / Coordinator\n登记 ID、输入、账户、版本固定", "x": 1375, "y": 990, "width": 430, "height": 130},
        {"id": "offline-disabled", "title": "当前部署边界", "detail": "离线任务未配置、未启用\n不是登记后自动运行", "x": 1975, "y": 990, "width": 430, "height": 130}
      ]
    },
    {
      "id": "decision",
      "title": "E．① Alpha → ④⑤ 仓位政策 → ⑥ 策略退出",
      "x": 35, "y": 1230, "width": 2430, "height": 245,
      "nodes": [
        {"id": "donchian", "title": "原注册 Donchian", "detail": "调用原 signal_callable", "x": 70, "y": 1290, "width": 340, "height": 130},
        {"id": "donchian-policy", "title": "方向信号＋原固定合约目标", "detail": "原多周期、通道 / 跟踪退出与冷却", "x": 470, "y": 1290, "width": 340, "height": 130},
        {"id": "legacy-qlib", "title": "既有固定 Qlib 候选适配", "detail": "独立的冻结合同", "x": 870, "y": 1290, "width": 340, "height": 130},
        {"id": "registered-inference", "title": "新登记候选固定推理", "detail": "factory_lgbm_ast_v1\n可见行情 → 因子 AST → 预处理 → 模型", "x": 1270, "y": 1290, "width": 340, "height": 130},
        {"id": "candidate-policy", "title": "带单位与期限的 BTCForecast", "detail": "候选自身校准、仓位与退出政策\n运行时不训练、不搜参", "x": 1670, "y": 1290, "width": 340, "height": 130},
        {"id": "target", "title": "目标与交易动作分离", "detail": "目标＋当前持仓 → 本次订单计划\nBTC 数量 / 合约张数 / 精度显式转换", "x": 2070, "y": 1290, "width": 340, "height": 130}
      ]
    },
    {
      "id": "authority",
      "title": "F．现有 BTC 执行权威链：所有策略复用",
      "x": 35, "y": 1530, "width": 2430, "height": 245,
      "nodes": [
        {"id": "risk", "title": "③ T2 风险＋T3 组合决策", "detail": "敞口、成本、保证金、可执行性\n减仓计划与反向先平约束", "x": 95, "y": 1590, "width": 500, "height": 130},
        {"id": "guardian", "title": "③ Runtime Guardian", "detail": "回撤、账户事实、连接与保护状态\n异常阻断与锁存", "x": 735, "y": 1590, "width": 430, "height": 130},
        {"id": "oms", "title": "⑦ OMS 与保护计划", "detail": "订单生命周期、幂等、OCO 归属\n先持久化意图，再允许提交", "x": 1330, "y": 1590, "width": 430, "height": 130},
        {"id": "dispatcher", "title": "权限校验＋Dispatcher", "detail": "版本、账户、会话、时钟与能力核验\n策略不能直接调用交易所", "x": 1950, "y": 1590, "width": 455, "height": 130}
      ]
    },
    {
      "id": "environment",
      "title": "G．执行环境隔离：共享核心，不混用成交事实",
      "x": 35, "y": 1830, "width": 2430, "height": 245,
      "nodes": [
        {"id": "offline", "title": "离线执行适配器", "detail": "历史时钟、行情、模拟账户和成交\n费用、资金费与明确的成交假设", "x": 95, "y": 1890, "width": 500, "height": 130},
        {"id": "demo", "title": "OKX Demo 运行适配", "detail": "代码路径存在，当前未启用\n不代表 paper / live 已获授权", "x": 735, "y": 1890, "width": 430, "height": 130},
        {"id": "protection", "title": "⑥ 保护单触发分支", "detail": "生效时间＋归属＋后续行情\n路径歧义时阻断，不选有利顺序", "x": 1330, "y": 1890, "width": 430, "height": 130},
        {"id": "events", "title": "订单、成交、仓位与资金事件", "detail": "唯一事件身份与来源\n保护成交不是新策略信号", "x": 1925, "y": 1890, "width": 480, "height": 130}
      ]
    },
    {
      "id": "ledger",
      "title": "H．⑦ 持久账本、恢复与核账",
      "x": 35, "y": 2130, "width": 2430, "height": 245,
      "nodes": [
        {"id": "ledger-uow", "title": "原 BTC Ledger / Runtime Store", "detail": "订单、成交、仓位、现金、资金流水\n持久提交与一致性核验", "x": 245, "y": 2190, "width": 500, "height": 130},
        {"id": "recovery", "title": "单写者＋日志哈希链＋检查点", "detail": "精确恢复、重复事件 / 成交去重\n状态不明时冻结，不盲目重单", "x": 1000, "y": 2190, "width": 500, "height": 130},
        {"id": "economics", "title": "经济结果", "detail": "价格盈亏、手续费、资金费\n现金、持仓、已实现 / 未实现盈亏", "x": 1755, "y": 2190, "width": 500, "height": 130}
      ]
    },
    {
      "id": "evidence",
      "title": "I．版本化证据与现有前端",
      "x": 35, "y": 2430, "width": 2430, "height": 300,
      "nodes": [
        {"id": "trace", "title": "精确证据关联", "detail": "策略 / 包 / 数据 / 代码 / 账户 / Run / Event\n信号 → 目标 → 风控 → 订单 → 成交 → 账本", "x": 95, "y": 2490, "width": 500, "height": 155},
        {"id": "readonly", "title": "小型封存摘要与只读接口", "detail": "核验身份、Hash 与来源\n页面读取不训练、不恢复、不重新核账", "x": 735, "y": 2490, "width": 500, "height": 155},
        {"id": "frontend", "title": "既有页面", "detail": "研究台与候选交接｜投资组合\nBTC 控制台｜策略模块 / 执行安全｜架构地图", "x": 1375, "y": 2490, "width": 430, "height": 155},
        {"id": "readonly-boundary", "title": "当前部署：research_readonly", "detail": "公共行情与研究证据可读\n账户、Demo 控制、下单与交易权限关闭", "x": 1975, "y": 2490, "width": 430, "height": 155}
      ]
    }
  ],
  "edges": [
    {"id": "history-dataset", "from": "okx-history", "to": "dataset", "style": "solid"},
    {"id": "factor-factory", "from": "factor-ast", "to": "alpha-factory", "style": "solid"},
    {"id": "factory-qlib", "from": "alpha-factory", "to": "qlib-training", "style": "solid"},
    {"id": "qlib-seal", "from": "qlib-training", "to": "sealed-research", "style": "solid"},
    {"id": "market-diagnostic", "from": "market-v2", "to": "market-diagnostics", "style": "solid"},
    {"id": "market-policy", "from": "market-v2", "to": "market-entry-policy", "style": "solid"},
    {"id": "package-registration", "from": "package-validation", "to": "registration", "style": "solid"},
    {"id": "registration-job", "from": "registration", "to": "offline-job", "style": "solid"},
    {"id": "offline-block", "from": "offline-disabled", "to": "offline-job", "style": "dashed", "label": "当前阻断启动", "labelX": 1885, "labelY": 1050},
    {"id": "donchian-policy", "from": "donchian", "to": "donchian-policy", "style": "solid"},
    {"id": "donchian-target", "from": "donchian-policy", "to": "target", "style": "solid", "route": "right"},
    {"id": "legacy-policy", "from": "legacy-qlib", "to": "candidate-policy", "style": "solid"},
    {"id": "registered-policy", "from": "registered-inference", "to": "candidate-policy", "style": "solid"},
    {"id": "policy-target", "from": "candidate-policy", "to": "target", "style": "solid"},
    {"id": "target-risk", "from": "target", "to": "risk", "style": "solid"},
    {"id": "risk-guardian", "from": "risk", "to": "guardian", "style": "solid"},
    {"id": "guardian-oms", "from": "guardian", "to": "oms", "style": "solid"},
    {"id": "oms-dispatcher", "from": "oms", "to": "dispatcher", "style": "solid"},
    {"id": "dispatcher-offline", "from": "dispatcher", "to": "offline", "style": "solid"},
    {"id": "dispatcher-demo", "from": "dispatcher", "to": "demo", "style": "dashed", "label": "另行授权及验收", "labelX": 1540, "labelY": 1835},
    {"id": "offline-events", "from": "offline", "to": "events", "style": "solid", "route": "right"},
    {"id": "demo-events", "from": "demo", "to": "events", "style": "dashed", "label": "获授权后的交易所回执", "labelX": 1515, "labelY": 1980},
    {"id": "offline-protection", "from": "offline", "to": "protection", "style": "solid"},
    {"id": "protection-events", "from": "protection", "to": "events", "style": "solid"},
    {"id": "events-ledger", "from": "events", "to": "ledger-uow", "style": "solid", "route": "left"},
    {"id": "ledger-economics", "from": "ledger-uow", "to": "economics", "style": "solid", "route": "right"},
    {"id": "ledger-recovery", "from": "ledger-uow", "to": "recovery", "style": "solid", "both": true},
    {"id": "trace-readonly", "from": "trace", "to": "readonly", "style": "solid"},
    {"id": "readonly-frontend", "from": "readonly", "to": "frontend", "style": "solid"},
    {"id": "boundary-frontend", "from": "readonly-boundary", "to": "frontend", "style": "dashed", "label": "页面能力边界", "labelX": 1890, "labelY": 2570},
    {"id": "dataset-factor", "from": "dataset", "to": "factor-ast", "style": "solid"},
    {"id": "dataset-donchian", "from": "dataset", "to": "donchian", "style": "solid", "route": "left"},
    {"id": "dataset-inference", "from": "dataset", "to": "registered-inference", "style": "solid"},
    {"id": "dataset-m1", "from": "dataset", "to": "market-m1", "style": "solid"},
    {"id": "dataset-market", "from": "dataset", "to": "market-v2", "style": "solid"},
    {"id": "m1-seal", "from": "market-m1", "to": "sealed-research", "style": "dashed", "label": "旁路证据，不控制交易", "labelX": 955, "labelY": 610},
    {"id": "diagnostic-trace", "from": "market-diagnostics", "to": "trace", "style": "solid"},
    {"id": "market-donchian", "from": "market-entry-policy", "to": "donchian-policy", "style": "dashed", "label": "仅冻结 Donchian 历史路径", "labelX": 1880, "labelY": 1180},
    {"id": "seal-package", "from": "sealed-research", "to": "package-validation", "style": "solid", "route": "left"},
    {"id": "seal-legacy", "from": "sealed-research", "to": "legacy-qlib", "style": "solid"},
    {"id": "job-inference", "from": "offline-job", "to": "registered-inference", "style": "solid"},
    {"id": "account-target", "from": "account-facts", "to": "target", "style": "solid", "route": "right"},
    {"id": "account-guardian", "from": "account-facts", "to": "guardian", "style": "solid"},
    {"id": "ledger-account", "from": "ledger-uow", "to": "account-facts", "style": "solid", "label": "核账后的事实供下一次决策使用", "labelX": 2140, "labelY": 1175, "route": "right"},
    {"id": "registration-trace", "from": "registration", "to": "trace", "style": "solid", "route": "left"},
    {"id": "target-trace", "from": "target", "to": "trace", "style": "solid"},
    {"id": "guardian-trace", "from": "guardian", "to": "trace", "style": "solid", "route": "left"},
    {"id": "ledger-trace", "from": "ledger-uow", "to": "trace", "style": "solid"},
    {"id": "public-frontend", "from": "public-market", "to": "frontend", "style": "solid", "label": "可视行情不等于策略输入", "labelX": 1580, "labelY": 350, "route": "right"}
  ]
};
// BTC_PANORAMA_DATA_END

export const btcPanoramaNodeCount = btcSystemPanorama.groups
  .reduce((total, group) => total + group.nodes.length, 0);

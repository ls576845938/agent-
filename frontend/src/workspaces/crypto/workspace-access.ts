// Display routing only. This never grants an operator capability: runtime
// actions still require the existing authoritative backend V2 contract.
export type WorkspaceHealth = {
  service?: string;
  data_source_default?: string;
  evidence_profile?: string;
  read_only?: boolean;
  controls_disabled?: boolean;
};

export type CryptoWorkspaceMode = 'research_readonly' | 'runtime' | 'unavailable';

export function cryptoWorkspaceAccess(health: WorkspaceHealth | null) {
  const mode: CryptoWorkspaceMode = (health?.evidence_profile === 'research_readonly' || health?.evidence_profile === 'candidate_management')
    && health.read_only === true && health.controls_disabled === true
    ? 'research_readonly'
    : (health?.evidence_profile === 'demo_quasi_live' || health?.evidence_profile === 'promotion_strict')
      && health.read_only === false
      ? 'runtime'
      : 'unavailable';
  return {
    mode,
    demoRuntime: mode === 'runtime',
    publicMarket: mode !== 'unavailable',
    // The stream is public display data only. Research-readonly mode may
    // subscribe to it without opening Demo/runtime controls or capabilities.
    publicStream: mode !== 'unavailable',
    marketViewPath: mode === 'research_readonly' ? '/api/research/btc/public-market/view' : '/api/research/btc/demo-paper/market-view',
    marketTickerPath: mode === 'research_readonly' ? '/api/research/btc/public-market/ticker' : '/api/research/btc/demo-paper/market-ticker',
    marketStreamPath: mode === 'research_readonly' ? '/api/research/btc/public-market/stream' : '/api/research/btc/demo-paper/market-stream',
    title: mode === 'research_readonly' ? '当前为研究只读模式' : '后端模式尚未确认',
    summary: mode === 'research_readonly'
      ? '运行控制未开放；不读取 Demo 账户，不启动策略，不提交订单。'
      : '暂停运行接口请求与操作；确认后端模式前不会推断交易权限。',
    marketUnavailable: '后端模式尚未确认，公共行情请求暂未启动。',
  };
}

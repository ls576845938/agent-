export type ResearchWorkspaceHealth = {
  evidence_profile?: string;
  read_only?: boolean;
  controls_disabled?: boolean;
};

export type ResearchWorkspaceMode =
  | 'research_readonly'
  | 'candidate_management'
  | 'runtime'
  | 'unknown';

export type ResearchWorkspaceAccess = {
  mode: ResearchWorkspaceMode;
  researchWrites: boolean;
  candidateManagement: boolean;
  reason: string;
};

// Display gating only. Backend access policy remains authoritative for every
// request. Missing or contradictory health fields must never enable a write.
export function researchWorkspaceAccess(health: ResearchWorkspaceHealth | null): ResearchWorkspaceAccess {
  if (health?.evidence_profile === 'research_readonly'
      && health.read_only === true && health.controls_disabled === true) {
    return {
      mode: 'research_readonly',
      researchWrites: false,
      candidateManagement: false,
      reason: '研究只读模式：可刷新并查看证据，但训练、恢复、注册、复核与组合写入均关闭。',
    };
  }
  if (health?.evidence_profile === 'candidate_management'
      && health.read_only === true && health.controls_disabled === true) {
    return {
      mode: 'candidate_management',
      researchWrites: false,
      candidateManagement: true,
      reason: '候选管理模式：只开放候选管理业务；研究训练、组合与交易操作仍关闭。',
    };
  }
  if (['demo_quasi_live', 'promotion_strict'].includes(health?.evidence_profile || '')
      && health?.read_only === false && health.controls_disabled === false) {
    return {
      mode: 'runtime',
      researchWrites: true,
      candidateManagement: false,
      reason: '',
    };
  }
  return {
    mode: 'unknown',
    researchWrites: false,
    candidateManagement: false,
    reason: '后端模式尚未确认：读取仍可重试，所有有副作用的操作保持关闭。',
  };
}

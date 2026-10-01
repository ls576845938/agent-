export type QuantFrontendIdentity = {
  schema_version: 'quant_frontend_runtime_identity_v1';
  release_id: string;
  fingerprint: string;
  configured_fingerprint: string;
  source_head: string;
  frontend_src_tree: string;
  canonical_branch: 'main';
  canonical_port: 3000;
  canonical: boolean;
  manifest_match: boolean;
  worktree: string;
};

declare const __QUANT_FRONTEND_IDENTITY__: QuantFrontendIdentity;

export const frontendIdentity = __QUANT_FRONTEND_IDENTITY__;
export const frontendFingerprintShort = frontendIdentity.fingerprint.slice(0, 12);

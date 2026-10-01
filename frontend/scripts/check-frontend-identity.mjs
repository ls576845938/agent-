import {inspectFrontendIdentity} from './frontend-identity-lib.mjs';

const requireCanonical = process.argv.includes('--canonical');
const inspection = inspectFrontendIdentity(process.cwd(), {requireClean: requireCanonical});
const passed = inspection.manifest_match
  && inspection.baseline_ancestor
  && (!requireCanonical || inspection.canonical);

console.log(JSON.stringify({
  status: passed ? 'passed' : 'blocked',
  canonical_required: requireCanonical,
  canonical: inspection.canonical,
  branch: inspection.branch,
  source_head: inspection.source_head,
  main_head: inspection.main_head,
  main_worktree: inspection.main_worktree,
  fingerprint: inspection.fingerprint,
  configured_fingerprint: inspection.manifest.fingerprint,
  manifest_match: inspection.manifest_match,
  baseline_ancestor: inspection.baseline_ancestor,
  dirty_paths: inspection.dirty_paths,
}, null, 2));

if (!passed) process.exit(2);

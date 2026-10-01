import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const baseline = execFileSync('git', ['show', '4096453b344e777e99f4272b43582d60cf1251f9:frontend/src/workspaces/ResearchDashboard.tsx'], {cwd: root, encoding: 'utf8'});
const expected = baseline.replaceAll("from '../", "from '../../").replaceAll("from './research/", "from './").replace('export default function ResearchDashboard()', 'export default function LegacyResearchDashboard()');
const legacy = readFileSync(new URL('../src/workspaces/research/LegacyResearchDashboard.tsx', import.meta.url), 'utf8');
const normalize = text => text.replaceAll('\r\n', '\n').trimEnd();
assert.equal(normalize(legacy), normalize(expected), 'Legacy must match the saved baseline except module-relative imports and exported component name.');
console.log('PASS: original research page preserved against Git baseline 4096453b344e777e99f4272b43582d60cf1251f9');

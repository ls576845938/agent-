import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

function load(relative) {
  const exports = {};
  const source = fs.readFileSync(new URL(relative, import.meta.url), 'utf8');
  new Function('exports', ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText)(exports);
  return exports;
}
const {buildParameterSlice, defaultAxes, metricQuality, formatMapMetric} = load('../src/workspaces/crypto/strategy-parameter-map.ts');
const {alphaSourcesFor} = load('../src/lib/strategy-alpha.ts');
const row = (id, fast, slow, fee = 10, sharpe = 1) => ({candidate_id: id, family: 'ma', params: {fast, slow, fee}, metrics: {sharpe_ratio: sharpe, max_drawdown_pct: -12}});
const rows = [row('a', 10, 60), row('b', 20, 60), row('c', 10, 80), row('other-cost', 20, 80, 20)];
const slice = buildParameterSlice(rows, 'fast', 'slow', {fee: 10}, 'sharpe_ratio');
assert.deepEqual(slice.xValues, [10, 20]);
assert.deepEqual(slice.yValues, [60, 80]);
assert.equal(slice.cells.filter((cell) => cell.status === 'available').length, 3);
assert.equal(slice.cells.find((cell) => cell.x === 20 && cell.y === 80).status, 'missing');
assert.equal(buildParameterSlice([...rows, row('duplicate', 10, 60, 10, 9)], 'fast', 'slow', {fee: 10}, 'sharpe_ratio').cells[0].status, 'ambiguous');
assert.equal(buildParameterSlice([row('nan', 10, 60, 10, NaN)], 'fast', 'slow', {fee: 10}, 'sharpe_ratio').cells[0].status, 'missing_metric');
assert.equal(buildParameterSlice(rows, 'fast', 'fast', {fee: 10}, 'sharpe_ratio').cells.length, 0);
assert.equal(buildParameterSlice(rows, 'fast', 'slow', {}, 'sharpe_ratio').cells.length, 0, 'must freeze every other parameter');
assert.deepEqual(defaultAxes([{params: {fast_window: 10, slow_window: 60}}]), ['fast_window', 'slow_window']);
assert.deepEqual(defaultAxes([{params: {entry_window: 180, exit_window: 90, cooldown_bars: 6}}]), ['entry_window', 'cooldown_bars']);
assert.ok(metricQuality(-5, 'max_drawdown_pct') > metricQuality(-20, 'max_drawdown_pct'));
assert.equal(metricQuality(5, 'max_drawdown_pct'), metricQuality(-5, 'max_drawdown_pct'));
assert.equal(formatMapMetric(0, 'sharpe_ratio'), '0.00');
assert.equal(formatMapMetric(null, 'sharpe_ratio'), '未发布');
const donchian = [120, 180, 240].map((entry, index) => ({candidate_id: `d${index}`, family: 'donchian', params: {signal_type: 'symmetric_donchian', entry_window: entry, exit_window: entry / 2, cooldown_bars: 6}, metrics: {sharpe_ratio: 1}}));
assert.equal(buildParameterSlice(donchian, 'entry_window', 'cooldown_bars', {signal_type: 'symmetric_donchian'}, 'sharpe_ratio').cells.filter((cell) => cell.status === 'available').length, 3, 'published formula coupling is explicit, not an accidental hidden parameter change');
assert.equal(buildParameterSlice([...donchian, {...donchian[0], params: {...donchian[0].params, exit_window: 99}}], 'entry_window', 'cooldown_bars', {signal_type: 'symmetric_donchian'}, 'sharpe_ratio').cells.length, 0, 'one broken coupling must require an explicit fixed exit window');
assert.deepEqual(alphaSourcesFor('macro_trend'), ['trend'], 'current implementation uses only price MA, not macro factors');
assert.deepEqual(alphaSourcesFor('factor_rank'), ['time_series'], 'single-frame momentum/volatility is not cross-sectional ranking');
assert.deepEqual(alphaSourcesFor('reversion_rsi'), ['time_series']);
assert.deepEqual(alphaSourcesFor('unknown_trend_name'), [], 'unknown names must not be guessed');
assert.deepEqual(alphaSourcesFor('pairs_trading'), [], 'unregistered hypothetical IDs are not classified from their names');
assert.deepEqual(alphaSourcesFor('earnings_drift'), ['trend', 'time_series'], 'current implementation has no earnings input');
console.log('PASS parameter map: fixed slices, missing cells, duplicate rejection, axes, metric direction, exact alpha taxonomy');

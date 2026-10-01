import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = fs.readFileSync(new URL('../src/workspaces/crypto/TradingViewChart.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
const slots = [];
const effects = [];
let cursor = 0;
let queue = [];
let options;
let creates = 0;
let fits = 0;
let updates = 0;
let sets = 0;
let range = {from: 20, to: 60};
const context = new Proxy({}, {get: (_, key) => key === 'measureText' ? () => ({width: 10}) : () => {}});
const makeElement = (canvas = false) => ({clientWidth: 320, clientHeight: 300, width: 320, height: 300,
  dataset: {}, ...(canvas ? {getContext: () => context} : {})});
const plot = makeElement();
const overlay = makeElement(true);
const timeScale = {fitContent: () => {fits++;}, getVisibleLogicalRange: () => range,
  subscribeVisibleLogicalRangeChange() {}, unsubscribeVisibleLogicalRangeChange() {}};
const series = () => ({setData() {sets++;}, update() {updates++;}, priceScale: () => ({applyOptions() {}})});
const chart = {timeScale: () => timeScale, addSeries: series, applyOptions() {}, remove() {},
  priceScale: () => ({applyOptions() {}})};
const react = {
  useRef(initial) {const i = cursor++; return slots[i] ??= {current: initial};},
  useState(initial) {const i = cursor++; slots[i] ??= {value: initial}; return [slots[i].value, value => {slots[i].value = value;}];},
  useMemo(fn) {cursor++; return fn();},
  useEffect(fn, deps) {const i = cursor++; const old = effects[i];
    if (!old || deps.some((value, index) => !Object.is(value, old.deps[index]))) {
      queue.push(() => {old?.cleanup?.(); effects[i] = {deps, cleanup: fn()};});
    }
  },
};
const jsx = (type, props) => ({type, props});
const dependencies = {
  react,
  'react/jsx-runtime': {jsx, jsxs: jsx},
  'lightweight-charts': {createChart: (_, value) => {creates++; options = value; return chart;},
    CandlestickSeries: 'candle', HistogramSeries: 'histogram', LineSeries: 'line',
    ColorType: {Solid: 'solid'}, CrosshairMode: {Normal: 0, Hidden: 2}, createSeriesMarkers() {}},
};
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText;
const module = {exports: {}};
new Function('exports', 'require', 'window', 'ResizeObserver', compiled)(module.exports,
  key => {assert.ok(dependencies[key], `Unexpected dependency ${key}`); return dependencies[key];},
  {devicePixelRatio: 1, requestAnimationFrame: fn => fn()}, class {observe() {} disconnect() {}});
const baseCandles = Array.from({length: 300}, (_, i) => ({time: 1700000000 + i * 60,
  open: 100, high: 102, low: 99, close: 101, volume: 5}));
const render = candles => {
  cursor = 0; queue = [];
  const tree = module.exports.default({candles, markers: [], loading: false});
  const walk = node => {
    if (!node || typeof node !== 'object') return;
    if (node.props?.ref) node.props.ref.current = node.type === 'canvas' ? overlay : plot;
    for (const child of [node.props?.children].flat()) walk(child);
  };
  walk(tree); queue.forEach(fn => fn()); return tree;
};
const tree = render(baseCandles);
assert.ok(options.timeScale.minBarSpacing <= 0.5, 'narrow chart must allow zooming out below the old 3px candle limit');
assert.doesNotMatch(JSON.stringify(tree), /tv-chart-navigation|btc-chart-zoom-|btc-chart-fit|btc-chart-interaction-hint/);
assert.doesNotMatch(css, /\.tv-chart-navigation/);
assert.equal(options.handleScale.mouseWheel, true);
assert.equal(options.handleScale.pinch, true);
assert.equal(options.handleScale.axisPressedMouseMove, true);
assert.equal(options.handleScroll.pressedMouseMove, true);
assert.equal(options.handleScroll.horzTouchDrag, true);
assert.equal(options.timeScale.lockVisibleTimeRangeOnResize, true);
assert.equal(fits, 1);
const beforeTick = updates;
render(baseCandles.map((item, i) => i === 299 ? {...item, close: 101.5} : item));
assert.ok(updates > beforeTick);
const beforeRollover = sets;
render([...baseCandles.slice(1), {...baseCandles[299], time: baseCandles[299].time + 60}]);
assert.ok(sets > beforeRollover);
assert.equal(creates, 1, 'live candle updates must not recreate the chart');
assert.equal(fits, 1, 'live candle updates must not refit the user viewport');
assert.deepEqual(range, {from: 20, to: 60});
console.log('PASS: no navigation overlay; native wheel/pinch/axis/pan enabled; 0.5px zoom floor; tick and rollover do not recreate/refit');

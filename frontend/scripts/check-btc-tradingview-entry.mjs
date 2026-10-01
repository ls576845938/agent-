import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

const read = (path) => readFileSync(resolve(process.cwd(), path), 'utf8');
const app = read('src/App.tsx');
const workspace = read('src/workspaces/CryptoWorkspace.tsx');
const chart = read('src/workspaces/crypto/TradingViewChart.tsx');
const styles = read('src/index.css');
const terminalStyles = read('src/terminal-workbench.css');
const packageJson = JSON.parse(read('package.json'));
const compactStyles = styles.replace(/\s+/g, ' ');
const compactTerminalStyles = terminalStyles.replace(/\s+/g, ' ');

const markers = {
  cryptoRoute: app.includes('path="/crypto"') && app.includes('<CryptoWorkspace'),
  chartImported: workspace.includes("from './crypto/TradingViewChart'"),
  chartRendered: workspace.includes('<TradingViewChart'),
  chartEngine: chart.includes('createChart'),
  chartDependency: packageJson.dependencies?.['lightweight-charts'] === '5.2.0',
  failClosedCopy: workspace.includes('Demo only') && workspace.includes('Live locked'),
  fluidWorkspaceTypography:
    compactStyles.includes('--btc-fluid-font-size: clamp(12px, min(1.04vw, 1.7vh), 18px);')
    && compactStyles.includes('font-size: var(--btc-fluid-font-size);')
    && terminalStyles.includes('BTC-FLUID-TYPOGRAPHY-01')
    && compactTerminalStyles.includes('.crypto-tv-shell { --btc-fluid-font-size: clamp(12px, min(1.04vw, 1.7vh), 18px); font-size: var(--btc-fluid-font-size); }')
    && compactTerminalStyles.includes('.crypto-tv-shell :is(span, strong, .status, .status-text, .control-label) { font-size: max(11px, 0.92em) !important; }'),
  narrowChartKeepsUsableHeight:
    styles.includes('BTC-CHART-NARROW-VIEWPORT-OCCLUSION-03')
    && compactStyles.includes('.crypto-tv-shell.layout-split:not(.chart-expanded) > .tv-primary-grid:not(.console-stacked) { grid-template-rows: max-content 8px minmax(var(--btc-strategy-tester-height, 420px), 1fr); height: auto; min-height: max(720px, calc(100vh - 128px)); }')
    && compactStyles.includes('.crypto-tv-shell.layout-split:not(.chart-expanded) > .tv-primary-grid:not(.console-stacked) > .tv-demo-console { contain: size; }')
    && compactStyles.includes('.crypto-tv-shell.layout-split:not(.chart-expanded) > .tv-primary-grid:not(.console-stacked) > .tv-bottom-dock { height: auto; min-height: var(--btc-strategy-tester-height, 420px); }')
    && compactStyles.includes('.crypto-tv-shell.layout-split .tv-market-terminal-body { flex: 0 0 clamp(280px, 38vh, 480px); height: clamp(280px, 38vh, 480px); min-height: 280px; grid-template-rows: minmax(0, 1fr); }'),
  narrowChartChildrenStayInsideBody:
    compactStyles.includes('.crypto-tv-shell.layout-split .tv-market-terminal-body > .tv-chart-stack { height: auto; min-height: 0; align-self: stretch; overflow: hidden; }')
    && compactStyles.includes('.crypto-tv-shell.layout-split .tv-market-terminal-body > .btc-public-depth { height: auto; min-height: 0; align-self: stretch; overflow-x: hidden; overflow-y: auto; }'),
  narrowChartChromeKeepsNaturalHeight:
    compactStyles.includes('.crypto-tv-shell.layout-split > .tv-primary-grid > .tv-chart-panel > :not(.tv-market-terminal-body) { flex-shrink: 0; }'),
  expandedChartHidesDuplicatedReadModel:
    compactStyles.includes(".crypto-tv-shell.chart-expanded > [data-testid='btc-current-head-domain-read-model'] { display: none; }"),
};

const missing = Object.entries(markers)
  .filter(([, present]) => !present)
  .map(([name]) => name);

if (missing.length > 0) {
  console.error(`BTC TradingView entry regression: missing ${missing.join(', ')}`);
  process.exit(1);
}

console.log(JSON.stringify({status: 'passed', markers}, null, 2));

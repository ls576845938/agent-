import {Link} from 'react-router-dom';
import {ArrowLeft, ShieldWarning, WarningCircle} from '@phosphor-icons/react';

export const BTC_ROLLOVER_ARCHIVE = {
  routeId: 'btc_10x_rollover_10sleeve',
  archiveId: 'br_split_2_on_double_lev10p0',
  scenario: 'br_split_2_on_double_lev10p0',
  displayName: 'BTC 10x 十仓滚仓爆炸版（历史危险参照）',
  trackedExplanation: 'docs/research/btc_10x_rollover_and_donchian_direction_origin.md',
  localSnapshotPaths: [
    'artifacts/btc_bankroll_rollover_lab/latest/btc_bankroll_rollover_lab_report.json',
    'artifacts/btc_bankroll_rollover_review/latest/btc_bankroll_rollover_review_report.json',
  ],
  metrics: {
    totalReturnPct: 1510327.760228,
    annualReturnPct: 4648.314318,
    maxDrawdownPct: 49.504493,
    rolloverIncrementVsNoRollover: 0,
    rollingStarts: 29,
    maxMedianFinalEquityRatio: 56.856895,
  },
  derivedIdentity: 'high_octane_attack_sleeve_v2/ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none',
  derivedMetrics: {
    originalAnnualReturnPct: 969.07,
    originalTotalReturnPct: 36627.90,
    originalMaxDrawdownPct: 27.10,
    strictNextBarAnnualReturnPct: 275.53,
    strictNextBarTotalReturnPct: 2636.05,
    strictNextBarMaxDrawdownPct: 41.30,
  },
} as const;

export function BtcResearchArchiveCard() {
  const archive = BTC_ROLLOVER_ARCHIVE;
  return (
    <section className="panel btc-rollover-archive-card" data-testid="btc-rollover-archive-card">
      <div className="panel-header">
        <div>
          <p className="eyebrow">BTC HISTORICAL DANGER REFERENCE · READ ONLY</p>
          <h3>{archive.displayName}</h3>
        </div>
        <span className="status-chip">RESEARCH ONLY · NO PAPER · NO LIVE</span>
      </div>
      <p>
        原始场景 <code>{archive.scenario}</code>：初始 10 个 isolated sleeves、10x 杠杆、
        <code>split_2_on_double</code>；拆分后允许且实际达到 100 sleeves，并非全程最多 10 仓。
        它是已有 Donchian 趋势方向上的资金管理压力样本，不是独立新 alpha。
      </p>
      <div className="btc-rollover-archive-metrics">
        <ArchiveMetric label="原始总收益" value={formatPercent(archive.metrics.totalReturnPct)} />
        <ArchiveMetric label="原始年化" value={formatPercent(archive.metrics.annualReturnPct)} />
        <ArchiveMetric label="最大回撤" value={formatPercent(archive.metrics.maxDrawdownPct)} danger />
        <ArchiveMetric label="拆仓增量 vs 10x 不滚仓" value="0" danger />
        <ArchiveMetric label="Rolling starts" value={String(archive.metrics.rollingStarts)} />
        <ArchiveMetric label="最大/中位终值比" value={archive.metrics.maxMedianFinalEquityRatio.toFixed(6)} danger />
      </div>
      <div className="btc-rollover-archive-warning">
        <ShieldWarning size={22} />
        <span>-5% / -10% adverse shock 可出现 all-dead；极端起点敏感，不能作为 paper/live 候选。</span>
      </div>
      <p className="text-muted">
        指标来自 tracked 来源说明与本机 ignored latest 复核快照；latest 不是 current-HEAD immutable artifact，
        不得作为 promotion evidence。
      </p>
      <Link
        className="strategy-history-link"
        data-testid="btc-rollover-archive-link"
        to={`/crypto?research_archive=${archive.routeId}&panel=backtest`}
      >
        打开只读历史档案与风险复核
      </Link>
    </section>
  );
}

export default function BtcResearchArchive() {
  const archive = BTC_ROLLOVER_ARCHIVE;
  return (
    <article className="btc-rollover-archive-detail" data-testid="btc-rollover-archive-detail">
      <header>
        <div>
          <p className="eyebrow">BTC RESEARCH ARCHIVE · LOCAL SNAPSHOT BOUNDARY</p>
          <h2>{archive.displayName}</h2>
          <code>{archive.archiveId}</code>
        </div>
        <span className="status-chip">READ ONLY · FAIL-CLOSED</span>
      </header>

      <section className="tv-report-notice blocked">
        <WarningCircle size={18} />
        <span>
          本档案只复述 tracked explanation 与本机 ignored latest 快照中的已核对结果；源报告不是 current-HEAD immutable，
          不生成曲线、不补造 ledger/fills，也不解锁 Demo、paper 或 live。
        </span>
        <strong>NO POST · NO DEMO IDENTITY</strong>
      </section>

      <section className="btc-rollover-archive-detail-grid">
        <ArchiveSection title="原始结构" subtitle="方向信号与资金管理必须分开理解">
          <ul>
            <li>底层方向：已筛选 BTC long/short Donchian 趋势方向。</li>
            <li>初始结构：10 个 isolated sleeves；翻倍拆分后允许且实际达到 100 sleeves。</li>
            <li>杠杆：10x。</li>
            <li>滚仓规则：sleeve 翻倍后按 <code>split_2_on_double</code> 拆为 2 个继续滚。</li>
            <li>场景 identity：<code>{archive.scenario}</code>。</li>
          </ul>
        </ArchiveSection>
        <ArchiveSection title="原始结果" subtitle="危险参照，不是收益承诺">
          <div className="btc-rollover-archive-metrics compact">
            <ArchiveMetric label="总收益" value={formatPercent(archive.metrics.totalReturnPct)} />
            <ArchiveMetric label="年化" value={formatPercent(archive.metrics.annualReturnPct)} />
            <ArchiveMetric label="最大回撤" value={formatPercent(archive.metrics.maxDrawdownPct)} danger />
          </div>
        </ArchiveSection>
        <ArchiveSection title="复核结论" subtitle="收益主要来自趋势信号 + 10x + 长趋势复利">
          <ul>
            <li><code>split_2_on_double</code> 相对 10x no-rollover 的增量：0。</li>
            <li>Rolling starts：{archive.metrics.rollingStarts}。</li>
            <li>最大/中位 final equity 比：{archive.metrics.maxMedianFinalEquityRatio.toFixed(6)}。</li>
            <li>-5% / -10% adverse shock 可令所有 sleeves 同时归零（all-dead）。</li>
          </ul>
        </ArchiveSection>
        <section id="high-octane-derived" className="tv-report-card">
          <div className="tv-report-card-head"><div><strong>身份隔离与 high-octane 派生对照</strong><span>后续派生不是原始万倍对象</span></div></div>
          <p>
            当前 registry 派生身份 <code>{archive.derivedIdentity}</code> 仅作后续派生说明，
            不是 <code>{archive.archiveId}</code>，不得替代原始档案，也不会注入 Demo catalog/start。
          </p>
          <p>
            结构差异：high-octane 最多 10 个暴露，仅 2 个 10x attack sleeves；原始 rollover 虽从 10 sleeves 开始，
            但 split 后实际达到 100 sleeves。
          </p>
          <div className="btc-rollover-archive-metrics compact">
            <ArchiveMetric label="High-octane 原始年化" value={formatPercent(archive.derivedMetrics.originalAnnualReturnPct)} />
            <ArchiveMetric label="High-octane 原始总收益" value={formatPercent(archive.derivedMetrics.originalTotalReturnPct)} />
            <ArchiveMetric label="High-octane 原始 DD" value={formatPercent(archive.derivedMetrics.originalMaxDrawdownPct)} danger />
            <ArchiveMetric label="严格 next-bar 年化" value={formatPercent(archive.derivedMetrics.strictNextBarAnnualReturnPct)} />
            <ArchiveMetric label="严格 next-bar 总收益" value={formatPercent(archive.derivedMetrics.strictNextBarTotalReturnPct)} />
            <ArchiveMetric label="严格 next-bar DD" value={formatPercent(archive.derivedMetrics.strictNextBarMaxDrawdownPct)} danger />
          </div>
          <p><strong>not_forward_ready</strong> · research-only · 无完整 series 时仅展示已核验表格数值，不生成曲线。</p>
        </section>
      </section>

      <section className="btc-rollover-archive-sources">
        <h3>来源与证据边界</h3>
        <dl>
          <div><dt>Tracked explanation</dt><dd><code>{archive.trackedExplanation}</code></dd></div>
          {archive.localSnapshotPaths.map((path) => (
            <div key={path}><dt>Local ignored latest</dt><dd><code>{path}</code></dd></div>
          ))}
          <div><dt>Freshness</dt><dd>非 current-HEAD immutable · 非 promotion evidence</dd></div>
          <div><dt>Safety</dt><dd>research-only · paper=false · live=false · broker/order=false</dd></div>
        </dl>
      </section>

      <Link className="strategy-history-link" to="/strategies"><ArrowLeft size={18} />返回策略历史档案</Link>
    </article>
  );
}

function ArchiveSection({title, subtitle, children}: {title: string; subtitle: string; children: unknown}) {
  return (
    <section className="tv-report-card">
      <div className="tv-report-card-head"><div><strong>{title}</strong><span>{subtitle}</span></div></div>
      {children}
    </section>
  );
}

function ArchiveMetric({label, value, danger = false}: {label: string; value: string; danger?: boolean}) {
  return <div className={danger ? 'danger' : ''}><span>{label}</span><strong>{value}</strong></div>;
}

function formatPercent(value: number): string {
  return `${value.toLocaleString('en-US', {minimumFractionDigits: 6, maximumFractionDigits: 6})}%`;
}

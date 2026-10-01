import {useEffect, useState} from 'react';

import MetricCard from '../components/MetricCard';
import StatusBadge from '../components/StatusBadge';
import {WorkbenchFrame} from '../components/workbench/Workbench';
import {
  CN_LAYER_IDS,
  failClosedCNWorkspaceModel,
  loadCNWorkspaceReadModel,
  type CNLayerId,
  type CNWorkspaceReadModel,
} from './cn/domainReadModel';
import './cn/cn-equity.css';

type CNEquityWorkspaceProps = {
  load?: () => Promise<CNWorkspaceReadModel>;
};

const LAYER_LABELS: Record<CNLayerId, {code: string; title: string}> = {
  data: {code: '01', title: '数据 / PIT'},
  market_rules: {code: '02', title: '市场规则'},
  backtest: {code: '03', title: '回测证据'},
  oms: {code: '04', title: 'OMS / Ledger'},
  replay: {code: '05', title: 'Replay'},
  qmt: {code: '06', title: 'QMT 合同'},
};

const FLAG_LABELS: Record<string, string> = {
  broker_access_allowed: 'BROKER ACCESS',
  live_allowed: 'LIVE',
  order_endpoint_allowed: 'ORDER ENDPOINT',
  paper_allowed: 'PAPER',
  paper_queue_allowed: 'PAPER QUEUE',
  private_endpoint_allowed: 'PRIVATE ENDPOINT',
  promotion_allowed: 'PROMOTION',
  qmt_sdk_allowed: 'QMT SDK',
  real_order_allowed: 'REAL ORDER',
  withdraw_allowed: 'WITHDRAW',
  demo_allowed: 'DEMO',
  network_allowed: 'EXTERNAL NETWORK',
  secret_access_allowed: 'SECRET ACCESS',
};

function shortHash(value: string, fallback = 'MISSING') {
  return value ? `${value.slice(0, 12)}…${value.slice(-6)}` : fallback;
}

function formatUtc(value: string) {
  if (!value) return 'NOT GENERATED';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  });
}

function evidenceClassLabel(value: string) {
  const labels: Record<string, string> = {
    quality_checked: 'quality_checked',
    research_ready: 'research evidence only',
    backtest_ready: 'backtest evidence only',
    promotion_evidence_ready: 'promotion evidence only',
  };
  return labels[value] ?? 'unclassified evidence';
}

export default function CNEquityWorkspace({
  load = loadCNWorkspaceReadModel,
}: CNEquityWorkspaceProps) {
  const [view, setView] = useState<CNWorkspaceReadModel | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setView(await load());
    } catch (error) {
      setView(failClosedCNWorkspaceModel(
        'BACKEND_UNAVAILABLE',
        error instanceof Error ? error.message : 'FETCH_FAILED',
      ));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, [load]);

  const display = view ?? failClosedCNWorkspaceModel(
    'BACKEND_UNAVAILABLE',
    'INITIAL_READ_PENDING',
  );
  const currentHead = display.freshness === 'CURRENT_HEAD';
  const allSafetyFalse = display.safety_flags.every(flag => flag.value === false);
  const bannerLabel = loading
    ? 'READING CURRENT-HEAD EVIDENCE'
    : display.availability === 'CURRENT_HEAD_API'
      ? 'FAIL-CLOSED · READ ONLY'
      : `${display.availability} · FAIL-CLOSED`;

  return (
    <WorkbenchFrame className="cn-equity-workbench" testId="cn-equity-terminal">
      <section
        className="cn-equity-workspace"
        data-testid="cn-equity-workspace"
        data-state={display.availability.toLowerCase()}
      >
      <header className="cn-command-header">
        <div className="cn-command-copy">
          <p className="cn-kicker">CN EQUITY / OPERATOR EVIDENCE / GET ONLY</p>
          <h1>A 股证据工作台</h1>
          <p>
            仅解释当前提交的证据与阻塞项。不会采集数据、运行策略、
            连接券商或创建任何订单。
          </p>
        </div>
        <div className="cn-command-actions">
          <StatusBadge
            status={display.status}
            label="当前只读状态"
            tone="bad"
          />
          <button
            type="button"
            className="cn-refresh-button"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? '读取中…' : '重新读取证据'}
          </button>
        </div>
      </header>

      <section className="cn-lock-strip" aria-label="交易权限锁">
        <div data-testid="cn-paper-lock">
          <span>PAPER</span>
          <strong>LOCKED</strong>
        </div>
        <div data-testid="cn-live-lock">
          <span>LIVE</span>
          <strong>LOCKED</strong>
        </div>
        <div>
          <span>BROKER CALLS</span>
          <strong>0</strong>
        </div>
        <div>
          <span>API CONTRACT</span>
          <strong>GET · NO-STORE</strong>
        </div>
      </section>

      <section
        className={`cn-fail-banner ${currentHead ? '' : 'cn-fail-banner-alert'}`}
        role="status"
        data-testid="cn-fail-closed-banner"
      >
        <div>
          <span className="cn-pulse" aria-hidden="true" />
          <strong>{bannerLabel}</strong>
        </div>
        <code>{display.gate.first_blocker || 'NO_BLOCKER_REPORTED'}</code>
      </section>

      <section className="cn-metric-grid" aria-label="Current HEAD 摘要">
        <MetricCard
          label="CURRENT HEAD"
          value={shortHash(display.code_commit)}
          tone={currentHead ? 'neutral' : 'bad'}
        />
        <MetricCard
          label="FRESHNESS"
          value={display.freshness}
          tone={currentHead ? 'neutral' : 'bad'}
        />
        <MetricCard
          label="BLOCKERS"
          value={String(display.blockers.length)}
          tone={display.blockers.length > 0 ? 'bad' : 'neutral'}
        />
        <MetricCard
          label="SAFETY FLAGS"
          value={allSafetyFalse ? 'ALL FALSE' : 'VIOLATION'}
          tone={allSafetyFalse ? 'neutral' : 'bad'}
        />
      </section>

      <section className="cn-section" aria-labelledby="cn-layers-heading">
        <div className="cn-section-heading">
          <div>
            <p className="cn-kicker">SIX-LAYER EVIDENCE CHAIN</p>
            <h2 id="cn-layers-heading">领域门禁状态</h2>
          </div>
          <span>{display.readiness_class} · 不构成交易授权</span>
        </div>
        <div className="cn-layer-grid">
          {CN_LAYER_IDS.map(layerId => {
            const layer = display.layers[layerId];
            const blocked = layer.status === 'blocked' || layer.blockers.length > 0;
            return (
              <article
                className={`cn-layer-card ${blocked ? 'cn-layer-blocked' : ''}`}
                data-testid={`cn-layer-${layerId}`}
                key={layerId}
              >
                <div className="cn-layer-card-head">
                  <span>{LAYER_LABELS[layerId].code}</span>
                  <StatusBadge
                    status={blocked ? 'BLOCKED' : 'QUALITY CHECKED'}
                    label={LAYER_LABELS[layerId].title}
                    tone={blocked ? 'bad' : 'neutral'}
                  />
                </div>
                <h3>{LAYER_LABELS[layerId].title}</h3>
                <p>
                  {evidenceClassLabel(layer.readiness_class)} · {layer.gate_impact}
                </p>
                <dl>
                  <div>
                    <dt>source</dt>
                    <dd title={layer.source_event}>{layer.source_event}</dd>
                  </div>
                  <div>
                    <dt>commit</dt>
                    <dd>{shortHash(layer.deliverable_commit)}</dd>
                  </div>
                  <div>
                    <dt>blockers</dt>
                    <dd>{layer.blockers.length}</dd>
                  </div>
                </dl>
                {layer.blockers.length > 0 ? (
                  <ul>
                    {layer.blockers.map(code => <li key={code}>{code}</li>)}
                  </ul>
                ) : (
                  <div className="cn-layer-note">
                    仅表示该层合同通过质量检查；交易权限仍锁定。
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <div className="cn-two-column">
        <section className="cn-section" aria-labelledby="cn-blockers-heading">
          <div className="cn-section-heading">
            <div>
              <p className="cn-kicker">ROOT CAUSE QUEUE</p>
              <h2 id="cn-blockers-heading">全部阻塞项</h2>
            </div>
            <span>{display.blockers.length} open</span>
          </div>
          <div className="cn-blocker-list" data-testid="cn-blocker-list">
            {display.blockers.map((blocker, index) => (
              <article
                className="cn-blocker-row"
                key={`${blocker.code}-${index}`}
              >
                <span className="cn-blocker-index">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div>
                  <strong>{blocker.code}</strong>
                  <p>{blocker.detail}</p>
                  <small>{blocker.next_action}</small>
                </div>
                <div className="cn-blocker-owner">
                  <span>{blocker.layer}</span>
                  <strong>{blocker.owner}</strong>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="cn-section" aria-labelledby="cn-safety-heading">
          <div className="cn-section-heading">
            <div>
              <p className="cn-kicker">NON-NEGOTIABLE INTERLOCK</p>
              <h2 id="cn-safety-heading">安全旗标</h2>
            </div>
            <span>{allSafetyFalse ? '13 / 13 FALSE' : 'CONTRACT VIOLATION'}</span>
          </div>
          <div className="cn-safety-grid" data-testid="cn-safety-grid">
            {display.safety_flags.map(flag => (
              <div
                className="cn-safety-row"
                data-testid="cn-safety-flag"
                key={flag.key}
              >
                <span>{FLAG_LABELS[flag.key] ?? flag.key}</span>
                <strong>false</strong>
                <small>{flag.source}</small>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="cn-provenance" aria-label="证据身份">
        <div>
          <span>generated · Asia/Shanghai display</span>
          <strong>{formatUtc(display.generated_at_utc)}</strong>
        </div>
        <div>
          <span>input sha256</span>
          <code title={display.input_sha256}>
            {shortHash(display.input_sha256)}
          </code>
        </div>
        <div>
          <span>generation hash</span>
          <code title={display.generation_hash}>
            {shortHash(display.generation_hash)}
          </code>
        </div>
        <div>
          <span>availability</span>
          <strong>{display.availability}</strong>
          <small>{display.availability_detail}</small>
        </div>
      </section>
      </section>
    </WorkbenchFrame>
  );
}

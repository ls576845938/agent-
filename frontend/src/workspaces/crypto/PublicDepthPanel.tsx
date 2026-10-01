import {useState} from 'react';

import type {PublicMarketStreamEvent, PublicMarketView} from './demo-types';
import {depthSourceLabel} from './console-display';

type DepthRow = {price: string; size: string; count: string; total: number};

function decimal(value: string | undefined): string {
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? numeric.toLocaleString('zh-CN', {minimumFractionDigits: 1, maximumFractionDigits: 1})
    : '—';
}

function depthRows(rows: Array<{price: string; size: string; count: string}>): DepthRow[] {
  let total = 0;
  return rows.map((row) => {
    total += Math.max(0, Number(row.size) || 0);
    return {...row, total};
  });
}

function DepthSide({
  label,
  rows,
  reverse = false,
}: {
  label: string;
  rows: DepthRow[];
  reverse?: boolean;
}) {
  const maximum = Math.max(...rows.map((row) => row.total), 0);
  const ordered = reverse ? [...rows].reverse() : rows;
  return <ol className={`btc-public-depth-rows ${label === 'asks' ? 'asks' : 'bids'}`} aria-label={`top five ${label}`}>
    {ordered.map((row, index) => {
      const fill = maximum > 0 ? Math.min(100, (row.total / maximum) * 100) : 0;
      return <li key={`${label}-${row.price}-${index}`}>
        <i className="btc-public-depth-fill" style={{width: `${fill}%`}} aria-hidden="true" />
        <span>{decimal(row.price)}</span><span>{decimal(row.size)}</span><span>{decimal(String(row.total))}</span>
      </li>;
    })}
  </ol>;
}

export default function PublicDepthPanel({
  stream,
  marketView,
  ticker,
  visualCandle,
}: {
  stream: PublicMarketStreamEvent | null;
  marketView: PublicMarketView | null;
  ticker: PublicMarketView['ticker'] | null;
  visualCandle: {open: number; close: number} | undefined;
}) {
  const streamDepth = stream?.status === 'live' ? stream.depth : null;
  const depth = streamDepth ?? marketView?.depth ?? null;
  const usingRestFallback = !streamDepth && Boolean(marketView?.depth);
  const restFresh = marketView?.stale === false;
  const state = streamDepth ? 'live' : usingRestFallback ? (restFresh ? 'fallback' : 'stale') : stream?.status ?? 'reconnecting';
  const sourceLabel = depthSourceLabel(Boolean(streamDepth), usingRestFallback, restFresh);
  const [expanded, setExpanded] = useState(true);
  const asks = depth ? depthRows(depth.asks) : [];
  const bids = depth ? depthRows(depth.bids) : [];
  const last = visualCandle?.close ?? Number(ticker?.last);
  const direction = visualCandle && visualCandle.close < visualCandle.open ? 'down' : 'up';
  const buyPower = depth ? Math.max(0, Math.min(100, depth.top5_imbalance * 100)) : 0;
  const sellPower = 100 - buyPower;
  return <section className={`btc-public-depth ${state}`} data-testid="btc-public-depth">
    <header>
      <div><strong>买卖盘口</strong><small title="OKX 公共 books5：有变化时约每 100ms 推送五档快照，并非逐笔成交或 10ms 全量盘口。">五档 · 公共行情</small></div>
      <span data-testid="btc-public-depth-status">{sourceLabel}</span>
      <button type="button" className="btc-public-depth-toggle" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)}>{expanded ? '收起盘口' : '展开盘口'}</button>
    </header>
    {!expanded ? null : !depth ? <p>等待完整五档盘口。</p> : <>
      <div className="btc-public-depth-columns" aria-hidden="true"><span>价格</span><span>数量</span><span>累计</span></div>
      <DepthSide label="asks" rows={asks} reverse />
      <div className={`btc-public-depth-mid ${direction}`} data-testid="btc-public-depth-mid">
        <strong>{Number.isFinite(last) ? last.toLocaleString('zh-CN', {minimumFractionDigits: 1, maximumFractionDigits: 1}) : '—'}</strong>
        <span>{direction === 'up' ? '▲' : '▼'} · 价差 {decimal(depth.spread)}</span>
      </div>
      <DepthSide label="bids" rows={bids} />
      <div className="btc-public-depth-power" aria-label={`买方力量 ${buyPower.toFixed(1)}%，卖方力量 ${sellPower.toFixed(1)}%`}>
        <span className="buy" style={{width: `${buyPower}%`}}>买 {buyPower.toFixed(1)}%</span>
        <span className="sell" style={{width: `${sellPower}%`}}>卖 {sellPower.toFixed(1)}%</span>
      </div>
      <footer title={`盘口序号：${depth.sequence ?? '未提供'}`}><span>更新 {new Date(depth.timestamp_ms).toLocaleTimeString('zh-CN', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3})}</span><span>{usingRestFallback ? (restFresh ? '轮询快照' : '过期快照') : '实时五档'}</span></footer>
    </>}
  </section>;
}

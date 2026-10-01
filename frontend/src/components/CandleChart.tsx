import {useEffect, useMemo, useRef, useState} from 'react';
import type {ChartSeriesPayload} from '../lib/view-model';
import {clampNumber, floorTimestampToInterval, formatPrice, formatTimestamp} from '../lib/utils';

type ValueEvent = {target: {value: string}};

type CandleViewport = {count: number; endIndex: number};
type CandleDragState = {chartWidth: number; startClientX: number; startEndIndex: number; visibleCount: number};
type CandlePoint = ChartSeriesPayload['candles'][number];
type TradeMarker = ChartSeriesPayload['markers'][number];
type CandleDisplayInterval = '1m' | '5m' | '15m' | '4h' | '1d' | '1w' | '1mo';

type ChartPointerEvent = {
  clientX: number;
  preventDefault: () => void;
  currentTarget: {getBoundingClientRect: () => DOMRect; setPointerCapture?: (id: number) => void};
  pointerId?: number;
};

type ChartWheelEvent = {deltaY: number; preventDefault: () => void};

const defaultVisibleCandles = 120;
const minimumVisibleCandles = 20;

const candleDisplayOptions: Array<{value: CandleDisplayInterval; label: string}> = [
  {value: '1m', label: '1 分钟'},
  {value: '5m', label: '5 分钟'},
  {value: '15m', label: '15 分钟'},
  {value: '4h', label: '4 小时'},
  {value: '1d', label: '日'},
  {value: '1w', label: '周'},
  {value: '1mo', label: '月'},
];

const fixedIntervalSeconds: Record<Exclude<CandleDisplayInterval, '1w' | '1mo'>, number> = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '4h': 14400,
  '1d': 86400,
};

function floorTimestampToCandleInterval(unix: number, interval: CandleDisplayInterval): number {
  if (interval === '1w' || interval === '1mo') {
    const timestamp = new Date(unix * 1000);
    if (interval === '1w') {
      const utcDay = timestamp.getUTCDay();
      const daysFromMonday = (utcDay + 6) % 7;
      return Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), timestamp.getUTCDate() - daysFromMonday) / 1000;
    }
    return Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), 1) / 1000;
  }
  const seconds = fixedIntervalSeconds[interval];
  return Math.floor(unix / seconds) * seconds;
}

function aggregateCandles(candles: CandlePoint[], interval: CandleDisplayInterval): CandlePoint[] {
  if (candles.length === 0) return [];
  const aggregated = new Map<number, CandlePoint>();
  for (const candle of candles) {
    const bucketTime = floorTimestampToCandleInterval(candle.time, interval);
    const current = aggregated.get(bucketTime);
    if (!current) {
      aggregated.set(bucketTime, {time: bucketTime, open: candle.open, high: candle.high, low: candle.low, close: candle.close});
      continue;
    }
    current.high = Math.max(current.high, candle.high);
    current.low = Math.min(current.low, candle.low);
    current.close = candle.close;
  }
  return Array.from(aggregated.values()).sort((a, b) => a.time - b.time);
}

function aggregateMarkers(markers: TradeMarker[], interval: CandleDisplayInterval): TradeMarker[] {
  return markers.map((marker) => ({...marker, time: floorTimestampToCandleInterval(marker.time, interval)}));
}

function defaultCandleViewport(length: number): CandleViewport {
  return {count: Math.min(defaultVisibleCandles, Math.max(0, length)), endIndex: length};
}

function clampCandleViewport(length: number, viewport: CandleViewport): CandleViewport {
  if (length <= 0) return {count: 0, endIndex: 0};
  const minCount = Math.min(minimumVisibleCandles, length);
  return {
    count: clampNumber(Math.round(viewport.count), minCount, length),
    endIndex: clampNumber(Math.round(viewport.endIndex), minCount, length),
  };
}

export type CandleChartProps = {
  candles: ChartSeriesPayload['candles'];
  markers: ChartSeriesPayload['markers'];
  title?: string;
};

export default function CandleChart({candles, markers, title = 'K 线与调仓标记'}: CandleChartProps) {
  const width = 860;
  const height = 360;
  const plot = {left: 58, right: 18, top: 18, bottom: 34};
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const [displayInterval, setDisplayInterval] = useState<CandleDisplayInterval>('1m');
  const displayCandles = useMemo(() => aggregateCandles(candles, displayInterval), [candles, displayInterval]);
  const displayMarkers = useMemo(() => aggregateMarkers(markers, displayInterval), [markers, displayInterval]);
  const [activeViewport, setViewport] = useState<CandleViewport>(() => defaultCandleViewport(displayCandles.length));
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const drag = useRef<CandleDragState | null>(null);

  const clampedViewport = clampCandleViewport(displayCandles.length, activeViewport);
  const startIndex = Math.max(0, clampedViewport.endIndex - clampedViewport.count);
  const visibleCandles = displayCandles.slice(startIndex, clampedViewport.endIndex);
  const visibleTimes = new Set(visibleCandles.map((c) => c.time));
  const visibleMarkers = displayMarkers.filter((m) => visibleTimes.has(m.time));
  const hoveredCandle = hoverIndex === null ? null : visibleCandles[hoverIndex] ?? null;

  useEffect(() => {
    setViewport(defaultCandleViewport(displayCandles.length));
    setHoverIndex(null);
  }, [displayCandles.length]);

  const updateViewport = (next: CandleViewport | ((c: CandleViewport) => CandleViewport)) => {
    setViewport((cur) => clampCandleViewport(displayCandles.length, typeof next === 'function' ? next(cur) : next));
  };

  const zoomAroundCenter = (ratio: number) => {
    updateViewport((cur) => {
      const n = clampCandleViewport(displayCandles.length, cur);
      const center = (n.endIndex - n.count) + n.count / 2;
      const nextCount = n.count * ratio;
      return {count: nextCount, endIndex: center + nextCount / 2};
    });
  };

  const panCandles = (delta: number) => updateViewport((cur) => ({...cur, endIndex: cur.endIndex + delta}));

  const updateHoverIndex = (event: ChartPointerEvent) => {
    if (visibleCandles.length === 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const chartX = (event.clientX - bounds.left) * (width / Math.max(1, bounds.width));
    const rawIndex = Math.round((chartX - plot.left) / Math.max(1, plotWidth) * Math.max(1, visibleCandles.length - 1));
    setHoverIndex(clampNumber(rawIndex, 0, visibleCandles.length - 1));
  };

  const handlePointerDown = (event: ChartPointerEvent) => {
    if (visibleCandles.length <= 1) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    drag.current = {chartWidth: bounds.width, startClientX: event.clientX, startEndIndex: clampedViewport.endIndex, visibleCount: clampedViewport.count};
    if (event.pointerId !== undefined) event.currentTarget.setPointerCapture?.(event.pointerId);
    updateHoverIndex(event);
  };

  const handlePointerMove = (event: ChartPointerEvent) => {
    updateHoverIndex(event);
    if (!drag.current) return;
    const candlePixelWidth = drag.current.chartWidth / Math.max(1, drag.current.visibleCount);
    const deltaBars = Math.round(-(event.clientX - drag.current.startClientX) / Math.max(1, candlePixelWidth));
    updateViewport({count: drag.current.visibleCount, endIndex: drag.current.startEndIndex + deltaBars});
  };

  const handlePointerUp = () => { drag.current = null; };

  const handleWheel = (event: ChartWheelEvent) => {
    if (displayCandles.length <= minimumVisibleCandles) return;
    event.preventDefault();
    zoomAroundCenter(event.deltaY > 0 ? 1.25 : 0.8);
  };

  if (visibleCandles.length === 0) {
    return (
      <section className="panel chart-panel">
        <div className="panel-header"><h3>{title}</h3><span>暂无数据</span></div>
        <div className="empty-chart">等待回测结果</div>
      </section>
    );
  }

  const lows = visibleCandles.map((c) => c.low);
  const highs = visibleCandles.map((c) => c.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const candleSlotWidth = plotWidth / Math.max(1, visibleCandles.length);
  const candleBodyWidth = clampNumber(candleSlotWidth * 0.56, 1.4, 10);
  const priceTicks = [max, min + range / 2, min];
  const timeTicks = [visibleCandles[0], visibleCandles[Math.floor((visibleCandles.length - 1) / 2)], visibleCandles[visibleCandles.length - 1]].filter(Boolean);

  const scaleY = (value: number) => plot.top + ((max - value) / range) * plotHeight;
  const xForIndex = (index: number) => plot.left + index * candleSlotWidth + candleSlotWidth / 2;

  return (
    <section className="panel chart-panel">
      <div className="panel-header chart-panel-header">
        <h3>{title}</h3>
        <div className="chart-header-meta">
          <span>{formatTimestamp(visibleCandles[0].time)} - {formatTimestamp(visibleCandles[visibleCandles.length - 1].time)} · {startIndex + 1}-{clampedViewport.endIndex}/{displayCandles.length}</span>
          <div className="chart-toolbar">
            <select className="chart-interval-select" value={displayInterval} onChange={(event: ValueEvent) => setDisplayInterval(event.target.value as CandleDisplayInterval)}>
              {candleDisplayOptions.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
            <button type="button" className="chart-tool" title="向前平移" onClick={() => panCandles(-Math.ceil(clampedViewport.count * 0.45))}>‹</button>
            <button type="button" className="chart-tool" title="缩小" onClick={() => zoomAroundCenter(1.35)}>-</button>
            <button type="button" className="chart-tool" title="放大" onClick={() => zoomAroundCenter(0.72)}>+</button>
            <button type="button" className="chart-tool" title="向后平移" onClick={() => panCandles(Math.ceil(clampedViewport.count * 0.45))}>›</button>
            <button type="button" className="chart-text-tool" onClick={() => updateViewport({count: displayCandles.length, endIndex: displayCandles.length})}>全部</button>
            <button type="button" className="chart-text-tool" onClick={() => updateViewport(defaultCandleViewport(displayCandles.length))}>重置</button>
          </div>
        </div>
      </div>
      <input className="chart-range" type="range" min={Math.max(1, clampedViewport.count)} max={Math.max(1, displayCandles.length)} value={Math.max(1, clampedViewport.endIndex)} onChange={(event: ValueEvent) => updateViewport({...clampedViewport, endIndex: Number(event.target.value)})} />
      <svg viewBox={`0 0 ${width} ${height}`} className={`candle-chart ${drag.current ? 'is-dragging' : ''}`} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} onPointerLeave={() => { handlePointerUp(); setHoverIndex(null); }} onWheel={handleWheel}>
        <rect className="chart-plot-bg" x={plot.left} y={plot.top} width={plotWidth} height={plotHeight} />
        {priceTicks.map((tick, i) => {
          const y = scaleY(tick);
          return (
            <g key={`${tick}-${i}`}>
              <line className="chart-grid-line" x1={plot.left} y1={y} x2={width - plot.right} y2={y} />
              <text className="axis-label price-label" x={plot.left - 8} y={y + 4}>{formatPrice(tick)}</text>
            </g>
          );
        })}
        {timeTicks.map((candle) => {
          const idx = visibleCandles.findIndex((c) => c.time === candle.time);
          return <text key={candle.time} className="axis-label time-label" x={xForIndex(Math.max(0, idx))} y={height - 8}>{formatTimestamp(candle.time)}</text>;
        })}
        {visibleCandles.map((candle, idx) => {
          const x = xForIndex(idx);
          const openY = scaleY(candle.open);
          const closeY = scaleY(candle.close);
          const rising = candle.close >= candle.open;
          const bodyTop = Math.min(openY, closeY);
          const bodyH = Math.max(2, Math.abs(closeY - openY));
          return (
            <g key={candle.time}>
              <line className="wick" x1={x} y1={scaleY(candle.high)} x2={x} y2={scaleY(candle.low)} />
              <rect className={rising ? 'candle-body candle-up' : 'candle-body candle-down'} x={x - candleBodyWidth / 2} y={bodyTop} width={candleBodyWidth} height={bodyH} rx={1.5} />
            </g>
          );
        })}
        {visibleMarkers.map((marker, mi) => {
          const idx = visibleCandles.findIndex((c) => c.time === marker.time);
          if (idx < 0) return null;
          const candle = visibleCandles[idx];
          const x = xForIndex(idx);
          const y = marker.position === 'aboveBar' ? Math.max(plot.top + 10, scaleY(candle.high) - 14) : Math.min(height - plot.bottom - 10, scaleY(candle.low) + 14);
          const pts = marker.position === 'aboveBar' ? `${x},${y - 10} ${x - 7},${y + 4} ${x + 7},${y + 4}` : `${x},${y + 10} ${x - 7},${y - 4} ${x + 7},${y - 4}`;
          return <polygon key={`${marker.time}-${marker.text}-${mi}`} points={pts} fill={marker.color} className="marker" />;
        })}
        {hoveredCandle ? (
          <g className="chart-hover-layer">
            <line className="chart-crosshair" x1={xForIndex(hoverIndex ?? 0)} y1={plot.top} x2={xForIndex(hoverIndex ?? 0)} y2={height - plot.bottom} />
            <g transform={`translate(${xForIndex(hoverIndex ?? 0) > width - 180 ? width - 212 : plot.left + 12}, ${plot.top + 12})`}>
              <rect className="chart-tooltip-box" width="190" height="86" rx="8" />
              <text className="chart-tooltip-text" x="10" y="20">{formatTimestamp(hoveredCandle.time)}</text>
              <text className="chart-tooltip-text muted" x="10" y="42">O {formatPrice(hoveredCandle.open)}  H {formatPrice(hoveredCandle.high)}</text>
              <text className="chart-tooltip-text muted" x="10" y="64">L {formatPrice(hoveredCandle.low)}  C {formatPrice(hoveredCandle.close)}</text>
            </g>
          </g>
        ) : null}
      </svg>
      <div className="marker-list">
        {visibleMarkers.slice(-4).map((marker, mi) => (
          <div key={`${marker.time}-${marker.text}-${mi}`} className="marker-pill">
            <span className="marker-dot" style={{backgroundColor: marker.color}} />
            <span>{formatTimestamp(marker.time)}</span>
            <span>{marker.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

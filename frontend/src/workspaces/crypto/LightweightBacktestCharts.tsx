import {useEffect, useRef} from 'react';
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

import type {ChartSeriesPayload} from '../../lib/view-model';

type ValuePoint = {time: number; value: number};

const chartOptions = {
  layout: {background: {type: ColorType.Solid, color: 'transparent'}, textColor: '#94a3b8'},
  grid: {vertLines: {color: 'rgba(148, 163, 184, 0.08)'}, horzLines: {color: 'rgba(148, 163, 184, 0.08)'}},
  rightPriceScale: {borderColor: 'rgba(148, 163, 184, 0.2)'},
  timeScale: {borderColor: 'rgba(148, 163, 184, 0.2)', timeVisible: true, secondsVisible: false},
  crosshair: {vertLine: {labelBackgroundColor: '#2563eb'}, horzLine: {labelBackgroundColor: '#2563eb'}},
};

function useResponsiveChart(build: (chart: IChartApi) => void, dependency: unknown) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = createChart(container, {...chartOptions, width: container.clientWidth, height: 280});
    build(chart);
    chart.timeScale().fitContent();
    const observer = new ResizeObserver((entries) => {
      const width = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (width > 0) chart.applyOptions({width});
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [dependency]);

  return containerRef;
}

export function LightweightAreaChart({title, points, color = '#38bdf8'}: {title: string; points: ValuePoint[]; color?: string}) {
  const normalized = points
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
    .sort((left, right) => left.time - right.time);
  const dependency = JSON.stringify(normalized);
  const containerRef = useResponsiveChart((chart) => {
    const series = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: `${color}55`,
      bottomColor: `${color}08`,
      lineWidth: 2,
    });
    series.setData(normalized.map((point) => ({time: point.time as Time, value: point.value})));
  }, dependency);

  return (
    <article className="panel lightweight-chart-card" data-testid={`lightweight-chart-${title}`}>
      <div className="panel-header"><h3>{title}</h3><span>{normalized.length} 点</span></div>
      {normalized.length ? <div ref={containerRef} className="lightweight-chart-canvas" /> : <div className="chart-empty-state">暂无可绘制数据</div>}
      <p className="chart-attribution">Charts by TradingView Lightweight Charts™</p>
    </article>
  );
}

export function LightweightCandlestickChart({candles, markers}: Pick<ChartSeriesPayload, 'candles' | 'markers'>) {
  const normalizedCandles = candles
    .filter((item) => [item.time, item.open, item.high, item.low, item.close].every(Number.isFinite))
    .sort((left, right) => left.time - right.time);
  const candleTimes = new Set(normalizedCandles.map((item) => item.time));
  const normalizedMarkers = markers
    .filter((item) => candleTimes.has(item.time))
    .sort((left, right) => left.time - right.time);
  const dependency = JSON.stringify([normalizedCandles, normalizedMarkers]);
  const containerRef = useResponsiveChart((chart) => {
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });
    series.setData(normalizedCandles.map((item) => ({...item, time: item.time as Time})));
    createSeriesMarkers(series, normalizedMarkers.map((item) => ({
      time: item.time as Time,
      position: item.position === 'aboveBar' ? 'aboveBar' : 'belowBar',
      color: item.color,
      shape: item.shape === 'arrowDown' ? 'arrowDown' : 'arrowUp',
      text: item.text,
    } as SeriesMarker<Time>)));
  }, dependency);

  return (
    <article className="panel lightweight-chart-card lightweight-candle-card" data-testid="lightweight-candles">
      <div className="panel-header"><h3>K 线与成交标记</h3><span>{normalizedCandles.length} 根 · {normalizedMarkers.length} 标记</span></div>
      {normalizedCandles.length ? <div ref={containerRef} className="lightweight-chart-canvas" /> : <div className="chart-empty-state">暂无 K 线；不会用模拟价格填充</div>}
      {markers.length > normalizedMarkers.length ? <p className="data-message">已忽略 {markers.length - normalizedMarkers.length} 个无法对齐 K 线时间戳的标记。</p> : null}
      <p className="chart-attribution">Charts by TradingView Lightweight Charts™</p>
    </article>
  );
}

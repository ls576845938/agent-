import {useEffect, useMemo, useRef} from 'react';
import {
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type Time,
} from 'lightweight-charts';
import {ChartLineUp} from '@phosphor-icons/react';

type Point = {time: number; value: number};

export default function EquityPerformanceChart({
  equity,
  drawdown,
}: {
  equity: Point[];
  drawdown: Point[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const normalized = useMemo(() => normalizeEquity(equity), [equity]);
  const normalizedDrawdown = useMemo(
    () => drawdown
      .filter((item) => Number.isFinite(item.time) && Number.isFinite(item.value))
      .sort((left, right) => left.time - right.time),
    [drawdown],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !normalized.length) return undefined;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 270,
      autoSize: false,
      layout: {
        background: {type: ColorType.Solid, color: '#0b0e14'},
        textColor: '#787b86',
        fontFamily: "Inter, 'Segoe UI', sans-serif",
          fontSize: 12,
      },
      grid: {
        vertLines: {color: 'rgba(120, 123, 134, 0.08)'},
        horzLines: {color: 'rgba(120, 123, 134, 0.08)'},
      },
      rightPriceScale: {
        borderColor: '#252a34',
        scaleMargins: {top: 0.08, bottom: 0.28},
      },
      timeScale: {
        borderColor: '#252a34',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
      },
      localization: {
        locale: 'zh-CN',
        priceFormatter: (value: number) => `${value.toFixed(2)}%`,
      },
    });
    const returnSeries = chart.addSeries(LineSeries, {
      color: '#2ebd85',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerRadius: 4,
    });
    returnSeries.setData(normalized.map((item) => ({time: item.time as Time, value: item.value})));

    if (normalizedDrawdown.length) {
      const drawdownSeries = chart.addSeries(HistogramSeries, {
        priceScaleId: 'drawdown',
        priceLineVisible: false,
        lastValueVisible: false,
      });
      drawdownSeries.priceScale().applyOptions({scaleMargins: {top: 0.74, bottom: 0}});
      drawdownSeries.setData(normalizedDrawdown.map((item) => ({
        time: item.time as Time,
        value: item.value,
        color: 'rgba(242, 54, 69, 0.28)',
      })));
    }

    chart.timeScale().fitContent();
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      const height = Math.floor(entry.contentRect.height);
      if (width > 0 && height > 0) chart.applyOptions({width, height});
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [normalized, normalizedDrawdown]);

  if (!normalized.length) {
    return (
      <div className="tv-report-chart-empty">
        <ChartLineUp size={26} weight="light" />
        <strong>等待 run-scoped equity series</strong>
        <span>不会用价格走势或模拟曲线冒充策略净值。</span>
      </div>
    );
  }
  return <div ref={containerRef} className="tv-equity-chart" data-testid="btc-equity-chart" />;
}

function normalizeEquity(points: Point[]): Point[] {
  const clean = points
    .filter((item) => Number.isFinite(item.time) && Number.isFinite(item.value))
    .sort((left, right) => left.time - right.time);
  const base = clean[0]?.value;
  if (!Number.isFinite(base) || base === 0) return [];
  return clean.map((item) => ({time: item.time, value: (item.value / base - 1) * 100}));
}

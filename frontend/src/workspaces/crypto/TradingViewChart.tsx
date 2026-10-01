import {useEffect, useMemo, useRef, useState} from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

import type {ChartDrawing, DrawingPoint, DrawingTool} from './canonical-report-types';

type ChartPointerEvent = {
  clientX: number;
  clientY: number;
  pointerId: number;
  currentTarget: HTMLCanvasElement;
};

type TextEditorState = {
  point: DrawingPoint;
  x: number;
  y: number;
  value: string;
};

type ValueEvent = {target: {value: string}};
type SubmitEvent = {preventDefault(): void};

export type TradingCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  in_progress?: boolean;
};

export type TradingMarker = {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
};

export default function TradingViewChart({
  candles,
  markers,
  loading,
  showVolume = true,
  showMarkers = true,
  showDonchian = true,
  showGrid = true,
  showCrosshair = true,
  chartType = 'candles',
  activeDrawingTool = 'cursor',
  drawings = [],
  drawingsLocked = false,
  drawingsHidden = false,
  onCommitDrawing,
}: {
  candles: TradingCandle[];
  markers: TradingMarker[];
  loading: boolean;
  showVolume?: boolean;
  showMarkers?: boolean;
  showDonchian?: boolean;
  showGrid?: boolean;
  showCrosshair?: boolean;
  chartType?: 'candles' | 'line';
  activeDrawingTool?: DrawingTool;
  drawings?: ChartDrawing[];
  drawingsLocked?: boolean;
  drawingsHidden?: boolean;
  onCommitDrawing?: (drawing: ChartDrawing) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const lineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const donchianSeriesRef = useRef<{upper: ISeriesApi<'Line'>; lower: ISeriesApi<'Line'>} | null>(null);
  const candleSignatureRef = useRef('');
  const renderRef = useRef<() => void>(() => undefined);
  const drawingsRef = useRef(drawings);
  const drawingsHiddenRef = useRef(drawingsHidden);
  const draftRef = useRef<ChartDrawing | null>(null);
  const [draft, setDraft] = useState<ChartDrawing | null>(null);
  const [textEditor, setTextEditor] = useState<TextEditorState | null>(null);
  drawingsRef.current = drawings;
  drawingsHiddenRef.current = drawingsHidden;
  draftRef.current = draft;

  const normalizedCandles = useMemo(() => {
    const byTime = new Map<number, TradingCandle>();
    candles.forEach((item) => {
      if ([item.time, item.open, item.high, item.low, item.close].every(Number.isFinite)) byTime.set(item.time, item);
    });
    return [...byTime.values()].sort((left, right) => left.time - right.time);
  }, [candles]);
  const normalizedMarkers = useMemo(() => {
    const times = new Set(normalizedCandles.map((item) => item.time));
    return markers.filter((item) => times.has(item.time)).sort((left, right) => left.time - right.time);
  }, [markers, normalizedCandles]);
  const visibleMarkerLabels = useMemo(
    () => (showMarkers ? normalizedMarkers.map((item) => item.text) : []),
    [normalizedMarkers, showMarkers],
  );
  const markerSignature = useMemo(
    () => normalizedMarkers.map((item) => `${item.time}:${item.position}:${item.shape}:${item.text}`).join('|'),
    [normalizedMarkers],
  );
  const hasCandles = normalizedCandles.length > 0;

  const updateVisibleRangeMetadata = () => {
    const chart = chartRef.current;
    const container = containerRef.current;
    const range = chart?.timeScale().getVisibleLogicalRange();
    if (!container || !range) return;
    container.dataset.visibleLogicalSpan = String(range.to - range.from);
    container.dataset.visibleLogicalCenter = String((range.from + range.to) / 2);
  };

  const fitVisibleRange = () => {
    chartRef.current?.timeScale().fitContent();
    window.requestAnimationFrame(updateVisibleRangeMetadata);
  };

  useEffect(() => {
    const container = containerRef.current;
    const overlay = overlayRef.current;
    if (loading || !container || !overlay || !normalizedCandles.length) return undefined;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 560,
      autoSize: false,
      layout: {
        background: {type: ColorType.Solid, color: '#0b0e14'},
        textColor: '#9ca3af',
        fontFamily: "Inter, 'Segoe UI', sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: {color: showGrid ? 'rgba(148, 163, 184, 0.055)' : 'transparent'},
        horzLines: {color: showGrid ? 'rgba(148, 163, 184, 0.055)' : 'transparent'},
      },
      crosshair: {
        mode: showCrosshair ? CrosshairMode.Normal : CrosshairMode.Hidden,
        vertLine: {color: '#6b7280', width: 1, labelBackgroundColor: '#2962ff'},
        horzLine: {color: '#6b7280', width: 1, labelBackgroundColor: '#2962ff'},
      },
      rightPriceScale: {
        borderColor: '#252a34',
        scaleMargins: {top: 0.08, bottom: 0.22},
      },
      timeScale: {
        borderColor: '#252a34',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
        // Keep the native zoom-out range usable even beside the narrow Demo dock.
        minBarSpacing: 0.5,
        fixLeftEdge: false,
        lockVisibleTimeRangeOnResize: true,
      },
      handleScroll: {mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false},
      handleScale: {axisPressedMouseMove: true, mouseWheel: true, pinch: true},
      localization: {locale: 'zh-CN'},
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#089981',
      downColor: '#f23645',
      borderVisible: false,
      wickUpColor: '#089981',
      wickDownColor: '#f23645',
      priceLineVisible: chartType === 'candles',
      priceLineColor: '#2962ff',
      lastValueVisible: chartType === 'candles',
      visible: chartType === 'candles',
    });
    candleSeries.setData(normalizedCandles.map((item) => ({
      time: item.time as Time,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
      color: item.in_progress ? '#f59e0b' : undefined,
      borderColor: item.in_progress ? '#fbbf24' : undefined,
      wickColor: item.in_progress ? '#fbbf24' : undefined,
    })));
    if (chartType === 'line') {
      const lineSeries = chart.addSeries(LineSeries, {
        color: '#2962ff',
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
        crosshairMarkerRadius: 4,
      });
      lineSeries.setData(normalizedCandles.map((item) => ({time: item.time as Time, value: item.close})));
      lineSeriesRef.current = lineSeries;
    }
    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: {type: 'volume'},
        priceScaleId: '',
        lastValueVisible: false,
        priceLineVisible: false,
      });
      volumeSeries.priceScale().applyOptions({scaleMargins: {top: 0.82, bottom: 0}});
      volumeSeries.setData(normalizedCandles.map((item) => ({
        time: item.time as Time,
        value: Number(item.volume ?? 0),
        color: item.close >= item.open ? 'rgba(8, 153, 129, 0.34)' : 'rgba(242, 54, 69, 0.34)',
      })));
      volumeSeriesRef.current = volumeSeries;
    }
    if (showDonchian) {
      const bands = donchianBands(normalizedCandles, 120);
      const upperSeries = chart.addSeries(LineSeries, {
        color: 'rgba(41, 98, 255, 0.72)',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const lowerSeries = chart.addSeries(LineSeries, {
        color: 'rgba(168, 85, 247, 0.64)',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      upperSeries.setData(bands.map((item) => ({time: item.time as Time, value: item.upper})));
      lowerSeries.setData(bands.map((item) => ({time: item.time as Time, value: item.lower})));
      donchianSeriesRef.current = {upper: upperSeries, lower: lowerSeries};
    }
    if (showMarkers) {
      createSeriesMarkers(candleSeries, normalizedMarkers.map((item) => ({
        ...item,
        time: item.time as Time,
      } as SeriesMarker<Time>)));
    }
    chart.timeScale().fitContent();
    chartRef.current = chart;
    priceSeriesRef.current = candleSeries;
    candleSeriesRef.current = candleSeries;
    candleSignatureRef.current = normalizedCandles.map((item) => item.time).join(':');

    const renderDrawings = () => {
      const context = overlay.getContext('2d');
      if (!context) return;
      const pixelRatio = window.devicePixelRatio || 1;
      const width = overlay.clientWidth;
      const height = overlay.clientHeight;
      if (overlay.width !== Math.round(width * pixelRatio) || overlay.height !== Math.round(height * pixelRatio)) {
        overlay.width = Math.round(width * pixelRatio);
        overlay.height = Math.round(height * pixelRatio);
      }
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, height);
      if (drawingsHiddenRef.current) return;
      [...drawingsRef.current, ...(draftRef.current ? [draftRef.current] : [])].forEach((drawing) => {
        drawChartDrawing(context, drawing, chart, candleSeries);
      });
    };
    renderRef.current = renderDrawings;
    const rangeHandler = () => window.requestAnimationFrame(() => {
      renderDrawings();
      updateVisibleRangeMetadata();
    });
    chart.timeScale().subscribeVisibleLogicalRangeChange(rangeHandler);
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      const height = Math.floor(entry.contentRect.height);
      if (width > 0 && height > 0) {
        chart.applyOptions({width, height});
        window.requestAnimationFrame(renderDrawings);
      }
    });
    observer.observe(container);
    window.requestAnimationFrame(() => {
      renderDrawings();
      updateVisibleRangeMetadata();
    });
    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeHandler);
      chartRef.current = null;
      priceSeriesRef.current = null;
      candleSeriesRef.current = null;
      lineSeriesRef.current = null;
      volumeSeriesRef.current = null;
      donchianSeriesRef.current = null;
      candleSignatureRef.current = '';
      renderRef.current = () => undefined;
      chart.remove();
    };
  }, [chartType, hasCandles, loading, markerSignature, showCrosshair, showDonchian, showGrid, showMarkers, showVolume]);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries || !normalizedCandles.length) return;
    const signature = normalizedCandles.map((item) => item.time).join(':');
    const latest = normalizedCandles[normalizedCandles.length - 1];
    const point = {
      time: latest.time as Time,
      open: latest.open,
      high: latest.high,
      low: latest.low,
      close: latest.close,
      color: latest.in_progress ? '#f59e0b' : undefined,
      borderColor: latest.in_progress ? '#fbbf24' : undefined,
      wickColor: latest.in_progress ? '#fbbf24' : undefined,
    };
    if (signature === candleSignatureRef.current) {
      candleSeries.update(point);
      lineSeriesRef.current?.update({time: latest.time as Time, value: latest.close});
      volumeSeriesRef.current?.update({
        time: latest.time as Time,
        value: Number(latest.volume ?? 0),
        color: latest.close >= latest.open ? 'rgba(8, 153, 129, 0.34)' : 'rgba(242, 54, 69, 0.34)',
      });
      const latestBand = donchianSeriesRef.current ? donchianBands(normalizedCandles, 120).at(-1) : undefined;
      if (latestBand && donchianSeriesRef.current) {
        donchianSeriesRef.current.upper.update({time: latestBand.time as Time, value: latestBand.upper});
        donchianSeriesRef.current.lower.update({time: latestBand.time as Time, value: latestBand.lower});
      }
    } else {
      candleSeries.setData(normalizedCandles.map((item) => ({
        time: item.time as Time,
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
        color: item.in_progress ? '#f59e0b' : undefined,
        borderColor: item.in_progress ? '#fbbf24' : undefined,
        wickColor: item.in_progress ? '#fbbf24' : undefined,
      })));
      lineSeriesRef.current?.setData(normalizedCandles.map((item) => ({time: item.time as Time, value: item.close})));
      volumeSeriesRef.current?.setData(normalizedCandles.map((item) => ({
        time: item.time as Time,
        value: Number(item.volume ?? 0),
        color: item.close >= item.open ? 'rgba(8, 153, 129, 0.34)' : 'rgba(242, 54, 69, 0.34)',
      })));
      if (donchianSeriesRef.current) {
        const bands = donchianBands(normalizedCandles, 120);
        donchianSeriesRef.current.upper.setData(bands.map((item) => ({time: item.time as Time, value: item.upper})));
        donchianSeriesRef.current.lower.setData(bands.map((item) => ({time: item.time as Time, value: item.lower})));
      }
      candleSignatureRef.current = signature;
    }
  }, [normalizedCandles]);

  useEffect(() => {
    window.requestAnimationFrame(() => renderRef.current());
  }, [draft, drawings, drawingsHidden]);

  useEffect(() => {
    if (activeDrawingTool !== 'text' || drawingsLocked || drawingsHidden) setTextEditor(null);
  }, [activeDrawingTool, drawingsHidden, drawingsLocked]);

  const pointFromPointer = (event: ChartPointerEvent): DrawingPoint | null => {
    const chart = chartRef.current;
    const priceSeries = priceSeriesRef.current;
    const overlay = overlayRef.current;
    if (!chart || !priceSeries || !overlay) return null;
    const rect = overlay.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const time = chart.timeScale().coordinateToTime(x);
    const price = priceSeries.coordinateToPrice(y);
    if (typeof time !== 'number' || price === null || !Number.isFinite(price)) return null;
    return {time, price: Number(price)};
  };

  const updateDraft = (next: ChartDrawing | null) => {
    draftRef.current = next;
    setDraft(next);
  };

  const handlePointerDown = (event: ChartPointerEvent) => {
    if (activeDrawingTool === 'cursor' || drawingsLocked || drawingsHidden) return;
    const point = pointFromPointer(event);
    if (!point) return;
    if (activeDrawingTool === 'text') {
      const rect = event.currentTarget.getBoundingClientRect();
      setTextEditor({
        point,
        x: Math.min(Math.max(8, event.clientX - rect.left + 12), Math.max(8, rect.width - 248)),
        y: Math.min(Math.max(8, event.clientY - rect.top + 12), Math.max(8, rect.height - 96)),
        value: '',
      });
      return;
    }

    const current = draftRef.current;
    if (current && current.tool === activeDrawingTool && current.tool !== 'pencil') {
      const completed = {...current, points: [current.points[0], point]};
      if (drawingDistance(completed.points) > 0) onCommitDrawing?.(completed);
      updateDraft(null);
      return;
    }

    updateDraft({
      id: crypto.randomUUID(),
      tool: activeDrawingTool,
      points: activeDrawingTool === 'pencil' ? [point] : [point, point],
    });
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {}
  };

  const handlePointerMove = (event: ChartPointerEvent) => {
    const current = draftRef.current;
    if (!current) return;
    const point = pointFromPointer(event);
    if (!point) return;
    if (current.tool === 'pencil') {
      const last = current.points.at(-1);
      if (last && last.time === point.time && Math.abs(last.price - point.price) < 0.01) return;
      updateDraft({...current, points: [...current.points, point]});
    } else {
      updateDraft({...current, points: [current.points[0], point]});
    }
  };

  const handlePointerUp = (event: ChartPointerEvent) => {
    const current = draftRef.current;
    if (!current) return;
    try {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {}
    const valid = current.tool === 'pencil' ? current.points.length > 1 : drawingDistance(current.points) > 0;
    if (valid) {
      onCommitDrawing?.(current);
      updateDraft(null);
      return;
    }
    if (current.tool === 'pencil') updateDraft(null);
  };

  const submitTextDrawing = (event: SubmitEvent) => {
    event.preventDefault();
    if (!textEditor?.value.trim()) return;
    onCommitDrawing?.({
      id: crypto.randomUUID(),
      tool: 'text',
      points: [textEditor.point],
      text: textEditor.value.trim(),
    });
    setTextEditor(null);
  };

  if (loading) return <div className="tv-chart-empty">正在读取本地 completed 1h K 线…</div>;
  if (!normalizedCandles.length) return <div className="tv-chart-empty">本地 K 线不可用；不会用模拟数据填充。</div>;
  const drawingEnabled = activeDrawingTool !== 'cursor' && !drawingsLocked && !drawingsHidden;
  return (
    <div
      className="tv-chart-stack"
      data-drawing-count={drawings.length}
      data-drawing-draft={draft?.tool ?? ''}
      data-drawing-draft-start={draft ? `${draft.points[0]?.time ?? ''}:${draft.points[0]?.price ?? ''}` : ''}
      data-text-editor-open={textEditor ? 'true' : 'false'}
    >
      <span
        className="visually-hidden"
        role="img"
        aria-label={`成交标记摘要：${visibleMarkerLabels.length ? visibleMarkerLabels.join('；') : '无'}`}
        data-testid="trading-chart-marker-summary"
        data-marker-count={visibleMarkerLabels.length}
        data-marker-labels={visibleMarkerLabels.join('|')}
      />
      <div
        ref={containerRef}
        className="tv-chart-canvas"
        data-testid="btc-trading-chart"
        onDoubleClick={fitVisibleRange}
      />
      <canvas
        ref={overlayRef}
        className={`tv-drawing-canvas ${drawingEnabled ? 'active' : ''}`}
        data-testid="btc-drawing-layer"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => updateDraft(null)}
      />
      {activeDrawingTool === 'text' && !textEditor ? (
        <div className="tv-text-annotation-hint" role="status">文本工具已启用 · 点击图表放置注释</div>
      ) : null}
      {textEditor ? (
        <form
          className="tv-text-annotation-editor"
          style={{left: textEditor.x, top: textEditor.y}}
          aria-label="添加文本注释"
          onSubmit={submitTextDrawing}
        >
          <strong>文本注释</strong>
          <input
            autoFocus
            aria-label="注释内容"
            placeholder="输入注释，按 Enter 保存"
            value={textEditor.value}
            onChange={(event: ValueEvent) => setTextEditor((current) => current ? {...current, value: event.target.value} : current)}
          />
          <div>
            <button type="button" onClick={() => setTextEditor(null)}>取消</button>
            <button type="submit" className="primary" disabled={!textEditor.value.trim()}>添加注释</button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

function drawChartDrawing(
  context: CanvasRenderingContext2D,
  drawing: ChartDrawing,
  chart: IChartApi,
  series: ISeriesApi<'Candlestick'>,
) {
  const points = drawing.points.map((point) => {
    const x = chart.timeScale().timeToCoordinate(point.time as Time);
    const y = series.priceToCoordinate(point.price);
    return x === null || y === null ? null : {x: Number(x), y: Number(y), source: point};
  });
  if (!points.length || points.some((point) => point === null)) return;
  const clean = points.filter((point): point is NonNullable<typeof point> => point !== null);
  const first = clean[0];
  const last = clean.at(-1) ?? first;
  context.save();
  context.lineCap = 'round';
  context.lineJoin = 'round';

  if (drawing.tool === 'pencil') {
    context.strokeStyle = '#f5a623';
    context.lineWidth = 2;
    context.beginPath();
    clean.forEach((point, index) => index ? context.lineTo(point.x, point.y) : context.moveTo(point.x, point.y));
    context.stroke();
  } else if (drawing.tool === 'target') {
    const delta = last.source.price - first.source.price;
    const stopPrice = first.source.price - delta / 2;
    const stopY = series.priceToCoordinate(stopPrice);
    if (stopY !== null) {
      const left = Math.min(first.x, last.x);
      const width = Math.max(26, Math.abs(last.x - first.x));
      context.fillStyle = 'rgba(8, 153, 129, 0.22)';
      context.fillRect(left, Math.min(first.y, last.y), width, Math.abs(last.y - first.y));
      context.fillStyle = 'rgba(242, 54, 69, 0.22)';
      context.fillRect(left, Math.min(first.y, Number(stopY)), width, Math.abs(Number(stopY) - first.y));
      context.strokeStyle = '#d1d4dc';
      context.lineWidth = 1;
      context.strokeRect(left, Math.min(first.y, last.y), width, Math.abs(last.y - first.y));
      context.strokeRect(left, Math.min(first.y, Number(stopY)), width, Math.abs(Number(stopY) - first.y));
      drawLabel(context, left + 6, first.y - 18, `R:R 2.00  目标 ${percentDelta(first.source.price, last.source.price)}`);
      drawLabel(context, left + 6, Number(stopY) + 4, `止损 ${percentDelta(first.source.price, stopPrice)}`);
    }
  } else if (drawing.tool === 'text') {
    drawLabel(context, first.x + 6, first.y - 10, drawing.text || '注释');
    drawAnchor(context, first.x, first.y, '#f5a623');
  } else {
    context.strokeStyle = drawing.tool === 'measure' ? '#f5a623' : '#2962ff';
    context.lineWidth = drawing.tool === 'trend' ? 2 : 1.5;
    if (drawing.tool === 'measure') context.setLineDash([5, 4]);
    context.beginPath();
    context.moveTo(first.x, first.y);
    context.lineTo(last.x, last.y);
    context.stroke();
    drawAnchor(context, first.x, first.y, context.strokeStyle.toString());
    drawAnchor(context, last.x, last.y, context.strokeStyle.toString());
    if (drawing.tool === 'measure') {
      const hours = Math.round(Math.abs(last.source.time - first.source.time) / 3600);
      drawLabel(
        context,
        (first.x + last.x) / 2 + 8,
        (first.y + last.y) / 2 - 8,
        `${percentDelta(first.source.price, last.source.price)} · ${hours}h · ${Math.max(1, hours)} bars`,
      );
    }
  }
  context.restore();
}

function drawAnchor(context: CanvasRenderingContext2D, x: number, y: number, color: string) {
  context.fillStyle = '#0b0e14';
  context.strokeStyle = color;
  context.lineWidth = 1.5;
  context.beginPath();
  context.arc(x, y, 3.5, 0, Math.PI * 2);
  context.fill();
  context.stroke();
}

function drawLabel(context: CanvasRenderingContext2D, x: number, y: number, text: string) {
  context.font = "12px Inter, 'Segoe UI', sans-serif";
  const width = context.measureText(text).width + 12;
  context.fillStyle = 'rgba(19, 23, 34, 0.94)';
  context.fillRect(x, y, width, 22);
  context.strokeStyle = '#434651';
  context.lineWidth = 1;
  context.strokeRect(x, y, width, 22);
  context.fillStyle = '#d1d4dc';
  context.fillText(text, x + 6, y + 15);
}

function drawingDistance(points: DrawingPoint[]): number {
  const first = points[0];
  const last = points.at(-1);
  if (!first || !last) return 0;
  return Math.abs(first.time - last.time) + Math.abs(first.price - last.price);
}

function percentDelta(start: number, end: number): string {
  if (!start) return '—';
  const value = (end / start - 1) * 100;
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function donchianBands(candles: TradingCandle[], period: number): Array<{time: number; upper: number; lower: number}> {
  if (candles.length < period) return [];
  return candles.slice(period - 1).map((item, index) => {
    const window = candles.slice(index, index + period);
    return {
      time: item.time,
      upper: Math.max(...window.map((candle) => candle.high)),
      lower: Math.min(...window.map((candle) => candle.low)),
    };
  });
}

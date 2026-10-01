import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {ChartBar} from '@phosphor-icons/react';

import type {CanonicalCost, CanonicalMonthlyReturn, CanonicalReportPoint, CanonicalTrade} from './canonical-report-types';

const GRID = 'rgba(120, 123, 134, 0.14)';
const TEXT = '#787b86';
const GOOD = '#089981';
const BAD = '#f23645';
const BLUE = '#2962ff';

export function TradePnlChart({trades}: {trades: CanonicalTrade[]}) {
  if (!trades.length) return <ChartEmpty label="等待逐笔 fills / ledger 交易周期" />;
  const data = trades.map((trade) => ({
    name: `#${trade.trade_number}`,
    pnl: trade.net_pnl,
    cumulative: trade.cumulative_pnl,
    direction: trade.direction === 'long' ? '做多' : '做空',
  }));
  return (
    <div className="tv-analytics-chart" data-testid="btc-trade-pnl-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{top: 12, right: 12, bottom: 2, left: 2}}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={{fill: TEXT, fontSize: 12}} axisLine={{stroke: GRID}} tickLine={false} />
          <YAxis tick={{fill: TEXT, fontSize: 12}} axisLine={false} tickLine={false} tickFormatter={compactMoney} width={52} />
          <Tooltip contentStyle={tooltipStyle} formatter={moneyTooltip} />
          <Legend wrapperStyle={{fontSize: 12, color: TEXT}} />
          <Bar dataKey="pnl" name="单笔净 PnL" radius={[2, 2, 0, 0]}>
            {data.map((item) => <Cell key={item.name} fill={item.pnl >= 0 ? GOOD : BAD} />)}
          </Bar>
          <Line dataKey="cumulative" name="累计 PnL" stroke={BLUE} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MonthlyReturnsChart({returns}: {returns: CanonicalMonthlyReturn[]}) {
  if (!returns.length) return <ChartEmpty label="等待 ledger 月末净值序列" />;
  return (
    <div className="tv-analytics-chart" data-testid="btc-monthly-returns-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={returns} margin={{top: 12, right: 10, bottom: 2, left: 0}}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="month" tick={{fill: TEXT, fontSize: 12}} interval="preserveStartEnd" axisLine={{stroke: GRID}} tickLine={false} />
          <YAxis tick={{fill: TEXT, fontSize: 12}} axisLine={false} tickLine={false} tickFormatter={(value: number) => `${value.toFixed(0)}%`} width={40} />
          <Tooltip contentStyle={tooltipStyle} formatter={percentTooltip} />
          <Bar dataKey="value" name="月收益" radius={[2, 2, 0, 0]}>
            {returns.map((item) => <Cell key={item.month} fill={item.value >= 0 ? GOOD : BAD} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CostBreakdownChart({costs}: {costs: CanonicalCost[]}) {
  if (!costs.length) return <ChartEmpty label="等待成本模型分项" />;
  const colors = ['#2962ff', '#7c3aed', '#f59e0b', '#f23645'];
  return (
    <div className="tv-analytics-chart" data-testid="btc-cost-breakdown-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={costs} layout="vertical" margin={{top: 8, right: 18, bottom: 4, left: 8}}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={{fill: TEXT, fontSize: 12}} axisLine={{stroke: GRID}} tickLine={false} tickFormatter={compactMoney} />
          <YAxis type="category" dataKey="label" tick={{fill: TEXT, fontSize: 12}} axisLine={false} tickLine={false} width={64} />
          <Tooltip contentStyle={tooltipStyle} formatter={moneyTooltip} />
          <Bar dataKey="value" name="成本" radius={[0, 3, 3, 0]}>
            {costs.map((item, index) => <Cell key={item.key} fill={colors[index % colors.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TradeOutcomeDonut({trades}: {trades: CanonicalTrade[]}) {
  if (!trades.length) return <ChartEmpty label="等待闭合交易样本" />;
  const winners = trades.filter((trade) => trade.net_pnl > 0).length;
  const losers = trades.filter((trade) => trade.net_pnl < 0).length;
  const flat = trades.length - winners - losers;
  const data = [
    {name: '盈利', value: winners, fill: GOOD},
    {name: '亏损', value: losers, fill: BAD},
    {name: '持平', value: flat, fill: '#787b86'},
  ].filter((item) => item.value > 0);
  return (
    <div className="tv-analytics-chart tv-donut-chart" data-testid="btc-trade-outcome-chart">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="56%" outerRadius="82%" paddingAngle={2}>
            {data.map((item) => <Cell key={item.name} fill={item.fill} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} />
          <Legend verticalAlign="bottom" wrapperStyle={{fontSize: 12, color: TEXT}} />
          <text x="50%" y="45%" textAnchor="middle" dominantBaseline="middle" fill="#d1d4dc" fontSize="22" fontWeight="700">{trades.length}</text>
          <text x="50%" y="55%" textAnchor="middle" dominantBaseline="middle" fill={TEXT} fontSize="12">闭合交易</text>
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DrawdownChart({drawdown}: {drawdown: CanonicalReportPoint[]}) {
  if (!drawdown.length) return <ChartEmpty label="等待 ledger drawdown 序列" />;
  const data = drawdown.map((point) => ({time: formatDate(point.time), value: point.value}));
  return (
    <div className="tv-analytics-chart" data-testid="btc-drawdown-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{top: 12, right: 10, bottom: 2, left: 0}}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="time" tick={{fill: TEXT, fontSize: 12}} interval="preserveStartEnd" axisLine={{stroke: GRID}} tickLine={false} />
          <YAxis tick={{fill: TEXT, fontSize: 12}} axisLine={false} tickLine={false} tickFormatter={(value: number) => `${value.toFixed(0)}%`} width={42} />
          <Tooltip contentStyle={tooltipStyle} formatter={percentTooltip} />
          <Area dataKey="value" name="回撤" stroke={BAD} fill="rgba(242, 54, 69, 0.22)" strokeWidth={1.5} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartEmpty({label}: {label: string}) {
  return <div className="tv-analytics-empty"><ChartBar size={24} weight="light" /><strong>{label}</strong><span>缺失证据保持空白，不生成模拟曲线。</span></div>;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toISOString().slice(0, 10);
}

function compactMoney(value: number): string {
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (absolute >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

function moneyTooltip(value: unknown): [string, string] {
  return [`${Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 2})} USDT`, ''];
}

function percentTooltip(value: unknown): [string, string] {
  return [`${Number(value).toFixed(2)}%`, ''];
}

const tooltipStyle = {
  background: '#131722',
  border: '1px solid #2a2e39',
  borderRadius: 4,
  color: '#d1d4dc',
  fontSize: 12,
};

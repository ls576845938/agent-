create schema if not exists quant;

create table if not exists quant.instruments (
    symbol text primary key,
    asset_id text,
    exchange text,
    name text,
    asset_type text not null,
    currency text not null default 'USD',
    listing_date date,
    delisting_date date,
    is_active boolean not null default true,
    sector text,
    industry text
);

create table if not exists quant.bars_1d (
    timestamp timestamptz not null,
    symbol text not null references quant.instruments(symbol),
    open double precision not null,
    high double precision not null,
    low double precision not null,
    close double precision not null,
    volume double precision not null,
    vwap double precision,
    adjusted_close double precision,
    source text not null,
    primary key (timestamp, symbol, source)
);

create table if not exists quant.bars_1m (
    timestamp timestamptz not null,
    symbol text not null references quant.instruments(symbol),
    open double precision not null,
    high double precision not null,
    low double precision not null,
    close double precision not null,
    volume double precision not null,
    vwap double precision,
    trade_count integer,
    session text not null,
    source text not null,
    primary key (timestamp, symbol, source)
);

create table if not exists quant.corporate_actions (
    symbol text not null references quant.instruments(symbol),
    action_type text not null,
    ex_date date not null,
    ratio double precision,
    cash_amount double precision,
    source text not null,
    primary key (symbol, action_type, ex_date, source)
);

create table if not exists quant.factor_values (
    date date not null,
    symbol text not null references quant.instruments(symbol),
    factor_name text not null,
    value double precision not null,
    universe text not null,
    version text not null,
    created_at timestamptz not null,
    primary key (date, symbol, factor_name, universe, version)
);

create table if not exists quant.signals (
    timestamp timestamptz not null,
    signal_id text primary key,
    strategy_id text not null,
    symbol text not null,
    signal_type text not null,
    signal_value double precision not null,
    confidence double precision
);

create table if not exists quant.target_positions (
    timestamp timestamptz not null,
    target_position_id text primary key,
    strategy_id text not null,
    symbol text not null,
    target_weight double precision not null,
    target_quantity double precision
);

create table if not exists quant.orders (
    order_id text primary key,
    client_order_id text unique not null,
    strategy_id text not null,
    run_id text,
    signal_id text,
    risk_check_id text,
    broker_order_id text,
    symbol text not null,
    side text not null,
    order_type text not null,
    quantity double precision not null,
    limit_price double precision,
    status text not null,
    broker text,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists quant.fills (
    fill_id text primary key,
    order_id text not null references quant.orders(order_id),
    symbol text not null,
    side text not null,
    quantity double precision not null,
    price double precision not null,
    commission double precision not null,
    filled_at timestamptz not null,
    broker text,
    broker_order_id text
);

create table if not exists quant.positions (
    timestamp timestamptz not null,
    account_id text not null,
    symbol text not null,
    quantity double precision not null,
    avg_price double precision not null,
    market_price double precision not null,
    unrealized_pnl double precision not null,
    primary key (timestamp, account_id, symbol)
);

create table if not exists quant.portfolio_snapshots (
    timestamp timestamptz not null,
    account_id text not null default 'default',
    equity double precision not null,
    cash double precision not null,
    gross_exposure double precision not null,
    net_exposure double precision not null,
    daily_pnl double precision not null,
    drawdown double precision not null,
    primary key (timestamp, account_id)
);

create table if not exists quant.experiments (
    experiment_id text primary key,
    run_id text not null,
    experiment_name text not null,
    run_type text not null,
    status text not null,
    symbols jsonb not null,
    strategy_id text,
    strategy_version text,
    data_vendor text,
    asset_class text,
    bar_size text,
    feature_version text,
    dataset_run_id text,
    model_id text,
    parameters jsonb not null default '{}'::jsonb,
    metrics jsonb not null default '{}'::jsonb,
    artifacts jsonb not null default '[]'::jsonb,
    tags jsonb not null default '[]'::jsonb,
    notes text,
    created_at timestamptz not null,
    completed_at timestamptz,
    error text
);

create table if not exists quant.model_artifacts (
    model_id text primary key,
    model_type text not null,
    path text not null,
    feature_names jsonb not null,
    feature_version text not null,
    dataset_run_id text,
    metrics jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null
);

create index if not exists idx_bars_1d_symbol_time on quant.bars_1d(symbol, timestamp desc);
create index if not exists idx_bars_1m_symbol_time on quant.bars_1m(symbol, timestamp desc);
create index if not exists idx_factor_values_name_date on quant.factor_values(factor_name, date desc);
create index if not exists idx_orders_status_created on quant.orders(status, created_at desc);
create index if not exists idx_experiments_name_created on quant.experiments(experiment_name, created_at desc);
create index if not exists idx_experiments_run_id on quant.experiments(run_id);

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import socket

import pandas as pd
import pytest

from quant_crypto.application.donchian_history_spec import HistorySpec, legacy_spec, validate_tables
from quant_crypto.application.donchian_historical_replay import DonchianHistoricalReplay
from quant_crypto.application import donchian_historical_replay as history_module
from quant_crypto.application.donchian_offline_replay import DonchianOfflineReplay, DonchianOfflineReplayConfig, build_trend_frame
from quant_crypto.application.donchian_historical_venue import HistoricalOfflineVenue, HistoricalBar, HistoricalFundingEvent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('historical replay must not access network')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def test_spec_is_immutable_and_preserves_original_units():
    spec = legacy_spec()
    payload = spec.payload
    payload['execution']['order_contracts'] = '100'
    assert spec.payload['execution']['order_contracts'] == '0.01'
    assert spec.payload['execution']['contract_value_btc'] == '0.01'
    assert spec.signal_rows == 168
    assert spec.warmup_rows == 5112


@pytest.mark.parametrize('section,key,value', [
    ('execution', 'order_contracts', '0.02'),
    ('execution', 'account_equity_usdt', '10000'),
    ('execution', 'terminal', 'force_close'),
    ('strategy', 'params_hash', '0' * 64),
    ('window', 'warmup_start', '2026-07-01T00:00:00+00:00'),
    ('window', 'evaluation_start', '2026-07-23T00:30:00+00:00'),
    ('window', 'evaluation_end', '2026-07-23T00:00:00+00:00'),
    ('window', 'evaluation_start', '2026-07-23T00:00:00'),
    ('data', 'manifest_git_spec', 'HEAD:.agent/data_manifests/latest.json'),
    ('data', 'prefix', '../outside'),
])
def test_invalid_spec_rejected_before_creating_state(section, key, value):
    payload = legacy_spec().payload
    payload[section][key] = value
    with pytest.raises(ValueError):
        HistorySpec.from_payload(payload)


def test_changed_dates_bind_distinct_identity_and_full_days_required():
    payload = legacy_spec().payload
    payload['window']['evaluation_start'] = '2026-07-10T00:00:00+00:00'
    spec = HistorySpec.from_payload(payload)
    assert spec.signal_rows == 480
    assert spec.warmup_rows == 4800
    assert spec.digest != legacy_spec().digest
    payload['window']['warmup_start'] = '2025-12-22T01:00:00+00:00'
    with pytest.raises(ValueError, match='warmup'):
        HistorySpec.from_payload(payload)


@pytest.mark.parametrize('change', ['interval', 'data_hash', 'manifest', 'source_head'])
def test_changed_identity_cannot_resume_existing_run(tmp_path, monkeypatch, change):
    monkeypatch.setattr(history_module, 'load_historical_input', lambda *args, **kwargs: None)
    first = DonchianHistoricalReplay(repo_root=Path.cwd(), output_root=tmp_path, run_id='immutable-resume-test')
    first.run_root.mkdir()
    first._load_or_create_artifact()
    payload = legacy_spec().payload
    if change == 'interval':
        payload['window']['evaluation_start'] = '2026-07-10T00:00:00+00:00'
    elif change == 'data_hash':
        payload['data']['files']['daily_bars.parquet'] = 'a' * 64
    elif change == 'manifest':
        payload['data']['manifest_sha256'] = 'b' * 64
    monkeypatch.setattr(history_module, 'legacy_spec', lambda: HistorySpec.from_payload(payload))
    if change == 'source_head':
        monkeypatch.setattr(history_module.subprocess, 'check_output', lambda *args, **kwargs: 'c' * 40)
    other = DonchianHistoricalReplay(repo_root=Path.cwd(), output_root=tmp_path, run_id='immutable-resume-test')
    with pytest.raises(ValueError, match='historical_run_identity_mismatch'):
        other._load_or_create_artifact()
    assert not (first.run_root/'state').exists()


def test_nonimmutable_spec_reference_rejected_without_git_read(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('mutable reference must not be resolved')
    monkeypatch.setattr(history_module.subprocess, 'check_output', deny)
    with pytest.raises(ValueError, match='exact_commit'):
        HistorySpec.from_git(tmp_path, 'HEAD:docs/research/latest.json')


def _tables(spec):
    times = pd.date_range(spec.warmup_start, spec.end - timedelta(hours=1), freq='h')
    common = {'event_time': times, 'available_time': times + pd.Timedelta(hours=1),
              'symbol': 'BTC-USDT-SWAP', 'source_symbol': 'BTCUSDT', 'confirm': 1}
    prices = {'open': 60000., 'high': 60100., 'low': 59900., 'close': 60000.}
    def ids(prefix, stamps):
        return [f'{prefix}:BTC-USDT-SWAP:{stamp.value // 1000000}' for stamp in stamps]
    bars = pd.DataFrame({**common, **prices, 'volume_base': 1., 'volume': 1., 'source_record_id': ids('okx', times)})
    marks = pd.DataFrame({**common, **prices, 'source_record_id': ids('okx-mark', times)})
    premium = pd.DataFrame({**common, 'mark_close': 60000., 'index_close': 60000., 'source_record_id': ids('okx-premium', times)})
    settlements = pd.date_range(spec.start, spec.end, freq='8h')
    funding = pd.DataFrame({'event_time': settlements, 'available_time': settlements,
                            'symbol': 'BTC-USDT-SWAP', 'source_symbol': 'BTCUSDT',
                            'instId': 'BTC-USDT-SWAP', 'fundingRate': .0001, 'markPrice': 60000.,
                            'source_record_id': ids('okx-funding', settlements)})
    return [bars, marks, premium, funding]


def test_complete_interval_with_distinct_warmup_and_funding_passes():
    spec = legacy_spec()
    result = validate_tables(spec, *_tables(spec))
    assert len(result[0]) == 5280


@pytest.mark.parametrize('problem', ['missing_hour', 'duplicate_mark', 'future_index', 'missing_funding', 'wrong_symbol', 'wrong_source_id', 'bad_price'])
def test_content_checks_do_not_trust_row_count_or_manifest(problem):
    spec = legacy_spec()
    tables = _tables(spec)
    if problem == 'missing_hour':
        tables[0] = tables[0].drop(index=200)
    elif problem == 'duplicate_mark':
        tables[1] = pd.concat([tables[1], tables[1].iloc[-1:]])
    elif problem == 'future_index':
        tables[2].loc[100, 'available_time'] += pd.Timedelta(hours=1)
    elif problem == 'missing_funding':
        tables[3] = tables[3].drop(index=2)
    elif problem == 'wrong_symbol':
        tables[0].loc[0, 'symbol'] = 'ETH-USDT-SWAP'
    elif problem == 'wrong_source_id':
        tables[0].loc[0, 'source_record_id'] = 'okx:ETH-USDT-SWAP:0'
    else:
        tables[0].loc[0, 'low'] = 70000.
    with pytest.raises(ValueError):
        validate_tables(spec, *tables)


@pytest.mark.parametrize('terminal_case', ['nonflat', 'protection_fill', 'ledger_before_evidence_restart'])
def test_terminal_reconciliation_keeps_nonflat_position_and_no_new_order(tmp_path, terminal_case):
    completed = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    def factory(path, now):
        venue = HistoricalOfflineVenue(path, now=now)
        if not venue.state['historical_events']:
            venue.now = completed + timedelta(seconds=1)
            venue.advance(completed_bar=HistoricalBar(
                event_time_utc=completed-timedelta(hours=1), available_time_utc=completed,
                open=Decimal('60000'), high=Decimal('60001'), low=Decimal('59999'), close=Decimal('60000'),
                mark_open=Decimal('60000'), mark_high=Decimal('60001'), mark_low=Decimal('59999'), mark_close=Decimal('60000'), index_close=Decimal('60000')),
                next_bar_open=Decimal('60000'))
        return venue
    config = DonchianOfflineReplayConfig(repo_root=Path.cwd(), state_dir=tmp_path/'state',
        run_id='spec-terminal-nonflat', decision_time_utc=completed,
        data_version='explicit-terminal-test-only', venue_factory=factory,
        decision_time_provider=lambda event, ordinal, phase: event+timedelta(seconds=1, milliseconds=ordinal))
    runner = DonchianOfflineReplay(config)
    frame = build_trend_frame('long', end=completed)
    opened = runner.run_frame(frame)
    assert opened['fill_count'] == 1
    terminal = completed+timedelta(hours=1)
    runner.venue.now = terminal+timedelta(seconds=1)
    runner.venue.advance(completed_bar=HistoricalBar(
        event_time_utc=completed, available_time_utc=terminal,
        open=Decimal('60000'), high=Decimal('60060'), low=Decimal('59999'), close=Decimal('60050'),
        mark_open=Decimal('60000'), mark_high=Decimal('60060'), mark_low=Decimal('59999'), mark_close=Decimal('60050'), index_close=Decimal('60050')),
        next_bar_open=None, funding_events=(HistoricalFundingEvent(terminal,terminal,Decimal('.0001'),Decimal('60050'),'terminal-08','reported_mark_price'),))
    if terminal_case == 'protection_fill':
        # Protection existed before this NEXT bar opened. No invented ordering
        # within the bar where the original opening order was created.
        start = terminal
        terminal += timedelta(hours=1)
        runner.venue.now = terminal + timedelta(seconds=1)
        runner.venue.advance(completed_bar=HistoricalBar(
            event_time_utc=start, available_time_utc=terminal,
            open=Decimal('59000'), high=Decimal('59100'), low=Decimal('58900'), close=Decimal('59000'),
            mark_open=Decimal('59000'), mark_high=Decimal('59100'), mark_low=Decimal('58900'), mark_close=Decimal('59000'), index_close=Decimal('59000')),
            next_bar_open=None)
    before = deepcopy(runner.venue.state)
    if terminal_case == 'ledger_before_evidence_restart':
        with pytest.raises(RuntimeError, match='injected_terminal_ledger_before_evidence_crash'):
            runner.reconcile_terminal_observation(completed_bar=terminal, observation_time=runner.venue.now, fail_after_ledger_before_evidence=True)
        runner.close()
        runner = DonchianOfflineReplay(replace(config, decision_time_utc=terminal))
        runner.venue.now = terminal + timedelta(seconds=1)
    receipt = runner.reconcile_terminal_observation(completed_bar=terminal, observation_time=runner.venue.now)
    again = runner.reconcile_terminal_observation(completed_bar=terminal, observation_time=runner.venue.now)
    assert receipt == again
    assert runner.venue.state == before
    assert receipt['ledger_event_hash']
    assert receipt['position_contracts'] == ('0' if terminal_case == 'protection_fill' else '0.01')
    assert receipt['funding_cashflow_usdt'] != '0'
    runner.close()


def test_original_signal_open_then_same_bar_attached_stop_reconciles_authoritative_ledger(tmp_path):
    opening = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    path = tmp_path/'state'
    def factory(venue_path, now):
        venue = HistoricalOfflineVenue(venue_path, now=now)
        if not venue.state['historical_events']:
            venue.now = opening + timedelta(seconds=1)
            venue.advance(completed_bar=HistoricalBar(
                event_time_utc=opening-timedelta(hours=1), available_time_utc=opening,
                open=Decimal('60000'), high=Decimal('60001'), low=Decimal('59999'), close=Decimal('60000'),
                mark_open=Decimal('60000'), mark_high=Decimal('60001'), mark_low=Decimal('59999'),
                mark_close=Decimal('60000'), index_close=Decimal('60000')),
                next_bar_open=Decimal('60000'))
        return venue
    config = DonchianOfflineReplayConfig(
        repo_root=Path.cwd(), state_dir=path, run_id='same-bar-protection-ledger',
        decision_time_utc=opening, data_version='explicit-same-bar-test-only',
        venue_factory=factory,
        decision_time_provider=lambda event, ordinal, phase: event+timedelta(seconds=1, milliseconds=ordinal),
    )
    runner = DonchianOfflineReplay(config)
    try:
        opened = runner.run_frame(build_trend_frame('long', end=opening))
        assert opened['fill_count'] == 1
        assert runner.venue.state['algos'][0]['economicTimePolicy'] == 'attached_parent_open_fill_before_bar_path_v1'
        terminal = opening + timedelta(hours=1)
        runner.venue.now = terminal + timedelta(seconds=1)
        runner.venue.advance(completed_bar=HistoricalBar(
            event_time_utc=opening, available_time_utc=terminal,
            open=Decimal('60000'), high=Decimal('60060'), low=Decimal('58900'), close=Decimal('59000'),
            mark_open=Decimal('60000'), mark_high=Decimal('60060'), mark_low=Decimal('58900'),
            mark_close=Decimal('59000'), index_close=Decimal('59000')),
            next_bar_open=None,
            funding_events=(HistoricalFundingEvent(terminal, terminal, Decimal('.0001'), Decimal('59000'),
                                                   'same-bar-funding-08', 'reported_mark_price'),))
        receipt = runner.reconcile_terminal_observation(completed_bar=terminal, observation_time=runner.venue.now)
        assert receipt['ledger_event_hash']
        assert receipt['position_contracts'] == '0'
        assert len(runner.venue.state['fills']) == 2
        assert runner.venue.state['fills'][1]['protectionEconomicEffectivePhase'] == 'after_parent_open_fill'
        assert runner.venue.state['fills'][1]['effectiveTimePolicy'] == 'intrabar_time_unknown'
        assert runner.venue.state['bills'][0]['balChg'] == '0'
        assert runner.reconcile_terminal_observation(completed_bar=terminal, observation_time=runner.venue.now) == receipt
    finally:
        runner.close()
    recovered = DonchianOfflineReplay(replace(config, decision_time_utc=terminal))
    try:
        recovered.venue.now = terminal + timedelta(seconds=1)
        assert recovered.reconcile_terminal_observation(completed_bar=terminal, observation_time=recovered.venue.now) == receipt
        assert len(recovered.venue.state['fills']) == 2
    finally:
        recovered.close()


@pytest.mark.parametrize('order_type,size,accepted', [('fok', '.01', True), ('ioc', '.01', True), ('fok', '2', False), ('market', '.01', False)])
def test_history_receives_current_oms_order_types_with_explicit_depth(tmp_path, order_type, size, accepted):
    now = datetime(2026, 7, 23, 8, tzinfo=timezone.utc)
    venue = HistoricalOfflineVenue(tmp_path/'venue.json', now=now)
    venue.state['quote'] = {'bid': '59997', 'ask': '60003', 'open': '60000'}
    response = venue.submit_order({'clOrdId': 'type-test', 'instId': 'BTC-USDT-SWAP', 'side': 'buy',
        'posSide': 'long', 'ordType': order_type, 'px': '60010', 'sz': size})
    assert response.action_ok is accepted
    assert len(venue.state['fills']) == int(accepted)

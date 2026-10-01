# US Equity Manual Vendor Drop Field Dictionary

| table | filename | field | type | required | validation | description |
| --- | --- | --- | --- | --- | --- | --- |
| `universe_membership_events` | `universe_membership_events.csv` | `security_id` | `stable_id` | `yes` | Stable issuer/security identifier and must resolve in symbol_mapping. | Stable security identifier used across all equity lineage files. |
| `universe_membership_events` | `universe_membership_events.csv` | `ticker` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Displayed ticker at the row's effective time, not a backfilled current ticker. |
| `universe_membership_events` | `universe_membership_events.csv` | `universe_name` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Name of the PIT universe, such as SP500, ETF_POOL, or US_CORE. |
| `universe_membership_events` | `universe_membership_events.csv` | `event_type` | `enum` | `yes` | One of: add, delist, exchange_change, list, remove, symbol_change | Provider event classification for membership or corporate action lineage. |
| `universe_membership_events` | `universe_membership_events.csv` | `effective_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Date on which the event becomes effective for PIT research. |
| `universe_membership_events` | `universe_membership_events.csv` | `end_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Optional end date for a membership or mapping interval. |
| `universe_membership_events` | `universe_membership_events.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |
| `delisted_symbols` | `delisted_symbols.csv` | `security_id` | `stable_id` | `yes` | Stable issuer/security identifier and must resolve in symbol_mapping. | Stable security identifier used across all equity lineage files. |
| `delisted_symbols` | `delisted_symbols.csv` | `ticker` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Displayed ticker at the row's effective time, not a backfilled current ticker. |
| `delisted_symbols` | `delisted_symbols.csv` | `delisting_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Date when the security leaves trading/listing coverage. |
| `delisted_symbols` | `delisted_symbols.csv` | `delisting_reason` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Provider reason for delisting, merger, liquidation, acquisition, or other removal. |
| `delisted_symbols` | `delisted_symbols.csv` | `last_trade_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Last known trading date before delisting or removal. |
| `delisted_symbols` | `delisted_symbols.csv` | `delisting_return` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Return impact associated with delisting if supplied by the provider. |
| `delisted_symbols` | `delisted_symbols.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |
| `corporate_actions` | `corporate_actions.csv` | `security_id` | `stable_id` | `yes` | Stable issuer/security identifier and must resolve in symbol_mapping. | Stable security identifier used across all equity lineage files. |
| `corporate_actions` | `corporate_actions.csv` | `ticker` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Displayed ticker at the row's effective time, not a backfilled current ticker. |
| `corporate_actions` | `corporate_actions.csv` | `event_type` | `enum` | `yes` | One of: delisting, dividend, merger, other, spin_off, split, symbol_change | Provider event classification for membership or corporate action lineage. |
| `corporate_actions` | `corporate_actions.csv` | `ex_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Corporate action ex-date. |
| `corporate_actions` | `corporate_actions.csv` | `effective_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Date on which the event becomes effective for PIT research. |
| `corporate_actions` | `corporate_actions.csv` | `ratio` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Split or event ratio when applicable. |
| `corporate_actions` | `corporate_actions.csv` | `cash_amount` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Cash dividend or cash component when applicable. |
| `corporate_actions` | `corporate_actions.csv` | `old_symbol` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Previous ticker or symbol in a symbol-change event. |
| `corporate_actions` | `corporate_actions.csv` | `new_symbol` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | New ticker or symbol in a symbol-change event. |
| `corporate_actions` | `corporate_actions.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |
| `symbol_mapping` | `symbol_mapping.csv` | `security_id` | `stable_id` | `yes` | Stable issuer/security identifier and must resolve in symbol_mapping. | Stable security identifier used across all equity lineage files. |
| `symbol_mapping` | `symbol_mapping.csv` | `ticker` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Displayed ticker at the row's effective time, not a backfilled current ticker. |
| `symbol_mapping` | `symbol_mapping.csv` | `start_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Start of symbol or identifier mapping interval. |
| `symbol_mapping` | `symbol_mapping.csv` | `end_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Optional end date for a membership or mapping interval. |
| `symbol_mapping` | `symbol_mapping.csv` | `figi` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | FIGI identifier when available. |
| `symbol_mapping` | `symbol_mapping.csv` | `cik` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | SEC CIK when available. |
| `symbol_mapping` | `symbol_mapping.csv` | `cusip` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | CUSIP when license permits storage. |
| `symbol_mapping` | `symbol_mapping.csv` | `permno` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | CRSP PERMNO when available and licensed. |
| `symbol_mapping` | `symbol_mapping.csv` | `exchange` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Exchange or venue identifier at the mapping interval. |
| `symbol_mapping` | `symbol_mapping.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |
| `adjustment_replay` | `adjustment_replay.csv` | `security_id` | `stable_id` | `yes` | Stable issuer/security identifier and must resolve in symbol_mapping. | Stable security identifier used across all equity lineage files. |
| `adjustment_replay` | `adjustment_replay.csv` | `ticker` | `string` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Displayed ticker at the row's effective time, not a backfilled current ticker. |
| `adjustment_replay` | `adjustment_replay.csv` | `date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Market date for adjustment replay row. |
| `adjustment_replay` | `adjustment_replay.csv` | `raw_close` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Unadjusted close used as replay input. |
| `adjustment_replay` | `adjustment_replay.csv` | `adjusted_close` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Provider adjusted close used as target value. |
| `adjustment_replay` | `adjustment_replay.csv` | `split_factor` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Split adjustment factor. |
| `adjustment_replay` | `adjustment_replay.csv` | `dividend_adjustment` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Dividend adjustment component. |
| `adjustment_replay` | `adjustment_replay.csv` | `total_adjustment_factor` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Total raw-to-adjusted factor. |
| `adjustment_replay` | `adjustment_replay.csv` | `replay_adjusted_close` | `decimal` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Adjusted close recomputed by the system or provider replay. |
| `adjustment_replay` | `adjustment_replay.csv` | `replay_error` | `decimal` | `yes` | Absolute value must be within adjustment replay tolerance. | Difference between adjusted_close and replay_adjusted_close. |
| `adjustment_replay` | `adjustment_replay.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `series_id` | `stable_id` | `yes` | Non-empty unless explicitly inapplicable; keep provider source semantics. | Macro series identifier. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `observation_period_start` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Macro observation period start date. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `observation_period_end` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Macro observation period end date. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `release_date` | `date:YYYY-MM-DD` | `yes` | ISO date; no future-as-of leakage. | Official macro release date. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `available_time_utc` | `datetime:UTC-Z` | `yes` | UTC timestamp ending with Z; must be the earliest usable release time. | Earliest UTC timestamp when the macro observation is usable by a strategy. |
| `macro_release_calendar` | `macro_release_calendar.csv` | `source_record_id` | `stable_id` | `yes` | Globally unique across all six CSV files. | Unique provider/source row identifier for audit and duplicate detection. |

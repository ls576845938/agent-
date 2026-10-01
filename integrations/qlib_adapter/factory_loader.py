"""Typed generated-feature loader for Qlib; preserves numeric-looking symbols."""
from pathlib import Path

import pandas as pd
from qlib.data.dataset.loader import DataLoader


class FactoryParquetLoader(DataLoader):
    def __init__(self, *, features: str, labels: str):
        self.features, self.labels = Path(features), Path(labels)
        if self.features.parent.resolve() != self.labels.parent.resolve():
            raise ValueError("factory_feature_label_root_mismatch")

    def load(self, instruments=None, start_time=None, end_time=None):
        features, labels = pd.read_parquet(self.features), pd.read_parquet(self.labels)
        for frame in (features, labels):
            if frame.index.names != ["datetime", "instrument"] or frame.index.duplicated().any():
                raise ValueError("factory_feature_index_invalid")
            if not all(isinstance(value, str) for value in frame.index.get_level_values("instrument")):
                raise ValueError("factory_instrument_type_invalid")
        if not features.index.equals(labels.index): raise ValueError("factory_feature_label_alignment_invalid")
        result = pd.concat({"feature":features,"label":labels},axis=1).sort_index()
        dates = result.index.get_level_values("datetime")
        if start_time is not None: result = result.loc[dates >= pd.Timestamp(start_time)]
        if end_time is not None: result = result.loc[result.index.get_level_values("datetime") <= pd.Timestamp(end_time)]
        if instruments is not None:
            if isinstance(instruments,str): raise ValueError("factory_loader_requires_explicit_instrument_list")
            result = result.loc[result.index.get_level_values("instrument").isin(instruments)]
        return result

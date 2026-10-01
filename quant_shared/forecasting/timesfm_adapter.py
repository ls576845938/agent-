from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from quant_shared.forecasting.contracts import (
    ForecastQuantile,
    ModelUnavailableError,
    TimeSeriesForecastRequest,
    TimeSeriesForecastResult,
)


TIMESFM_DEFAULT_CHECKPOINT = "google/timesfm-2.5-200m-pytorch"
TIMESFM_MODEL_ID = "timesfm"
TIMESFM_MODEL_VERSION = "2.5"


def is_timesfm_available() -> bool:
    return importlib.util.find_spec("timesfm") is not None


def inspect_timesfm_environment() -> dict[str, Any]:
    return {
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "python_supported": sys.version_info >= (3, 10),
        "timesfm_python_package_present": is_timesfm_available(),
        "torch_python_package_present": importlib.util.find_spec("torch") is not None,
        "numpy_python_package_present": importlib.util.find_spec("numpy") is not None,
        "default_checkpoint": TIMESFM_DEFAULT_CHECKPOINT,
    }


@dataclass
class TimesFMForecastAdapter:
    checkpoint_repo_id: str = TIMESFM_DEFAULT_CHECKPOINT
    max_context: int = 1024
    max_horizon: int = 256
    normalize_inputs: bool = True
    use_continuous_quantile_head: bool = True
    force_flip_invariance: bool = True
    infer_is_positive: bool = True
    fix_quantile_crossing: bool = True
    torch_compile: bool = False
    model_id: str = TIMESFM_MODEL_ID
    model_version: str = TIMESFM_MODEL_VERSION

    def __post_init__(self) -> None:
        if int(self.max_context) <= 0:
            raise ValueError("TimesFM max_context must be positive.")
        if int(self.max_context) % 32 != 0:
            raise ValueError("TimesFM 2.5 max_context must be a multiple of 32.")
        if int(self.max_horizon) <= 0:
            raise ValueError("TimesFM max_horizon must be positive.")
        if sys.version_info < (3, 10):
            raise ModelUnavailableError("TimesFM requires Python >=3.10.")
        if not is_timesfm_available():
            raise ModelUnavailableError(
                "TimesFM is not installed. Install the optional timesfm extra in an isolated research environment."
            )
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        import timesfm  # type: ignore[import-not-found]

        if not hasattr(timesfm, "TimesFM_2p5_200M_torch"):
            raise ModelUnavailableError("Installed timesfm package does not expose the TimesFM 2.5 torch API.")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            self.checkpoint_repo_id,
            torch_compile=bool(self.torch_compile),
        )
        model.compile(
            timesfm.ForecastConfig(
                max_context=int(self.max_context),
                max_horizon=int(self.max_horizon),
                normalize_inputs=bool(self.normalize_inputs),
                use_continuous_quantile_head=bool(self.use_continuous_quantile_head),
                force_flip_invariance=bool(self.force_flip_invariance),
                infer_is_positive=bool(self.infer_is_positive),
                fix_quantile_crossing=bool(self.fix_quantile_crossing),
            )
        )
        self._model = model
        return model

    def forecast(self, request: TimeSeriesForecastRequest) -> TimeSeriesForecastResult:
        if request.horizon_steps > self.max_horizon:
            raise ValueError("request horizon exceeds TimesFM adapter max_horizon.")
        if len(request.history_values) > self.max_context:
            values = request.history_values[-self.max_context :]
        else:
            values = request.history_values

        model = self._load_model()
        point_forecast, quantile_forecast = model.forecast(
            horizon=request.horizon_steps,
            inputs=[np.asarray(values, dtype=np.float32)],
        )
        point_values = tuple(float(item) for item in np.asarray(point_forecast)[0, : request.horizon_steps])
        quantiles = _extract_quantiles(quantile_forecast, request.horizon_steps)
        return TimeSeriesForecastResult(
            request=request,
            model_id=self.model_id,
            model_version=self.model_version,
            generated_at_utc=datetime.now(timezone.utc),
            point_forecast=point_values,
            quantiles=quantiles,
            confidence=None,
            metadata={
                "checkpoint_repo_id": self.checkpoint_repo_id,
                "max_context": self.max_context,
                "max_horizon": self.max_horizon,
                "normalize_inputs": self.normalize_inputs,
                "use_continuous_quantile_head": self.use_continuous_quantile_head,
                "torch_compile": self.torch_compile,
                "adapter_boundary": "research_or_risk_auxiliary_only",
            },
        )


def _extract_quantiles(quantile_forecast: Any, horizon_steps: int) -> tuple[ForecastQuantile, ...]:
    if quantile_forecast is None:
        return ()
    array = np.asarray(quantile_forecast)
    if array.ndim != 3 or array.shape[0] < 1:
        return ()
    rows = array[0, :horizon_steps, :]
    if rows.shape[-1] <= 1:
        return ()
    probabilities = [round(0.1 * item, 1) for item in range(1, min(10, rows.shape[-1]))]
    quantiles: list[ForecastQuantile] = []
    for step_index, row in enumerate(rows, start=1):
        for offset, probability in enumerate(probabilities, start=1):
            quantiles.append(
                ForecastQuantile(
                    step=step_index,
                    quantile=probability,
                    value=float(row[offset]),
                )
            )
    return tuple(quantiles)

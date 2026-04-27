from __future__ import annotations


class QuantStationError(Exception):
    """Base application error."""


class ConfigurationError(QuantStationError):
    """Raised when runtime configuration is invalid."""


class DataNotAvailableError(QuantStationError):
    """Raised when market data cannot be loaded from the requested source."""


class DataSyncError(QuantStationError):
    """Raised when external market data cannot be synchronized."""


class StrategyNotFoundError(QuantStationError):
    """Raised when a strategy id does not exist in the registry."""


class DependencyUnavailableError(QuantStationError):
    """Raised when an optional runtime dependency is missing."""


class RunNotFoundError(QuantStationError):
    """Raised when a run id cannot be found in the registry."""

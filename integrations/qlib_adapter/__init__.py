"""Qlib daily-only adapter for research workflows.

This package is import-safe when optional Qlib dependencies are absent.
"""

from .schemas import MissingDependencyError, QlibAdapterError

__all__ = ["MissingDependencyError", "QlibAdapterError"]

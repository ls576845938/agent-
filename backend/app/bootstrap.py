from __future__ import annotations

from backend.app.api.app_factory import create_app
from backend.app.core.config import settings
from backend.app.core.exceptions import DependencyUnavailableError


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise DependencyUnavailableError(
            "uvicorn is not installed. Install project dependencies from pyproject.toml before starting the API server."
        ) from exc

    uvicorn.run(
        "backend.app.api.app_factory:create_app",
        host=settings.api_host,
        port=settings.api_port,
        factory=True,
        reload=False,
    )

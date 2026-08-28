"""FastAPI application factory.

Thin by design (ARCHITECTURE §5: "``apps/`` and ``workers/`` are thin entry
points"). This module wires: settings, the engine, the RFC 9457 exception
handlers, and the routers. It contains no business logic.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from neptiq_api.routers import health
from neptiq_core.errors import NeptiqError, ValidationError
from neptiq_core.logging import configure_logging, get_logger
from neptiq_core.settings import get_settings
from neptiq_db.session import create_engine, create_session_factory, install_rls_guard

logger = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

# Below this we do not log a traceback: 4xx are client faults and would
# otherwise drown the error budget in noise.
_SERVER_ERROR_FLOOR = 500


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    The evidence-domain assertion runs here, at startup, rather than being
    checked at the point of serving raw bodies. A misconfiguration that puts
    hostile content inside the app's cookie scope must stop the process, not
    produce one failed request — by the time a raw body is being served it is
    too late to discover the domains share a cookie jar (ARCHITECTURE §14).
    """
    settings = get_settings()
    configure_logging("INFO" if settings.NEPTIQ_ENV != "dev" else "DEBUG")
    settings.assert_evidence_domain_separate()

    engine = create_engine(settings.DATABASE_URL, echo=settings.NEPTIQ_ENV == "dev")
    if settings.NEPTIQ_ENV in ("dev", "test", "staging"):
        install_rls_guard(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    logger.info(
        "api starting",
        extra={
            "env": settings.NEPTIQ_ENV,
            "region": settings.NEPTIQ_REGION,
            # P10 / invariant 9: log whether we are running with external LLM
            # providers at all, so a degraded-mode run is identifiable in logs.
            "external_llm_available": settings.external_llm_available,
        },
    )
    try:
        yield
    finally:
        # Workers "drain leases before shutdown" (§15); the API's equivalent is
        # closing the pool so in-flight transactions finish or roll back
        # cleanly rather than being severed mid-statement.
        await engine.dispose()
        logger.info("api stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="NEPTIQ API",
        version="0.1.0",
        # OpenAPI 3.1 so that Pydantic v2 JSON Schema maps cleanly and the
        # generated frontend client in apps/web/lib/api is faithful (§4).
        openapi_version="3.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    @app.exception_handler(NeptiqError)
    async def _neptiq_error_handler(request: Request, exc: NeptiqError) -> JSONResponse:
        # Server-side faults are logged with the traceback; client faults are
        # not, to keep 4xx noise out of the error budget.
        if exc.status >= _SERVER_ERROR_FLOOR:
            logger.exception("request failed", extra={"code": exc.code, "path": request.url.path})
        return JSONResponse(
            status_code=exc.status,
            content=exc.as_problem(instance=str(request.url.path)),
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's error list is echoed, but through ``errors`` as structured
        # data — never interpolated into ``detail``, because the offending input
        # is attacker-controlled and ``detail`` is rendered as text in clients.
        problem = ValidationError("one or more fields failed validation").as_problem(
            instance=str(request.url.path)
        )
        problem["errors"] = _safe_validation_errors(exc.errors())
        return JSONResponse(status_code=422, content=problem, media_type=PROBLEM_JSON)

    app.include_router(health.router)
    return app


def _safe_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Reduce Pydantic errors to location + type, dropping echoed input.

    ``ctx`` and ``input`` can contain the raw submitted value. Echoing it back
    is a reflected-content path, and for a large body it is also a denial of
    service against our own logs.
    """
    out: list[dict[str, Any]] = []
    for err in errors[:50]:
        if not isinstance(err, dict):
            continue
        out.append(
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "type": str(err.get("type", "unknown")),
                "msg": str(err.get("msg", ""))[:200],
            }
        )
    return out


app = create_app()

__all__ = ["app", "create_app", "lifespan"]

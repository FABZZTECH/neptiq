"""Health and readiness.

Two endpoints, because they answer different questions and conflating them
breaks rolling deploys:

  * ``/healthz``  — is the process alive? No dependency checks. Kamal uses this
    to decide whether to kill the container. If it checked Postgres, a brief
    database blip would make Kamal destroy every healthy app container.
  * ``/readyz``   — can this instance serve traffic? Checks the database. Used
    by the proxy to decide whether to route requests here.

Neither endpoint is tenant-scoped, so neither uses the RLS session dependency.
``/readyz`` deliberately uses a trivial ``SELECT 1`` rather than reading a
tenant table, because reading a tenant table without an org binding correctly
returns zero rows and would make a healthy database look broken.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neptiq_api.deps.tenancy import get_session_factory
from neptiq_api.schemas.base import ApiModel
from neptiq_core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(ApiModel):
    status: Literal["ok"]


class ReadyResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]
    # Surfaced so an operator can see at a glance whether this instance is
    # running without external LLM providers — invariant 9's degraded mode is
    # a supported state, not an outage, and must be visible as such.
    external_llm_available: bool


@router.get("/healthz", response_model=HealthResponse, summary="Liveness — no dependency checks")
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadyResponse, summary="Readiness — checks the database")
async def readyz(
    response: Response,
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> ReadyResponse:
    database: Literal["ok", "unavailable"] = "ok"
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness probe: database unavailable")
        database = "unavailable"
        response.status_code = 503

    from neptiq_core.settings import get_settings

    settings = get_settings()
    return ReadyResponse(
        status="ready" if database == "ok" else "not_ready",
        database=database,
        external_llm_available=settings.external_llm_available,
    )


__all__ = ["HealthResponse", "ReadyResponse", "router"]

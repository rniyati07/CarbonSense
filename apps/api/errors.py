"""ENG-5b — maps known service-layer domain exceptions to HTTP responses.

Only exceptions that already exist as named, expected outcomes in the
services this API wraps are registered here (404 for "not found," 400 for
"invalid input"). Anything else propagates to FastAPI's default 500 --
deliberately not caught by a blanket handler, so a real bug surfaces as a
loud 500 during development/CI rather than a silently-swallowed 400.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from services.feedback.service import (
    FindingNotFoundError as FeedbackFindingNotFoundError,
)
from services.feedback.service import (
    InvalidFeedbackActionError,
    MissingExplainabilityBundleError,
)
from services.optimization.service import BuildingNotFoundError as OptimizationBuildingNotFoundError
from services.tenant_admin.service import BuildingNotFoundError as AdminBuildingNotFoundError
from services.tenant_admin.service import TenantNotFoundError


def _not_found(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


def _bad_request(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(FeedbackFindingNotFoundError, _not_found)
    app.add_exception_handler(OptimizationBuildingNotFoundError, _not_found)
    app.add_exception_handler(AdminBuildingNotFoundError, _not_found)
    app.add_exception_handler(TenantNotFoundError, _not_found)
    app.add_exception_handler(InvalidFeedbackActionError, _bad_request)
    app.add_exception_handler(MissingExplainabilityBundleError, _bad_request)

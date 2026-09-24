"""
Project Assessment Instruments Endpoints.

Manages assessment instruments per project.
Allows cloning global instruments (PROBAST, ROBIS) or creating custom ones.
"""

import time
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    CurrentUser,
    DbSession,
    ensure_project_member,
    require_project_member,
)
from app.core.logging import get_logger
from app.repositories.assessment_repository import (
    ProjectAssessmentInstrumentRepository,
    ProjectAssessmentItemRepository,
)
from app.schemas.assessment import (
    CloneInstrumentRequest,
    CloneInstrumentResponse,
    ProjectAssessmentInstrumentCreate,
    ProjectAssessmentInstrumentSchema,
    ProjectAssessmentInstrumentUpdate,
    ProjectAssessmentItemCreate,
    ProjectAssessmentItemSchema,
    ProjectAssessmentItemUpdate,
)
from app.schemas.common import ApiResponse
from app.services.project_assessment_instrument_service import (
    ProjectAssessmentInstrumentService,
)
from app.utils.rate_limiter import limiter

router = APIRouter()
logger = get_logger(__name__)


async def _ensure_instrument_access(
    db: AsyncSession,
    instrument_id: UUID,
    user_id: str,
) -> None:
    """404 if the project instrument does not exist, 403 if the user is not a project member."""
    instrument = await ProjectAssessmentInstrumentRepository(db).get_by_id(instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument not found: {instrument_id}",
        )
    await ensure_project_member(db, instrument.project_id, user_id)


async def _ensure_item_access(
    db: AsyncSession,
    item_id: UUID,
    user_id: str,
) -> None:
    """404 if the project item does not exist, 403 if the user is not a project member."""
    item = await ProjectAssessmentItemRepository(db).get_by_id(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item not found: {item_id}",
        )
    await _ensure_instrument_access(db, item.project_instrument_id, user_id)


@router.get(
    "/global",
    response_model=ApiResponse,
    summary="List global instruments",
    description="Lists all global instruments available for cloning.",
)
@limiter.limit("30/minute")
async def list_global_instruments(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    List available global instruments (PROBAST, ROBIS, etc.).

    Returns summary info for each instrument for selection.
    """
    trace_id = str(uuid.uuid4())

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    instruments = await service.list_global_instruments()

    return ApiResponse(
        ok=True,
        data={"instruments": instruments},
        trace_id=trace_id,
    )


@router.get(
    "/project/{project_id}",
    response_model=ApiResponse,
    summary="List project instruments",
    description="Lists all instruments configured for a project.",
    dependencies=[Depends(require_project_member)],
)
@limiter.limit("30/minute")
async def list_project_instruments(
    request: Request,
    project_id: UUID,
    db: DbSession,
    user: CurrentUser,
    active_only: bool = True,
) -> ApiResponse:
    """
    List instruments for a project.

    Args:
        project_id: Project ID.
        active_only: If True, return only active instruments.
    """
    trace_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    instruments = await service.list_project_instruments(
        project_id=project_id,
        active_only=active_only,
    )

    duration_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "list_project_instruments_done",
        trace_id=trace_id,
        project_id=str(project_id),
        count=len(instruments),
        duration_ms=round(duration_ms, 2),
    )

    return ApiResponse(
        ok=True,
        data={"instruments": [i.model_dump(by_alias=True) for i in instruments]},
        trace_id=trace_id,
    )


@router.get(
    "/{instrument_id}",
    response_model=ApiResponse,
    summary="Get instrument",
    description="Fetches an instrument by ID with all its items.",
)
@limiter.limit("30/minute")
async def get_instrument(
    request: Request,
    instrument_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Fetch instrument by ID with items.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_instrument_access(db, instrument_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    instrument = await service.get_project_instrument(instrument_id)

    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument not found: {instrument_id}",
        )

    return ApiResponse(
        ok=True,
        data=instrument.model_dump(by_alias=True),
        trace_id=trace_id,
    )


@router.post(
    "/clone",
    response_model=ApiResponse,
    summary="Clone global instrument",
    description="Clones a global instrument to a specific project.",
)
@limiter.limit("10/minute")
async def clone_global_instrument(
    request: Request,
    payload: CloneInstrumentRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Clone a global instrument (PROBAST, ROBIS) to a project.

    Creates a full copy with all items, allowing later
    customization without affecting the original instrument.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "clone_instrument_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(payload.project_id),
        global_instrument_id=str(payload.global_instrument_id),
    )

    await ensure_project_member(db, payload.project_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    try:
        instrument = await service.clone_global_instrument(
            project_id=payload.project_id,
            global_instrument_id=payload.global_instrument_id,
            custom_name=payload.custom_name,
        )

        return ApiResponse(
            ok=True,
            data=CloneInstrumentResponse(
                project_instrument_id=instrument.id,
                message="Instrument cloned successfully",
            ).model_dump(by_alias=True),
            trace_id=trace_id,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(
            "clone_instrument_error",
            trace_id=trace_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clone instrument: {e}",
        )


@router.post(
    "",
    response_model=ApiResponse,
    summary="Create custom instrument",
    description="Creates a new custom instrument for a project.",
)
@limiter.limit("10/minute")
async def create_instrument(
    request: Request,
    payload: ProjectAssessmentInstrumentCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Create a custom instrument.

    Allows creating custom instruments with user-defined items,
    without cloning a global instrument.
    """
    trace_id = str(uuid.uuid4())

    logger.info(
        "create_instrument_request",
        trace_id=trace_id,
        user_id=user.sub,
        project_id=str(payload.project_id),
        tool_type=payload.tool_type,
    )

    await ensure_project_member(db, payload.project_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    instrument = await service.create_custom_instrument(payload)

    return ApiResponse(
        ok=True,
        data=instrument.model_dump(by_alias=True),
        trace_id=trace_id,
    )


@router.patch(
    "/{instrument_id}",
    response_model=ApiResponse,
    summary="Update instrument",
    description="Updates a project instrument.",
)
@limiter.limit("20/minute")
async def update_instrument(
    request: Request,
    instrument_id: UUID,
    payload: ProjectAssessmentInstrumentUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Atualiza um instrumento de projeto.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_instrument_access(db, instrument_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    instrument = await service.update_instrument(instrument_id, payload)

    if not instrument:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument not found: {instrument_id}",
        )

    return ApiResponse(
        ok=True,
        data=instrument.model_dump(by_alias=True),
        trace_id=trace_id,
    )


@router.delete(
    "/{instrument_id}",
    response_model=ApiResponse,
    summary="Delete instrument",
    description="Deletes a project instrument.",
)
@limiter.limit("10/minute")
async def delete_instrument(
    request: Request,
    instrument_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Deleta um instrumento de projeto.

    Remove o instrumento e todos os seus items.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_instrument_access(db, instrument_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    deleted = await service.delete_instrument(instrument_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument not found: {instrument_id}",
        )

    return ApiResponse(
        ok=True,
        data={"message": "Instrument deleted successfully"},
        trace_id=trace_id,
    )


# =================== ITEM ENDPOINTS ===================


@router.post(
    "/{instrument_id}/items",
    response_model=ApiResponse,
    summary="Add item",
    description="Adds an item to an instrument.",
)
@limiter.limit("20/minute")
async def add_item(
    request: Request,
    instrument_id: UUID,
    payload: ProjectAssessmentItemCreate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Adiciona um novo item a um instrumento.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_instrument_access(db, instrument_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    item = await service.add_item(instrument_id, payload)

    return ApiResponse(
        ok=True,
        data=item.model_dump(by_alias=True),
        trace_id=trace_id,
    )


@router.patch(
    "/items/{item_id}",
    response_model=ApiResponse,
    summary="Update item",
    description="Updates an instrument item.",
)
@limiter.limit("20/minute")
async def update_item(
    request: Request,
    item_id: UUID,
    payload: ProjectAssessmentItemUpdate,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Atualiza um item de instrumento.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_item_access(db, item_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    item = await service.update_item(item_id, payload)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item not found: {item_id}",
        )

    return ApiResponse(
        ok=True,
        data=item.model_dump(by_alias=True),
        trace_id=trace_id,
    )


@router.delete(
    "/items/{item_id}",
    response_model=ApiResponse,
    summary="Delete item",
    description="Deletes an instrument item.",
)
@limiter.limit("20/minute")
async def delete_item(
    request: Request,
    item_id: UUID,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    """
    Deleta um item de instrumento.
    """
    trace_id = str(uuid.uuid4())
    await _ensure_item_access(db, item_id, user.sub)

    service = ProjectAssessmentInstrumentService(
        db=db,
        user_id=user.sub,
        trace_id=trace_id,
    )

    deleted = await service.delete_item(item_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item not found: {item_id}",
        )

    return ApiResponse(
        ok=True,
        data={"message": "Item deleted successfully"},
        trace_id=trace_id,
    )

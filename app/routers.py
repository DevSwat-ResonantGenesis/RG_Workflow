from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import WorkflowDefinition, WorkflowRun, WorkflowStepResult, WorkflowEvent
from .executor import workflow_executor


router = APIRouter(prefix="/workflow", tags=["workflow"])


# Request/Response Models
class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: Optional[str] = "manual"
    trigger_config: Optional[Dict[str, Any]] = None
    steps: List[Dict[str, Any]]
    graph_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    graph_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger_type: Optional[str]
    trigger_config: Optional[Dict[str, Any]] = None
    steps: List[Dict[str, Any]]
    graph_data: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    enabled: bool
    version: int
    is_template: bool = False
    template_category: Optional[str] = None

    class Config:
        from_attributes = True


class WorkflowRunCreate(BaseModel):
    input_data: Optional[Dict[str, Any]] = None


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    status: str
    current_step: int
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class StepResultResponse(BaseModel):
    id: str
    step_index: int
    step_name: Optional[str]
    status: str
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None

    class Config:
        from_attributes = True


class EventCreate(BaseModel):
    event_type: str
    source: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    workflow_id: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    event_type: str
    source: Optional[str]
    processed: bool

    class Config:
        from_attributes = True


def _serialize_workflow(w) -> WorkflowResponse:
    return WorkflowResponse(
        id=str(w.id),
        name=w.name,
        description=w.description,
        trigger_type=w.trigger_type,
        trigger_config=w.trigger_config,
        steps=w.steps or [],
        graph_data=w.graph_data,
        tags=w.tags,
        enabled=w.enabled,
        version=w.version,
        is_template=getattr(w, 'is_template', False) or False,
        template_category=getattr(w, 'template_category', None),
    )


# Workflow Definition Endpoints
@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a new workflow definition."""
    user_id = request.headers.get("x-user-id")

    if not user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    workflow = WorkflowDefinition(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        trigger_type=payload.trigger_type,
        trigger_config=payload.trigger_config,
        steps=payload.steps,
        graph_data=payload.graph_data,
        tags=payload.tags,
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)

    return _serialize_workflow(workflow)


@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Update a workflow definition."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    result = await session.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.id == workflow_id)
        .where(WorkflowDefinition.user_id == header_user_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None:
        workflow.description = payload.description
    if payload.trigger_type is not None:
        workflow.trigger_type = payload.trigger_type
    if payload.trigger_config is not None:
        workflow.trigger_config = payload.trigger_config
    if payload.steps is not None:
        workflow.steps = payload.steps
    if payload.graph_data is not None:
        workflow.graph_data = payload.graph_data
    if payload.tags is not None:
        workflow.tags = payload.tags

    workflow.version = (workflow.version or 0) + 1
    await session.commit()
    await session.refresh(workflow)

    return _serialize_workflow(workflow)


@router.get("/workflows", response_model=List[WorkflowResponse])
async def list_workflows(
    request: Request,
    user_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """List all workflow definitions."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")
    if user_id and user_id != header_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    stmt = select(WorkflowDefinition)
    stmt = stmt.where(WorkflowDefinition.user_id == header_user_id)

    result = await session.execute(stmt)
    workflows = result.scalars().all()

    return [_serialize_workflow(w) for w in workflows]


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get a workflow definition by ID."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    result = await session.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.id == workflow_id)
        .where(WorkflowDefinition.user_id == header_user_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return _serialize_workflow(workflow)


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Delete a workflow definition."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    result = await session.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.id == workflow_id)
        .where(WorkflowDefinition.user_id == header_user_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await session.delete(workflow)
    await session.commit()
    return {"status": "deleted", "id": workflow_id}


# Workflow Execution Endpoints
@router.post("/workflows/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: str,
    payload: WorkflowRunCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Execute a workflow."""
    user_id = request.headers.get("x-user-id")

    if not user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    # Get workflow definition
    result = await session.execute(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.id == workflow_id)
        .where(WorkflowDefinition.user_id == user_id)
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.enabled:
        raise HTTPException(status_code=400, detail="Workflow is disabled")

    # Create run record
    run = WorkflowRun(
        workflow_id=workflow_id,
        user_id=user_id,
        status="pending",
        input_data=payload.input_data,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # Execute workflow (in background for long-running workflows)
    # For now, execute synchronously
    result = await workflow_executor.execute_workflow(workflow, run, session)

    return WorkflowRunResponse(
        id=str(run.id),
        workflow_id=str(run.workflow_id),
        status=run.status,
        current_step=run.current_step,
        output_data=run.output_data,
        error_message=run.error_message,
    )


@router.get("/runs", response_model=List[WorkflowRunResponse])
async def list_runs(
    request: Request,
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List workflow runs."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.user_id == header_user_id)
        .order_by(WorkflowRun.created_at.desc())
    )
    if workflow_id:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)

    result = await session.execute(stmt.limit(limit))
    runs = result.scalars().all()

    return [
        WorkflowRunResponse(
            id=str(r.id),
            workflow_id=str(r.workflow_id),
            status=r.status,
            current_step=r.current_step,
            output_data=r.output_data,
            error_message=r.error_message,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get a workflow run by ID."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .where(WorkflowRun.user_id == header_user_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return WorkflowRunResponse(
        id=str(run.id),
        workflow_id=str(run.workflow_id),
        status=run.status,
        current_step=run.current_step,
        output_data=run.output_data,
        error_message=run.error_message,
    )


@router.get("/runs/{run_id}/steps", response_model=List[StepResultResponse])
async def get_run_steps(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get step results for a workflow run."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    run_result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .where(WorkflowRun.user_id == header_user_id)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    result = await session.execute(
        select(WorkflowStepResult)
        .where(WorkflowStepResult.run_id == run_id)
        .order_by(WorkflowStepResult.step_index)
    )
    steps = result.scalars().all()

    return [
        StepResultResponse(
            id=str(s.id),
            step_index=s.step_index,
            step_name=s.step_name,
            status=s.status,
            output_data=s.output_data,
            error_message=s.error_message,
            duration_ms=s.duration_ms,
        )
        for s in steps
    ]


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Cancel a running workflow."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    result = await session.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .where(WorkflowRun.user_id == header_user_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Run cannot be cancelled")

    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    await session.commit()

    return {"status": "cancelled", "id": run_id}


# Event Bus Endpoints
@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def publish_event(
    payload: EventCreate,
    session: AsyncSession = Depends(get_session),
):
    """Publish an event to the event bus."""
    event = WorkflowEvent(
        event_type=payload.event_type,
        source=payload.source,
        payload=payload.payload,
        workflow_id=payload.workflow_id,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    # If event targets a specific workflow, trigger it
    if payload.workflow_id:
        result = await session.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.id == payload.workflow_id,
                WorkflowDefinition.enabled == True,
            )
        )
        workflow = result.scalar_one_or_none()
        if workflow and workflow.trigger_type == "event":
            # Create and execute run
            run = WorkflowRun(
                workflow_id=workflow.id,
                status="pending",
                input_data=payload.payload,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            await workflow_executor.execute_workflow(workflow, run, session)

    event.processed = True
    await session.commit()

    return EventResponse(
        id=str(event.id),
        event_type=event.event_type,
        source=event.source,
        processed=event.processed,
    )


@router.get("/events", response_model=List[EventResponse])
async def list_events(
    event_type: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List recent events."""
    stmt = select(WorkflowEvent).order_by(WorkflowEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(WorkflowEvent.event_type == event_type)

    result = await session.execute(stmt.limit(limit))
    events = result.scalars().all()

    return [
        EventResponse(
            id=str(e.id),
            event_type=e.event_type,
            source=e.source,
            processed=e.processed,
        )
        for e in events
    ]


@router.get("/workflows/stats")
async def workflow_stats(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Get workflow statistics for the current user."""
    header_user_id = request.headers.get("x-user-id")
    if not header_user_id:
        raise HTTPException(status_code=401, detail="User ID required")

    from sqlalchemy import func

    # Total workflows
    total_result = await session.execute(
        select(func.count(WorkflowDefinition.id))
        .where(WorkflowDefinition.user_id == header_user_id)
    )
    total_workflows = total_result.scalar() or 0

    # Enabled workflows
    enabled_result = await session.execute(
        select(func.count(WorkflowDefinition.id))
        .where(WorkflowDefinition.user_id == header_user_id)
        .where(WorkflowDefinition.enabled == True)
    )
    enabled_workflows = enabled_result.scalar() or 0

    # Total runs
    total_runs_result = await session.execute(
        select(func.count(WorkflowRun.id))
        .where(WorkflowRun.user_id == header_user_id)
    )
    total_runs = total_runs_result.scalar() or 0

    # Completed runs
    completed_result = await session.execute(
        select(func.count(WorkflowRun.id))
        .where(WorkflowRun.user_id == header_user_id)
        .where(WorkflowRun.status == "completed")
    )
    completed_runs = completed_result.scalar() or 0

    # Failed runs
    failed_result = await session.execute(
        select(func.count(WorkflowRun.id))
        .where(WorkflowRun.user_id == header_user_id)
        .where(WorkflowRun.status == "failed")
    )
    failed_runs = failed_result.scalar() or 0

    return {
        "total_workflows": total_workflows,
        "enabled_workflows": enabled_workflows,
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "success_rate": round((completed_runs / total_runs * 100), 1) if total_runs > 0 else 0,
    }


@router.get("/health")
async def health():
    return {"service": "workflow", "status": "ok"}

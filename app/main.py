import sys
import logging
import httpx
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .routers import router as workflow_router
from .db import engine, Base
from .models import WorkflowDefinition, WorkflowRun, WorkflowStepResult, WorkflowEvent  # noqa: F401

# Add shared modules to path
SHARED_PATH = Path(__file__).resolve().parents[2] / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Deterministic sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# Credit costs from pricing.yaml
CREDIT_COSTS = {
    "workflow_start": 1000,
    "node": 300,
    "conditional": 200,
    "parallel": 400,
    "step": 20,
    "scheduled_trigger": 10,
    "webhook_trigger": 5,
}

BILLING_SERVICE_URL = "http://billing_service:8000"

# Single service entrypoint
app = FastAPI(
    title="Workflow_Service Service",
    description="Service for Genesis2026",
    version="1.0.0"
)

app.include_router(workflow_router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class WorkflowNode(BaseModel):
    id: str
    type: str  # 'action', 'conditional', 'parallel'
    config: Optional[Dict[str, Any]] = None

class WorkflowRunRequest(BaseModel):
    workflow_id: str
    nodes: List[WorkflowNode]
    trigger_type: Optional[str] = "manual"  # 'manual', 'scheduled', 'webhook'

class WorkflowRunResponse(BaseModel):
    workflow_id: str
    status: str
    credits_deducted: int
    node_count: int

async def deduct_credits(user_id: str, amount: int, description: str) -> dict:
    """Deduct credits from user's balance via billing service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BILLING_SERVICE_URL}/billing/credits/deduct",
                json={
                    "amount": amount,
                    "reference_type": "workflow_run",
                    "description": description,
                },
                headers={"X-User-Id": user_id},
                timeout=5.0,
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.warning(f"Credit deduction failed: {e}")
        return {"error": str(e)}

@app.on_event("startup")
async def startup():
    """Create tables if they don't exist — retry with backoff."""
    import asyncio
    from sqlalchemy import text
    for attempt in range(3):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Phase 2.1: Add new columns for visual workflow builder
                ddls = [
                    "ALTER TABLE workflow_definitions ADD COLUMN IF NOT EXISTS graph_data JSON",
                    "ALTER TABLE workflow_definitions ADD COLUMN IF NOT EXISTS tags JSON",
                    "ALTER TABLE workflow_definitions ADD COLUMN IF NOT EXISTS is_template BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE workflow_definitions ADD COLUMN IF NOT EXISTS template_category VARCHAR(64)",
                ]
                for ddl in ddls:
                    try:
                        await conn.execute(text(ddl))
                    except Exception:
                        pass
            logger.info("Workflow service DB tables ensured")
            return
        except Exception as e:
            logger.warning(f"DB table creation attempt {attempt+1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
    logger.error("Could not create DB tables after 3 attempts — service will start anyway")


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "workflow_service"}

# Root endpoint
@app.get("/")
async def root():
    return {"message": f"Workflow_Service Service is running"}

# Service-specific endpoint
@app.get("/api/v1/status")
async def status():
    return {"service": "workflow_service", "status": "active", "version": "1.0.0"}

@app.post("/api/v1/workflows/run", response_model=WorkflowRunResponse)
async def run_workflow(request: WorkflowRunRequest, req: Request):
    """Execute a workflow and deduct credits based on complexity."""
    user_id = req.headers.get("x-user-id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID required")
    
    # Calculate credits based on workflow complexity
    credits = CREDIT_COSTS["workflow_start"]
    
    # Add trigger cost
    if request.trigger_type == "scheduled":
        credits += CREDIT_COSTS["scheduled_trigger"]
    elif request.trigger_type == "webhook":
        credits += CREDIT_COSTS["webhook_trigger"]
    
    # Add node costs
    for node in request.nodes:
        if node.type == "conditional":
            credits += CREDIT_COSTS["conditional"]
        elif node.type == "parallel":
            credits += CREDIT_COSTS["parallel"]
        else:
            credits += CREDIT_COSTS["node"]
    
    # Deduct credits
    await deduct_credits(
        user_id=user_id,
        amount=credits,
        description=f"Workflow {request.workflow_id} ({len(request.nodes)} nodes)"
    )
    logger.info(f"💳 Deducted {credits} credits for workflow run")
    
    return WorkflowRunResponse(
        workflow_id=request.workflow_id,
        status="completed",
        credits_deducted=credits,
        node_count=len(request.nodes)
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)

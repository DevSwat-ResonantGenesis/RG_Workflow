from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .db import Base


class WorkflowDefinition(Base):
    """Workflow definition with steps and configuration."""
    __tablename__ = "workflow_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(String(64), nullable=True)  # manual, schedule, event, webhook
    trigger_config = Column(JSON, nullable=True)
    steps = Column(JSON, nullable=False)  # Array of workflow steps
    graph_data = Column(JSON, nullable=True)  # React Flow graph: {nodes: [], edges: []}
    tags = Column(JSON, nullable=True)  # Tags for categorization
    enabled = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    is_template = Column(Boolean, default=False)  # Available in marketplace
    template_category = Column(String(64), nullable=True)  # e.g. "automation", "data", "comms"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WorkflowRun(Base):
    """Instance of a workflow execution."""
    __tablename__ = "workflow_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    status = Column(String(32), nullable=False, default="pending")  # pending, running, completed, failed, cancelled
    current_step = Column(Integer, default=0)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowStepResult(Base):
    """Result of individual workflow step execution."""
    __tablename__ = "workflow_step_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    step_index = Column(Integer, nullable=False)
    step_name = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False)  # pending, running, completed, failed, skipped
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowEvent(Base):
    """Events in the workflow event bus."""
    __tablename__ = "workflow_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)
    source = Column(String(128), nullable=True)
    payload = Column(JSON, nullable=True)
    processed = Column(Boolean, default=False)
    workflow_id = Column(UUID(as_uuid=True), index=True, nullable=True)  # Target workflow if any
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

"""Workflow execution engine."""

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .models import WorkflowDefinition, WorkflowRun, WorkflowStepResult


class WorkflowExecutor:
    """Executes workflow steps."""

    def __init__(self):
        self.step_handlers = {
            "http_request": self._execute_http_request,
            "llm_completion": self._execute_llm_completion,
            "memory_search": self._execute_memory_search,
            "agent_execute": self._execute_agent_execute,
            "send_notification": self._execute_notification,
            "transform_data": self._execute_transform,
            "condition": self._execute_condition,
            "delay": self._execute_delay,
        }

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
        session,
    ) -> Dict[str, Any]:
        """Execute all steps in a workflow."""
        steps = workflow.steps or []
        context = {
            "input": run.input_data or {},
            "steps": {},
            "user_id": str(run.user_id) if getattr(run, "user_id", None) else None,
        }

        run.status = "running"
        run.started_at = datetime.utcnow()
        await session.commit()

        try:
            for i, step in enumerate(steps):
                await session.refresh(run)
                if run.status == "cancelled":
                    if not run.completed_at:
                        run.completed_at = datetime.utcnow()
                    run.output_data = context
                    await session.commit()
                    return {"status": "cancelled"}

                run.current_step = i
                await session.commit()

                step_result = await self._execute_step(
                    step=step,
                    step_index=i,
                    run_id=run.id,
                    context=context,
                    session=session,
                )

                context["steps"][step.get("name", f"step_{i}")] = step_result

                if step_result.get("status") == "failed":
                    # Check if step has error handling
                    if not step.get("continue_on_error", False):
                        run.status = "failed"
                        run.error_message = step_result.get("error")
                        run.completed_at = datetime.utcnow()
                        await session.commit()
                        return {"status": "failed", "error": step_result.get("error")}

            # All steps completed
            run.status = "completed"
            run.output_data = context
            run.completed_at = datetime.utcnow()
            await session.commit()

            return {"status": "completed", "output": context}

        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)
            run.completed_at = datetime.utcnow()
            await session.commit()
            return {"status": "failed", "error": str(e)}

    async def _execute_step(
        self,
        step: Dict[str, Any],
        step_index: int,
        run_id,
        context: Dict[str, Any],
        session,
    ) -> Dict[str, Any]:
        """Execute a single workflow step."""
        step_type = step.get("type", "unknown")
        step_name = step.get("name", f"step_{step_index}")
        step_config = step.get("config", {})

        start_time = time.time()

        # Create step result record
        step_result = WorkflowStepResult(
            run_id=run_id,
            step_index=step_index,
            step_name=step_name,
            status="running",
            input_data=step_config,
        )
        session.add(step_result)
        await session.commit()

        try:
            # Get handler for step type
            handler = self.step_handlers.get(step_type)
            if not handler:
                raise ValueError(f"Unknown step type: {step_type}")

            # Execute step
            result = await handler(step_config, context)

            # Update step result
            duration_ms = int((time.time() - start_time) * 1000)
            step_result.status = "completed"
            step_result.output_data = result
            step_result.duration_ms = duration_ms
            await session.commit()

            return {"status": "completed", "output": result}

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            step_result.status = "failed"
            step_result.error_message = str(e)
            step_result.duration_ms = duration_ms
            await session.commit()

            return {"status": "failed", "error": str(e)}

    # Step Handlers
    async def _execute_http_request(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an HTTP request step."""
        method = config.get("method", "GET")
        url = self._interpolate(config.get("url", ""), context)
        headers = config.get("headers", {})
        body = config.get("body")

        if body:
            body = self._interpolate_dict(body, context)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body if method in ("POST", "PUT", "PATCH") else None,
            )

            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:1000],
            }

    async def _execute_llm_completion(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an LLM completion step."""
        prompt = self._interpolate(config.get("prompt", ""), context)
        model = config.get("model", "gpt-4-turbo-preview")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "http://llm_service:8000/llm/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "model": model,
                        "max_tokens": config.get("max_tokens", 1024),
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "content": data["choices"][0]["message"]["content"],
                        "model": data["model"],
                    }
                return {"error": f"LLM request failed: {response.status_code}"}
        except httpx.RequestError as e:
            return {"error": str(e)}

    async def _execute_memory_search(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a memory search step."""
        query = self._interpolate(config.get("query", ""), context)
        user_id = config.get("user_id")
        limit = config.get("limit", 5)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://memory_service:8000/memory/retrieve",
                    json={
                        "query": query,
                        "user_id": user_id,
                        "limit": limit,
                    },
                )
                if response.status_code == 200:
                    return {"memories": response.json()}
                return {"error": f"Memory search failed: {response.status_code}"}
        except httpx.RequestError as e:
            return {"error": str(e)}

    async def _execute_agent_execute(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        agent_id = config.get("agent_id")
        if not agent_id:
            raise ValueError("agent_execute step requires config.agent_id")

        task = self._interpolate(str(config.get("task", "")), context).strip()
        if not task:
            task = "Run workflow step"

        agent_engine_base = os.getenv(
            "AGENT_ENGINE_SERVICE_URL", "http://agent_engine_service:8000"
        ).rstrip("/")
        url = f"{agent_engine_base}/execution/agents/{agent_id}/execute"

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        user_id = context.get("user_id")
        if user_id:
            headers["x-user-id"] = str(user_id)

        payload: Dict[str, Any] = {
            "task": task,
            "context": config.get("context"),
            "available_tools": config.get("available_tools"),
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise ValueError(
                f"agent_engine_service returned {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        if data.get("success") is False:
            raise ValueError(data.get("error") or "Agent execution failed")

        return data

    async def _execute_notification(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a notification step (placeholder)."""
        channel = config.get("channel", "log")
        message = self._interpolate(config.get("message", ""), context)

        # In production, integrate with notification services
        return {
            "channel": channel,
            "message": message,
            "sent": True,
        }

    async def _execute_transform(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a data transformation step."""
        expression = config.get("expression", "")
        
        # Simple key extraction (in production, use a proper expression language)
        if expression.startswith("$."):
            path = expression[2:].split(".")
            value = context
            for key in path:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    value = None
                    break
            return {"result": value}

        return {"result": expression}

    async def _execute_condition(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a condition check step."""
        left = self._interpolate(str(config.get("left", "")), context)
        operator = config.get("operator", "==")
        right = self._interpolate(str(config.get("right", "")), context)

        result = False
        if operator == "==":
            result = left == right
        elif operator == "!=":
            result = left != right
        elif operator == ">":
            result = float(left) > float(right)
        elif operator == "<":
            result = float(left) < float(right)
        elif operator == "contains":
            result = right in left

        return {"result": result, "left": left, "right": right}

    async def _execute_delay(
        self, config: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a delay step."""
        import asyncio
        seconds = config.get("seconds", 1)
        await asyncio.sleep(min(seconds, 60))  # Max 60 seconds
        return {"delayed": seconds}

    # Helper methods
    def _interpolate(self, template: str, context: Dict[str, Any]) -> str:
        """Interpolate variables in a template string."""
        result = template
        
        # Replace {{input.key}} patterns
        import re
        pattern = r"\{\{(\w+)\.(\w+)\}\}"
        
        def replace(match):
            section = match.group(1)
            key = match.group(2)
            if section in context and isinstance(context[section], dict):
                return str(context[section].get(key, match.group(0)))
            return match.group(0)

        return re.sub(pattern, replace, result)

    def _interpolate_dict(self, data: Dict, context: Dict[str, Any]) -> Dict:
        """Interpolate variables in a dictionary."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._interpolate(value, context)
            elif isinstance(value, dict):
                result[key] = self._interpolate_dict(value, context)
            else:
                result[key] = value
        return result


workflow_executor = WorkflowExecutor()

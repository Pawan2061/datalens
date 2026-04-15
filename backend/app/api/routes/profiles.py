from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from app.agent.models import AgentEvent, AgentEventType
from app.agent.profiler import (
    generate_workspace_profile,
    load_profile,
    delete_profile,
)
from app.api.routes.users import get_current_user
from app.db.connection_manager import connection_manager
from app.db.insight_db import insight_db
from app.schemas.profile import ProfileGenerateRequest, ProfileStatusResponse, ProfileUpdateQuestionsRequest

router = APIRouter()

# In-memory queues for profile generation progress SSE
_profile_queues: dict[str, asyncio.Queue] = {}


@router.post("/api/workspaces/{workspace_id}/profile/generate")
async def start_profile_generation(
    workspace_id: str,
    request: ProfileGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Start async profile generation for a workspace connection."""
    queue: asyncio.Queue = asyncio.Queue()
    queue_key = f"{workspace_id}:{request.connection_id}"
    _profile_queues[queue_key] = queue

    asyncio.create_task(
        _run_profile_generation(
            workspace_id=workspace_id,
            connection_id=request.connection_id,
            queue_key=queue_key,
            queue=queue,
        )
    )

    return {"status": "generating", "workspace_id": workspace_id}


async def _run_profile_generation(
    workspace_id: str,
    connection_id: str,
    queue_key: str,
    queue: asyncio.Queue,
) -> None:
    """Background task to generate the profile."""
    try:
        # Look up the human-readable connection name from connection_manager
        conn_entry = connection_manager._connections.get(connection_id)
        connection_name = ""
        if conn_entry and conn_entry.get("config"):
            connection_name = getattr(conn_entry["config"], "name", "") or ""

        await generate_workspace_profile(
            connection_id=connection_id,
            workspace_id=workspace_id,
            connection_name=connection_name,
            queue=queue,
        )
    except Exception as e:
        await queue.put(
            AgentEvent(
                event_type=AgentEventType.error,
                data={"message": str(e)},
            )
        )
    finally:
        await queue.put(None)  # Signal done
        # Keep the queue around briefly so late-connecting SSE clients can drain it
        await asyncio.sleep(30)
        _profile_queues.pop(queue_key, None)


@router.get("/api/workspaces/{workspace_id}/profile/stream/{connection_id}")
async def profile_stream(
    workspace_id: str,
    connection_id: str,
):
    """SSE endpoint for profile generation progress.

    If the in-memory queue exists (same instance that started generation),
    streams real-time events. Otherwise, falls back to polling Cosmos DB
    status — this handles Cloud Run multi-instance deployments gracefully.
    """
    queue_key = f"{workspace_id}:{connection_id}"

    # Retry loop: the profile generation task may not have created the queue yet
    queue = _profile_queues.get(queue_key)
    if queue is None:
        for _ in range(10):  # wait up to 5 seconds (10 x 0.5s)
            await asyncio.sleep(0.5)
            queue = _profile_queues.get(queue_key)
            if queue is not None:
                break

    if queue is not None:
        # ── Real-time queue streaming (same instance) ──
        async def event_generator():
            while True:
                event = await queue.get()
                if event is None:
                    yield {"event": "done", "data": json.dumps({"status": "complete"})}
                    break

                if isinstance(event, AgentEvent):
                    yield {
                        "event": event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                        "data": json.dumps(event.data, default=str),
                    }
                else:
                    yield {"event": "message", "data": json.dumps(event, default=str)}

            _profile_queues.pop(queue_key, None)

        return EventSourceResponse(event_generator())

    # ── Fallback: poll Cosmos DB status (different instance / late connect) ──
    async def polling_generator():
        yield {
            "event": "thinking",
            "data": json.dumps({"content": "Generating data intelligence profile..."}),
        }
        for _ in range(120):  # poll for up to ~6 minutes (120 x 3s)
            await asyncio.sleep(3)
            try:
                doc = await load_profile(workspace_id, connection_id)
                if doc is None:
                    continue
                if doc.status == "ready":
                    yield {
                        "event": "thinking",
                        "data": json.dumps({"content": "Profile generation complete!"}),
                    }
                    yield {"event": "done", "data": json.dumps({"status": "complete"})}
                    return
                elif doc.status == "failed":
                    yield {
                        "event": "error",
                        "data": json.dumps({"message": doc.error_message or "Profile generation failed"}),
                    }
                    yield {"event": "done", "data": json.dumps({"status": "complete"})}
                    return
                # Still generating — send a heartbeat so the connection stays alive
                yield {
                    "event": "thinking",
                    "data": json.dumps({"content": "Still analyzing your data..."}),
                }
            except Exception:
                continue
        # Timed out
        yield {
            "event": "error",
            "data": json.dumps({"message": "Profile generation timed out. Check status later."}),
        }
        yield {"event": "done", "data": json.dumps({"status": "complete"})}

    return EventSourceResponse(polling_generator())


@router.get("/api/workspaces/{workspace_id}/profile")
async def get_profile(
    workspace_id: str,
    connection_id: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Get the stored profile for a workspace connection."""
    if not connection_id:
        raise HTTPException(status_code=400, detail="connection_id query parameter required")

    doc = await load_profile(workspace_id, connection_id)
    if doc is None:
        return ProfileStatusResponse(status="none").model_dump()

    return {
        "status": doc.status,
        "profile_id": doc.id,
        "generated_at": doc.generated_at,
        "connection_id": doc.connection_id,
        "connector_type": doc.connector_type,
        "error_message": doc.error_message,
        "generation_duration_ms": doc.generation_duration_ms,
        "raw_profile": doc.raw_profile,
        "profile_text": doc.profile_text,
    }


@router.put("/api/workspaces/{workspace_id}/profile/questions")
async def update_profile_questions(
    workspace_id: str,
    body: ProfileUpdateQuestionsRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update the directional questions and suggested questions in a profile."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "update_profile_questions: workspace_id=%s connection_id=%s",
        workspace_id, body.connection_id,
    )

    doc = await load_profile(workspace_id, body.connection_id)
    if doc is None:
        logger.warning(
            "Profile not found for workspace_id=%s connection_id=%s",
            workspace_id, body.connection_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Profile not found for workspace={workspace_id} connection={body.connection_id}",
        )

    # Update the raw_profile's directional_plan and suggested_questions
    raw = doc.raw_profile or {}
    raw["directional_plan"] = [q.model_dump() for q in body.directional_plan]
    raw["suggested_questions"] = body.suggested_questions

    # Persist to Cosmos DB
    container = insight_db.container("workspace_profiles")
    profile_id = f"profile-{body.connection_id}"
    try:
        cosmos_doc = container.read_item(item=profile_id, partition_key=workspace_id)
    except Exception as e:
        logger.warning("Cosmos read_item failed: %s", e)
        raise HTTPException(
            status_code=404,
            detail=f"Profile document not found in Cosmos: {profile_id} / {workspace_id}",
        )

    cosmos_doc["raw_profile"] = raw
    container.upsert_item(cosmos_doc)

    return {"status": "updated", "questions_count": len(body.directional_plan)}


@router.delete("/api/workspaces/{workspace_id}/profile")
async def remove_profile(
    workspace_id: str,
    connection_id: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Delete a profile to force re-generation."""
    if not connection_id:
        raise HTTPException(status_code=400, detail="connection_id query parameter required")

    deleted = await delete_profile(workspace_id, connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")

    return {"status": "deleted"}

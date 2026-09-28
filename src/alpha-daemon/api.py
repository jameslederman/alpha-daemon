import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode

from models import ResearchQuery, ResearchScope, ResearchSynthesis
from temporal_runtime import connect_temporal_client, temporal_task_queue


class ResearchQueryRequest(BaseModel):
    symbol: str
    objective: str
    as_of: datetime | None = None


class ResearchStartResponse(BaseModel):
    workflow_id: str
    status: str


class ResearchStatusResponse(BaseModel):
    workflow_id: str
    status: str
    result: ResearchSynthesis | None = None
    error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.temporal_client = await connect_temporal_client(
        use_pydantic_data_converter=True,
    )
    yield


app = FastAPI(
    title="AlphaDaemon API",
    version="0.1.0",
    lifespan=lifespan,
)


def require_api_key(
    api_key: Annotated[
        str | None,
        Header(alias="X-AlphaDaemon-Key"),
    ] = None,
) -> None:
    expected = os.getenv("ALPHA_DAEMON_API_KEY")

    if not expected:
        return

    if api_key is None or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/research",
    response_model=ResearchStartResponse,
    dependencies=[Depends(require_api_key)],
)
async def start_research(
    payload: ResearchQueryRequest,
    request: Request,
) -> ResearchStartResponse:
    symbol = payload.symbol.strip().upper()
    objective = payload.objective.strip()

    if not symbol:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="symbol must not be blank",
        )

    if not objective:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="objective must not be blank",
        )

    created_at = datetime.now(timezone.utc)
    as_of = payload.as_of or created_at

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="as_of must include a timezone",
        )

    as_of = as_of.astimezone(timezone.utc)

    if as_of > created_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="as_of cannot be in the future",
        )

    query = ResearchQuery(
        query_id=f"research_query:{uuid4()}",
        objective=objective,
        scope=ResearchScope(
            kind="security",
            attributes={"symbol": symbol},
        ),
        as_of=as_of,
        created_at=created_at,
    )

    await request.app.state.temporal_client.start_workflow(
        "ResearchOrchestratorWorkflow",
        query,
        id=query.query_id,
        task_queue=temporal_task_queue(),
    )

    return ResearchStartResponse(
        workflow_id=query.query_id,
        status="running",
    )


@app.get(
    "/research/{workflow_id}",
    response_model=ResearchStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_research(
    workflow_id: str,
    request: Request,
) -> ResearchStatusResponse:
    handle = request.app.state.temporal_client.get_workflow_handle(
        workflow_id,
        result_type=ResearchSynthesis,
    )

    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Research workflow not found",
            ) from exc
        raise

    workflow_status = description.status.name.lower()

    if description.status == WorkflowExecutionStatus.COMPLETED:
        result = await handle.result()
        return ResearchStatusResponse(
            workflow_id=workflow_id,
            status=workflow_status,
            result=result,
        )

    error: str | None = None
    failure_statuses = {
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    }

    if description.status in failure_statuses:
        try:
            await handle.result()
        except WorkflowFailureError as exc:
            error = str(exc)

    return ResearchStatusResponse(
        workflow_id=workflow_id,
        status=workflow_status,
        error=error,
    )

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from models import ResearchScope, ResearchTask
from workflows import ResearchTaskWorkflow


def parse_as_of(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("as-of must be an ISO 8601 datetime") from exc

    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("as-of must include a timezone")

    return dt.astimezone(timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one skill-scoped AlphaDaemon research task"
    )
    parser.add_argument("symbol", help="Security ticker to research")
    parser.add_argument(
        "objective",
        help="Specific research objective for the selected skill",
    )
    parser.add_argument(
        "--skill",
        default="fundamental_analysis",
        help="Registered research skill (default: fundamental_analysis)",
    )
    parser.add_argument(
        "--as-of",
        type=parse_as_of,
        default=None,
        help="Point-in-time knowledge cutoff",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    as_of = args.as_of or datetime.now(timezone.utc)

    task = ResearchTask(
        task_id=f"research_task:{uuid4()}",
        skill=args.skill,
        objective=args.objective,
        scope=ResearchScope(
            kind="security",
            attributes={"symbol": args.symbol.strip().upper()},
        ),
        as_of=as_of,
    )

    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )

    result = await client.execute_workflow(
        ResearchTaskWorkflow.run,
        task,
        id=task.task_id,
        task_queue="my-task-queue",
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())

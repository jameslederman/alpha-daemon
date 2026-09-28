import os
from collections.abc import Sequence
from typing import Any

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter


def temporal_address() -> str:
    return os.getenv("TEMPORAL_ADDRESS", "localhost:7233")


def temporal_namespace() -> str:
    return os.getenv("TEMPORAL_NAMESPACE", "default")


def temporal_task_queue() -> str:
    return os.getenv("TEMPORAL_TASK_QUEUE", "my-task-queue")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"Invalid boolean value: {value!r}")


async def connect_temporal_client(
    *,
    plugins: Sequence[Any] | None = None,
    use_pydantic_data_converter: bool = False,
) -> Client:
    api_key = os.getenv("TEMPORAL_API_KEY")
    tls_env = os.getenv("TEMPORAL_TLS")

    tls = _parse_bool(tls_env) if tls_env is not None else bool(api_key)

    kwargs: dict[str, Any] = {
        "namespace": temporal_namespace(),
        "tls": tls,
    }

    if api_key:
        kwargs["api_key"] = api_key

    if plugins:
        kwargs["plugins"] = list(plugins)

    if use_pydantic_data_converter:
        kwargs["data_converter"] = pydantic_data_converter

    return await Client.connect(
        temporal_address(),
        **kwargs,
    )

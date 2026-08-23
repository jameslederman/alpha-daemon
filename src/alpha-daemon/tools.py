from typing import Any, Awaitable, Callable

from market_data import MarketDataProvider
from models import (
    GetPriceHistoryArgs,
    MarketBar,
    ToolRequest,
    ToolResult,
)


ToolHandler = Callable[..., Awaitable[Any]]


def get_handler(tool_name: str) -> ToolHandler:
    if tool_name == "get_price_history":
        return get_price_history

    raise ValueError(f"Unknown tool: {tool_name}")

async def execute_tool(
    request: ToolRequest,
    provider: MarketDataProvider,
) -> ToolResult:
    if request.tool_name == "get_price_history":
        args = GetPriceHistoryArgs.model_validate(request.arguments)

        output = await get_price_history(
            args=args,
            provider=provider,
        )

        return ToolResult(
            call_id=request.call_id,
            tool_name=request.tool_name,
            output=output,
        )

    raise ValueError(f"Unknown tool: {request.tool_name}")


async def get_price_history(
    args: GetPriceHistoryArgs,
    provider: MarketDataProvider,
) -> list[MarketBar]:
    return await provider.get_daily_bars(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
    )
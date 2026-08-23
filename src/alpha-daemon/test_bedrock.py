import asyncio

from llm import BedrockLLMClient


async def main():
    llm = BedrockLLMClient(
        model_id="amazon.nova-pro-v1:0",
    )

    response = await llm.generate(
        system_prompt="You are a financial research analyst.",
        user_prompt="In one sentence, explain what an earnings surprise is.",
    )

    print(response.text)
    print(f"Request ID: {response.request_id}")
    print(f"Model: {response.model_id}")
    print(f"Input tokens: {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}")
    print(f"Total tokens: {response.usage.total_tokens}")
    print(f"Latency: {response.latency_ms:.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())

from abc import ABC, abstractmethod
from dataclasses import dataclass
import asyncio
import time

import boto3


@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    # uncomment there when we add prompt caching
    # cache_read_tokens: int = 0
    # cache_write_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    model_id: str
    usage: LLMUsage
    latency_ms: float
    request_id: str


class LLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        pass


class BedrockLLMClient(LLMClient):
    def __init__(
        self,
        model_id: str,
        region_name: str = "us-east-1",
    ):
        self.model_id = model_id
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=region_name,
        )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        start_time = time.perf_counter()

        response = await asyncio.to_thread(
            self.client.converse,
            modelId=self.model_id,
            system=[
                {"text": system_prompt}
            ],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                }
            ],
            inferenceConfig={
                "temperature": 0.1,
                "maxTokens": 1000,
            },
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        text = response["output"]["message"]["content"][0]["text"]

        usage = response["usage"]

        request_id = response["ResponseMetadata"]["RequestId"]

        return LLMResponse(
            text=text,
            model_id=self.model_id,
            usage=LLMUsage(
                input_tokens=usage["inputTokens"],
                output_tokens=usage["outputTokens"],
                total_tokens=usage["totalTokens"],
            ),
            latency_ms=latency_ms,
            request_id=request_id,
        )
"""LLM integration module for AI model interactions."""

import os
import json
import asyncio
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass
import httpx


def _load_env_from_file(filepath: str):
    """Simple .env file loader."""
    if not os.path.exists(filepath):
        return

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ[key] = value


# Load environment variables
import pathlib
_project_root = pathlib.Path(__file__).parent.parent
_load_env_from_file(str(_project_root / ".env"))


@dataclass
class LLMContentPart:
    """Content part for LLM messages."""
    type: str
    content: Any
    cache_control: Optional[Dict[str, Any]] = None


@dataclass
class LLMMessage:
    """Message for LLM API."""
    role: str  # "system", "user", "assistant"
    content: Union[str, List[LLMContentPart]]


@dataclass
class ChatCompletionResponse:
    """Response from chat completion API."""
    id: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, int]] = None


class LLMClient:
    """Client for interacting with LLM APIs."""

    def __init__(self):
        """Initialize LLM client with configuration from .env."""
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

        # Clean up model name if needed
        if self.model.startswith("OpenAI/"):
            self.model = self.model.replace("OpenAI/", "")

    async def generate_completion(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> ChatCompletionResponse:
        """Generate a completion from the LLM."""
        use_model = model or self.model
        use_api_base = api_base or self.api_base
        use_api_key = api_key or self.api_key

        # Convert messages to API format
        api_messages = []
        for msg in messages:
            if isinstance(msg.content, str):
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            else:
                # Handle structured content
                api_messages.append({
                    "role": msg.role,
                    "content": [self._convert_content_part(part) for part in msg.content]
                })

        payload = {
            "model": use_model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Content-Type": "application/json",
        }

        if use_api_key:
            headers["Authorization"] = f"Bearer {use_api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{use_api_base}/chat/completions"
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                error_text = response.text
                raise Exception(f"LLM API error ({response.status_code}): {error_text}")

            data = response.json()
            return ChatCompletionResponse(
                id=data.get("id", ""),
                choices=data.get("choices", []),
                usage=data.get("usage")
            )

    async def generate_completion_stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Generate a streaming completion from the LLM."""
        use_model = model or self.model
        use_api_base = api_base or self.api_base
        use_api_key = api_key or self.api_key

        # Convert messages to API format
        api_messages = []
        for msg in messages:
            if isinstance(msg.content, str):
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": [self._convert_content_part(part) for part in msg.content]
                })

        payload = {
            "model": use_model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        headers = {
            "Content-Type": "application/json",
        }

        if use_api_key:
            headers["Authorization"] = f"Bearer {use_api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{use_api_base}/chat/completions"
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise Exception(f"LLM API error ({response.status_code}): {error_text}")

                async for line in response.aiter_lines():
                    line = line.strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if data.get("choices"):
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

    def _convert_content_part(self, part: LLMContentPart) -> Dict[str, Any]:
        """Convert content part to API format."""
        result = {
            "type": part.type,
        }

        if part.type == "text":
            result["text"] = part.content
        elif part.type == "image_url":
            result["image_url"] = part.content
        elif part.type == "input_audio":
            result["input_audio"] = part.content

        if part.cache_control:
            result["cache_control"] = part.cache_control

        return result

    @staticmethod
    def strip_markdown_code_fences(text: str) -> str:
        """Strip markdown code fences from text."""
        import re
        # Remove ```json ... ``` or ``` ... ```
        pattern = r'```(?:json)?\s*(.*?)\s*```'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()


# Global LLM client instance
llm_client = LLMClient()


async def generate_completion(
    messages: List[LLMMessage],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    response_format: Optional[Dict[str, Any]] = None,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ChatCompletionResponse:
    """Generate a completion using the global LLM client."""
    return await llm_client.generate_completion(
        messages, model, temperature, max_tokens, response_format,
        api_base, api_key,
    )


async def generate_completion_stream(
    messages: List[LLMMessage],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """Generate a streaming completion using the global LLM client."""
    async for chunk in llm_client.generate_completion_stream(
        messages, model, temperature, max_tokens,
        api_base, api_key,
    ):
        yield chunk


def strip_markdown_code_fences(text: str) -> str:
    """Strip markdown code fences from text."""
    return LLMClient.strip_markdown_code_fences(text)

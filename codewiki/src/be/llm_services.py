"""
LLM service factory for creating configured LLM clients.

Includes a compatibility layer for OpenAI-compatible API proxies that may
return slightly non-standard responses (e.g. choices[].index = None).

Supports multiple providers: openai-compatible, anthropic, bedrock, azure-openai.

Tracing (CODEWIKI_LLM_TRACE): ``call_llm`` and pydantic-ai Agent traffic
(``CompatibleOpenAIModel.request`` / ``request_stream``; ``FallbackModel`` delegates).
CLI ``config validate`` connectivity probes write to ``CODEWIKI_LLM_TRACE_DIR`` (or
``~/.codewiki/llm_trace``) when tracing is enabled and no ``docs_dir/trace`` run exists.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import traceback
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from openai import (
    APIError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)
from openai.types import chat

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.settings import ModelSettings
from openai import OpenAI

from codewiki.src.config import Config
from codewiki.src.config import DEFAULT_MODEL_CONTEXT_WINDOW

logger = logging.getLogger(__name__)

# Async agent path: DocumentationGenerator.run() sets this so CompatibleOpenAIModel can resolve docs_dir/trace.
_llm_trace_config_ctx: contextvars.ContextVar[Optional[Config]] = contextvars.ContextVar(
    "llm_trace_config", default=None
)
_trace_path_lock = threading.Lock()
_trace_seq = 0

_LLM_TRACE_INPUT_BANNER = (
    "\n"
    + "=" * 80
    + "\nLLM TRACE — INPUT\n"
    + "=" * 80
    + "\n"
)
_LLM_TRACE_OUTPUT_BANNER = (
    "\n"
    + "=" * 80
    + "\nLLM TRACE — OUTPUT\n"
    + "=" * 80
    + "\n"
)


# ──────────────────────────────────────────────────────────────────
# Model context window auto-detection
# ──────────────────────────────────────────────────────────────────

# Exact match: model_id → context_window (tokens)
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic Claude models
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-4-20250514": 200_000,
    # OpenAI GPT-4 family
    "gpt-4o": 128_000,
    "gpt-4o-2024-08-06": 128_000,
    "gpt-4o-2024-11-20": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-turbo-2024-04-09": 128_000,
    "gpt-4-1106-preview": 128_000,
    "gpt-4-0125-preview": 128_000,
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-4-0613": 8_192,
    "gpt-3.5-turbo": 16_384,
    "gpt-3.5-turbo-16k": 16_384,
    "gpt-3.5-turbo-0125": 16_384,
    "gpt-3.5-turbo-1106": 16_384,
    # OpenAI o-series
    "o1": 200_000,
    "o1-mini": 200_000,
    "o1-preview": 128_000,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    # DeepSeek
    "deepseek-chat": 1_000_000,
    "deepseek-reasoner": 64_000,
    "deepseek-v3": 128_000,
    "deepseek-v3-pro": 128_000,
    "deepseek-v4": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
    # Gemini
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    # Qwen / Alibaba
    "qwen-max": 32_768,
    "qwen-plus": 32_768,
    "qwen-turbo": 8_192,
    "qwen2.5-72b-instruct": 32_768,
    # GLM / Zhipu
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    "glm-4-plus": 128_000,
    "glm-4-air": 128_000,
    "glm-4p5": 128_000,
    "glm-4.5": 128_000,
    # Mistral
    "mistral-large-latest": 128_000,
    "mistral-medium-latest": 32_000,
    "mistral-small-latest": 32_000,
    "codestral-latest": 32_000,
    # Grok
    "grok-2": 128_000,
    "grok-3": 1_000_000,
    # Llama
    "llama-3.1-405b": 128_000,
    "llama-3.1-70b": 128_000,
    "llama-3.1-8b": 128_000,
    "llama-3.2-90b": 128_000,
    "llama-3.3-70b": 128_000,
}

# Pattern-based matching: (regex, context_window)
# Checked in order; first match wins
_MODEL_PATTERN_WINDOWS: list[tuple[str, int]] = [
    # Anthropic — all Claude 3/4 models have 200K
    (r"^claude-3", 200_000),
    (r"^claude-4", 200_000),
    (r"^anthropic/claude-3", 200_000),
    (r"^anthropic/claude-4", 200_000),
    (r"^bedrock/anthropic\.claude", 200_000),
    # OpenAI GPT-4o variants
    (r"^gpt-4o", 128_000),
    (r"^o[1-9]", 200_000),  # o1, o3, o4 family
    (r"^gpt-4-turbo", 128_000),
    (r"^gpt-4-.*preview", 128_000),
    (r"^gpt-4-32k", 32_768),
    (r"^gpt-4[^-]", 8_192),  # gpt-4 (not gpt-4o, not gpt-4-turbo)
    (r"^gpt-3\.5", 16_384),
    # DeepSeek
    (r"^deepseek-v4", 1_000_000),
    (r"^deepseek-v3", 128_000),
    (r"^deepseek-r1", 128_000),
    (r"^deepseek", 64_000),
    # Gemini
    (r"^gemini-1\.5-pro", 2_097_152),
    (r"^gemini-1\.5-flash", 1_048_576),
    (r"^gemini-2", 1_048_576),
    (r"^gemini-2\.5", 1_048_576),
    # Qwen
    (r"^qwen.?max", 32_768),
    (r"^qwen.?plus", 32_768),
    (r"^qwen2\.5", 32_768),
    (r"^qwen", 8_192),
    # GLM
    (r"^glm-4", 128_000),
    # Mistral
    (r"^mistral-large", 128_000),
    (r"^mistral-medium", 32_000),
    (r"^mistral-small", 32_000),
    (r"^codestral", 32_000),
    # Grok
    (r"^grok-3", 1_000_000),
    (r"^grok", 128_000),
    # Llama
    (r"^llama-3\.[12]", 128_000),
    (r"^llama-3\.3", 128_000),
    (r"^meta-llama/llama-3", 128_000),
    # Bedrock patterns
    (r"^bedrock/", 200_000),  # Most Bedrock models are Claude-based
]


def detect_model_context_window(model_name: str) -> int | None:
    """
    Auto-detect the context window size for a given model name.

    Uses exact match lookup table first, then regex pattern matching.
    Returns None if no match found (caller should use a sensible default).

    >>> detect_model_context_window("claude-sonnet-4-20250514")
    200000
    >>> detect_model_context_window("gpt-4o")
    128000
    >>> detect_model_context_window("unknown-model-xyz")
    None
    """
    if not model_name:
        return None

    # Strip common provider prefixes for matching
    clean_name = model_name
    for prefix in ("bedrock/", "anthropic/", "openai/"):
        if clean_name.lower().startswith(prefix):
            clean_name = clean_name[len(prefix):]
            break

    # 1) Exact match (case-insensitive)
    key = model_name.lower()
    if key in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[key]
    if clean_name.lower() in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[clean_name.lower()]

    # 2) Pattern-based match
    import re
    for pattern, window in _MODEL_PATTERN_WINDOWS:
        if re.match(pattern, key, re.IGNORECASE):
            return window
        if re.match(pattern, clean_name, re.IGNORECASE):
            return window

    return None


def resolve_model_context_window(config) -> int:
    """
    Resolve the effective model context window for a Config instance.

    Priority:
    1. Explicitly configured config.model_context_window (if differs from default)
    2. Auto-detected from config.main_model name
    3. config.model_context_window default (65536)
    """
    if config.model_context_window != DEFAULT_MODEL_CONTEXT_WINDOW:
        return config.model_context_window

    detected = detect_model_context_window(config.main_model)
    if detected is not None:
        logger.debug(
            "Auto-detected context window %d for model %s",
            detected,
            config.main_model,
        )
        return detected

    logger.debug(
        "Could not auto-detect context window for %s, using default %d",
        config.main_model,
        config.model_context_window,
    )
    return config.model_context_window


def push_llm_trace_context(config: Config):
    """
    Bind Config for pydantic-ai Agent LLM calls (trace files use config.docs_dir/trace).
    Returns a token for pop_llm_trace_context.
    """
    return _llm_trace_config_ctx.set(config)


def pop_llm_trace_context(token) -> None:
    _llm_trace_config_ctx.reset(token)


def _trace_config_for_call(explicit: Optional[Config]) -> Optional[Config]:
    return explicit if explicit is not None else _llm_trace_config_ctx.get()


def _trace_enabled(cfg: Optional[Config]) -> bool:
    if cfg is None:
        return False
    return bool(getattr(cfg, "llm_trace_enabled", False))


def _llm_trace_env_enabled() -> bool:
    """True when CODEWIKI_LLM_TRACE is set (same semantics as Config.from_cli)."""
    t = os.getenv("CODEWIKI_LLM_TRACE", "").strip().lower()
    return t in ("1", "true", "yes", "on")


def standalone_llm_trace_root() -> str:
    """Directory for traces when no run uses ``docs_dir/trace`` (e.g. ``config validate``)."""
    return os.environ.get(
        "CODEWIKI_LLM_TRACE_DIR",
        os.path.expanduser("~/.codewiki/llm_trace"),
    )


def _allocate_trace_file_path(trace_root: str) -> str:
    global _trace_seq
    os.makedirs(trace_root, exist_ok=True)
    with _trace_path_lock:
        _trace_seq += 1
        seq = _trace_seq
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"llm_{ts}_{seq:06d}.txt"
    return os.path.join(trace_root, fname)


def _serialize_trace_obj(obj: Any) -> str:
    try:
        if hasattr(obj, "model_dump"):
            return json.dumps(obj.model_dump(mode="json"), ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return repr(obj)


def _format_model_messages_for_trace(messages: list[ModelMessage]) -> str:
    parts: list[str] = []
    for i, m in enumerate(messages):
        parts.append(f"--- message[{i}] ---")
        parts.append(_serialize_trace_obj(m))
    return "\n".join(parts)


def write_llm_trace_event(
    trace_root: str,
    *,
    input_text: str,
    output_text: Optional[str],
    model_name: str,
    source: str,
    trace_label: Optional[str] = None,
    error_text: Optional[str] = None,
) -> None:
    """Write one LLM-related event to a new file under ``trace_root``."""
    path = _allocate_trace_file_path(trace_root)
    label_line = f"label={trace_label}\n" if trace_label else ""
    meta = (
        f"model={model_name}\nsource={source}\n{label_line}"
        f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
    )
    chunks = [
        meta,
        _LLM_TRACE_INPUT_BANNER,
        input_text,
    ]
    if error_text:
        chunks.append(
            "\n"
            + "=" * 80
            + "\nLLM TRACE — ERROR\n"
            + "=" * 80
            + "\n"
        )
        chunks.append(error_text)
    chunks.append(_LLM_TRACE_OUTPUT_BANNER)
    chunks.append("" if output_text is None else str(output_text))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(chunks))
    except OSError as e:
        logger.warning("LLM trace write failed (%s): %s", path, e)


def write_llm_trace_standalone(
    *,
    input_text: str,
    output_text: Optional[str],
    model_name: str,
    source: str,
    trace_label: Optional[str] = None,
    error_text: Optional[str] = None,
) -> None:
    """Trace when ``Config.docs_dir`` is not in use; gated by ``CODEWIKI_LLM_TRACE`` only."""
    if not _llm_trace_env_enabled():
        return
    write_llm_trace_event(
        standalone_llm_trace_root(),
        input_text=input_text,
        output_text=output_text,
        model_name=model_name,
        source=source,
        trace_label=trace_label,
        error_text=error_text,
    )


def write_llm_trace_file(
    cfg: Config,
    *,
    input_text: str,
    output_text: Optional[str],
    model_name: str,
    source: str,
    trace_label: Optional[str] = None,
    error_text: Optional[str] = None,
) -> None:
    """Append one LLM exchange to a new file under docs_dir/trace/."""
    if not _trace_enabled(cfg):
        return
    write_llm_trace_event(
        os.path.join(cfg.docs_dir, "trace"),
        input_text=input_text,
        output_text=output_text,
        model_name=model_name,
        source=source,
        trace_label=trace_label,
        error_text=error_text,
    )


def _should_use_max_completion_tokens(model_name: str, base_url: str) -> bool:
    """
    Determine whether to use max_completion_tokens instead of max_tokens.

    Newer OpenAI models (o1, o3, gpt-4o, etc.) require max_completion_tokens.
    Anthropic and other providers still use max_tokens.
    """
    model_lower = model_name.lower()
    # OpenAI models that require max_completion_tokens
    new_openai_patterns = ("o1", "o3", "gpt-4o", "gpt-4-turbo")
    if any(pattern in model_lower for pattern in new_openai_patterns):
        return True
    # If base_url points to OpenAI directly, newer models may need it
    if base_url and "api.openai.com" in base_url:
        return True
    return False


def _build_model_settings(config: Config, model_name: str) -> OpenAIModelSettings:
    """Build model settings with the correct token parameter."""
    if _should_use_max_completion_tokens(model_name, config.llm_base_url):
        return OpenAIModelSettings(
            temperature=0.0,
            max_completion_tokens=config.max_tokens
        )
    return OpenAIModelSettings(
        temperature=0.0,
        max_tokens=config.max_tokens
    )


def _get_litellm_model_name(model_name: str, provider: str) -> str:
    """
    Get the litellm-compatible model name for a given provider.

    For Bedrock, prefixes the model name with 'bedrock/' if not already prefixed.
    For Anthropic, prefixes with 'anthropic/' if not already prefixed.
    """
    if provider == "bedrock":
        if not model_name.startswith("bedrock/"):
            return f"bedrock/{model_name}"
    elif provider == "anthropic":
        if not model_name.startswith("anthropic/"):
            return f"anthropic/{model_name}"
    return model_name


class CompatibleOpenAIModel(OpenAIModel):
    """OpenAIModel subclass that patches non-standard API proxy responses.

    Some OpenAI-compatible proxies return responses with fields like
    choices[].index set to None instead of an integer. This subclass
    fixes those fields before pydantic validation runs.
    """

    def _validate_completion(self, response: chat.ChatCompletion) -> chat.ChatCompletion:
        # Patch choices[].index: None -> sequential integer (0, 1, 2, ...)
        if response.choices:
            for i, choice in enumerate(response.choices):
                if choice.index is None:
                    choice.index = i
        return super()._validate_completion(response)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        cfg = _llm_trace_config_ctx.get()
        try:
            result = await super().request(messages, model_settings, model_request_parameters)
            if _trace_enabled(cfg):
                write_llm_trace_file(
                    cfg,
                    input_text=_format_model_messages_for_trace(messages),
                    output_text=_serialize_trace_obj(result),
                    model_name=str(self.model_name),
                    source="pydantic_agent",
                    trace_label="pydantic_ai_agent_request",
                )
            return result
        except Exception:
            if _trace_enabled(cfg):
                write_llm_trace_file(
                    cfg,
                    input_text=_format_model_messages_for_trace(messages),
                    output_text=None,
                    model_name=str(self.model_name),
                    source="pydantic_agent",
                    trace_label="pydantic_ai_agent_request",
                    error_text=traceback.format_exc(),
                )
            raise

    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        cfg = _llm_trace_config_ctx.get()
        try:
            async for item in super().request_stream(
                messages, model_settings, model_request_parameters, run_context
            ):
                yield item
        except Exception:
            if _trace_enabled(cfg):
                write_llm_trace_file(
                    cfg,
                    input_text=_format_model_messages_for_trace(messages),
                    output_text=None,
                    model_name=str(self.model_name),
                    source="pydantic_agent",
                    trace_label="pydantic_ai_request_stream",
                    error_text=traceback.format_exc(),
                )
            raise
        if _trace_enabled(cfg):
            write_llm_trace_file(
                cfg,
                input_text=_format_model_messages_for_trace(messages),
                output_text=(
                    "[streaming completed; token-level chunks are not aggregated in this trace]"
                ),
                model_name=str(self.model_name),
                source="pydantic_agent",
                trace_label="pydantic_ai_request_stream",
            )


def _create_litellm_openai_client(config: Config) -> OpenAI:
    """
    Create an OpenAI-compatible client backed by litellm's proxy.

    litellm translates OpenAI API calls to Bedrock, Anthropic, etc.
    """
    import litellm
    # Configure litellm for the provider
    if config.provider == "bedrock":
        import os
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)

    # litellm exposes an OpenAI-compatible Router we can use,
    # but the simplest path is to use litellm.completion() directly.
    # For pydantic-ai integration, we create a proxy client.
    return OpenAI(
        api_key=config.llm_api_key or "not-needed-for-bedrock",
        base_url=config.llm_base_url or "https://api.openai.com/v1",
    )


def create_main_model(config: Config) -> CompatibleOpenAIModel:
    """Create the main LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.main_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.main_model)
    )


def create_fallback_model(config: Config) -> CompatibleOpenAIModel:
    """Create the fallback LLM model from configuration."""
    return CompatibleOpenAIModel(
        model_name=config.fallback_model,
        provider=OpenAIProvider(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key
        ),
        settings=_build_model_settings(config, config.fallback_model)
    )


def create_fallback_models(config: Config) -> FallbackModel:
    """Create fallback models chain from configuration."""
    main = create_main_model(config)
    fallback = create_fallback_model(config)
    return FallbackModel(main, fallback)


def create_openai_client(config: Config) -> OpenAI:
    """Create OpenAI client from configuration with timeout."""
    return OpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        timeout=httpx.Timeout(config.llm_timeout, connect=30.0),
        max_retries=0,  # We manage retries ourselves via tenacity
    )


def call_llm(
    prompt: str,
    config: Config,
    model: str = None,
    temperature: float = 0.0,
    trace_label: Optional[str] = None,
) -> str:
    """
    Call LLM with the given prompt.

    Supports openai-compatible, anthropic, and bedrock providers.
    For bedrock/anthropic, uses litellm to translate the API call.

    When config.llm_trace_enabled is True, each call writes prompt and response to
    docs_dir/trace/ (see write_llm_trace_file).

    Includes retry with exponential backoff for transient failures
    (rate limits, timeouts, server errors).

    Args:
        prompt: The prompt to send
        config: Configuration containing LLM settings
        model: Model name (defaults to config.main_model)
        temperature: Temperature setting
        trace_label: Optional tag in trace file metadata (e.g. ``cluster_modules`` vs ``parent_overview``).

    Returns:
        LLM response text
    """
    if model is None:
        model = config.main_model

    provider = getattr(config, "provider", "openai-compatible")
    cfg = _trace_config_for_call(config)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            InternalServerError,
        )),
        reraise=True,
    )
    def _do_call() -> str:
        if provider in ("bedrock", "anthropic"):
            return _call_llm_via_litellm(prompt, config, model, temperature)
        elif provider == "azure-openai":
            return _call_llm_via_azure(prompt, config, model, temperature)

        client = create_openai_client(config)
        token_kwargs = {}
        if _should_use_max_completion_tokens(model, config.llm_base_url):
            token_kwargs["max_completion_tokens"] = config.max_tokens
        else:
            token_kwargs["max_tokens"] = config.max_tokens

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            **token_kwargs
        )
        return response.choices[0].message.content

    try:
        raw = _do_call()
        out = raw if raw is not None else ""
        if _trace_enabled(cfg):
            write_llm_trace_file(
                cfg,
                input_text=prompt,
                output_text=out,
                model_name=model,
                source="call_llm",
                trace_label=trace_label,
            )
        return out
    except Exception:
        if _trace_enabled(cfg):
            write_llm_trace_file(
                cfg,
                input_text=prompt,
                output_text=None,
                model_name=model,
                source="call_llm",
                trace_label=trace_label,
                error_text=traceback.format_exc(),
            )
        raise


def _call_llm_via_litellm(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via litellm for Bedrock/Anthropic providers.

    litellm handles the provider-specific API translation automatically.
    """
    import litellm
    import os

    litellm_model = _get_litellm_model_name(model, config.provider)

    if config.provider == "bedrock":
        os.environ.setdefault("AWS_DEFAULT_REGION", config.aws_region)
        os.environ.setdefault("AWS_REGION_NAME", config.aws_region)
        logger.debug("Calling Bedrock model %s in region %s", litellm_model, config.aws_region)
    elif config.provider == "anthropic":
        logger.debug("Calling Anthropic model %s via litellm", litellm_model)

    response = litellm.completion(
        model=litellm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
        api_key=config.llm_api_key if config.provider != "bedrock" else None,
    )
    return response.choices[0].message.content


def _call_llm_via_azure(
    prompt: str,
    config: Config,
    model: str,
    temperature: float = 0.0
) -> str:
    """
    Call LLM via Azure OpenAI.

    Uses the AzureOpenAI client from the openai package with
    azure_endpoint, api_version, and deployment name.
    """
    from openai import AzureOpenAI

    client = AzureOpenAI(
        api_key=config.llm_api_key,
        api_version=config.api_version,
        azure_endpoint=config.llm_base_url,
    )

    deployment = config.azure_deployment or model
    logger.debug("Calling Azure OpenAI deployment %s (api_version=%s)", deployment, config.api_version)

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=config.max_tokens,
    )
    return response.choices[0].message.content

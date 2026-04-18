"""
LLM service factory for creating configured LLM clients.

Includes a compatibility layer for OpenAI-compatible API proxies that may
return slightly non-standard responses (e.g. choices[].index = None).

Supports multiple providers: openai-compatible, anthropic, bedrock, azure-openai.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
import traceback
from typing import Any, Optional

from openai.types import chat

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.settings import ModelSettings
from openai import OpenAI

from codewiki.src.config import Config

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


def _allocate_trace_file_path(cfg: Config) -> str:
    global _trace_seq
    trace_root = os.path.join(cfg.docs_dir, "trace")
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


def write_llm_trace_file(
    cfg: Config,
    *,
    input_text: str,
    output_text: Optional[str],
    model_name: str,
    source: str,
    error_text: Optional[str] = None,
) -> None:
    """Append one LLM exchange to a new file under docs_dir/trace/."""
    if not _trace_enabled(cfg):
        return
    path = _allocate_trace_file_path(cfg)
    meta = f"model={model_name}\nsource={source}\ntimestamp={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
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
                    error_text=traceback.format_exc(),
                )
            raise


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
    """Create OpenAI client from configuration."""
    return OpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key
    )


def call_llm(
    prompt: str,
    config: Config,
    model: str = None,
    temperature: float = 0.0
) -> str:
    """
    Call LLM with the given prompt.

    Supports openai-compatible, anthropic, and bedrock providers.
    For bedrock/anthropic, uses litellm to translate the API call.

    When config.llm_trace_enabled is True, each call writes prompt and response to
    docs_dir/trace/ (see write_llm_trace_file).

    Args:
        prompt: The prompt to send
        config: Configuration containing LLM settings
        model: Model name (defaults to config.main_model)
        temperature: Temperature setting

    Returns:
        LLM response text
    """
    if model is None:
        model = config.main_model

    provider = getattr(config, "provider", "openai-compatible")
    cfg = _trace_config_for_call(config)

    try:
        if provider in ("bedrock", "anthropic"):
            raw = _call_llm_via_litellm(prompt, config, model, temperature)
        elif provider == "azure-openai":
            raw = _call_llm_via_azure(prompt, config, model, temperature)
        else:
            client = create_openai_client(config)

            token_kwargs = {}
            if _should_use_max_completion_tokens(model, config.llm_base_url):
                token_kwargs["max_completion_tokens"] = config.max_tokens
                logger.debug("Using max_completion_tokens=%d for model %s", config.max_tokens, model)
            else:
                token_kwargs["max_tokens"] = config.max_tokens

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                **token_kwargs
            )
            raw = response.choices[0].message.content

        out = raw if raw is not None else ""
        if _trace_enabled(cfg):
            write_llm_trace_file(
                cfg,
                input_text=prompt,
                output_text=out,
                model_name=model,
                source="call_llm",
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

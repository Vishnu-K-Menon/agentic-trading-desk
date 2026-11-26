"""Turn a model name into a model object for the Agents SDK, whoever the provider is."""

import os
from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel
from openai import AsyncOpenAI
from . import config  # noqa: F401  (loads the environment)

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
GROK_BASE_URL = "https://api.x.ai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Providers reached through their OpenAI-compatible endpoints: (name fragment, base URL, key variable).
COMPATIBLE = [
    ("claude", ANTHROPIC_BASE_URL, "ANTHROPIC_API_KEY"),
    ("deepseek", DEEPSEEK_BASE_URL, "DEEPSEEK_API_KEY"),
    ("grok", GROK_BASE_URL, "GROK_API_KEY"),
    ("gemini", GEMINI_BASE_URL, "GOOGLE_API_KEY"),
]

_clients: dict[str, AsyncOpenAI] = {}


def _client(base_url: str | None, key_variable: str) -> AsyncOpenAI:
    if key_variable not in _clients:
        _clients[key_variable] = AsyncOpenAI(base_url=base_url, api_key=os.getenv(key_variable) or "missing")
    return _clients[key_variable]


def get_model(model_name: str):
    if "/" in model_name:
        return OpenAIChatCompletionsModel(model=model_name, openai_client=_client(OPENROUTER_BASE_URL, "OPENROUTER_API_KEY"))
    for fragment, base_url, key_variable in COMPATIBLE:
        if fragment in model_name:
            return OpenAIChatCompletionsModel(model=model_name, openai_client=_client(base_url, key_variable))
    # OpenAI's own models use the Responses API; newer ones reject tools on Chat Completions.
    return OpenAIResponsesModel(model=model_name, openai_client=_client(None, "OPENAI_API_KEY"))

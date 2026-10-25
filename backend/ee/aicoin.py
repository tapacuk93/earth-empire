"""Kept as an alias: Earth Empire no longer uses the aicoin proxy. Claude is called directly with the
Anthropic API (ee/llm.py), and speech is transcribed on the box. The monitor imports this name."""
from .llm import (AIUnavailable, AicoinError, LLMError, NoApiKey, OutOfCoins, ProviderOutOfCredit,  # noqa: F401
                  claude, settings, transcribe, usd_for)

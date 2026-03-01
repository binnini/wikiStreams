"""Prompt package for the WikiStreams daily reporter.

The active prompt style is selected via the PROMPT_STYLE environment variable
(or config setting). Available styles: 'default', 'doro'.
"""

from importlib import import_module

from reporter.config import settings

_module = import_module(f"reporter.prompts.{settings.prompt_style}")

SYSTEM_PROMPT: str = _module.SYSTEM_PROMPT
build_user_message = _module.build_user_message

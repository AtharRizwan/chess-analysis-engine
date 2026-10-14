"""The coach through Claude Code (`claude -p`), on the Claude subscription Claude Code is signed in with.

The Claude API needs an API key and bills per token; a Claude Pro or Max plan doesn't include API credits.
This backend runs the user's own, unmodified Claude Code instead, so narrations count toward their plan's
usage limits. Claude Code does the signing in: the app never sees the login.

`ClaudeCodeClient` answers `client.beta.messages.create(**kwargs)` the way the Anthropic SDK does (a stop
reason, content blocks and usage), so the coach's call loop, checks and fallback work unchanged. Each call:

- runs in safe mode (no CLAUDE.md, hooks, plugins, skills or MCP servers) and with no tools, so all
  Claude can do is write the note;
- uses the coach's own system prompt and JSON schema, and saves no session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chess_analysis_engine.config import data_dir
from chess_analysis_engine.explain.coach_llm import CoachError

TIMEOUT = 180.0  # seconds, as for the API client
# Kept out of Claude Code's environment: an API key would be billed instead of the subscription, and
# CLAUDECODE marks a nested session (it's set when the server itself was started from Claude Code).
DROPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
NOT_SIGNED_IN = (
    "Claude Code isn't signed in: run `claude` in a terminal and sign in with your Claude account."
)
_SLOTS = threading.BoundedSemaphore(2)  # each call is a whole Claude Code process

Runner = Callable[..., subprocess.CompletedProcess[str]]


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}


def _text(content: Any) -> str:
    """A message's text: a string, or the text blocks in a list (dicts or SDK-like objects)."""
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict):
            block = SimpleNamespace(**block)
        if getattr(block, "type", None) == "text":
            texts.append(block.text)
    return "\n".join(texts)


def _prompt(messages: list[dict[str, Any]]) -> str:
    """The conversation as one prompt: `claude -p` takes a single message, so earlier replies are quoted."""
    parts = []
    for message in messages:
        text = _text(message["content"])
        parts.append(f"Your previous reply:\n{text}" if message["role"] == "assistant" else text)
    return "\n\n".join(parts)


def _parse(stdout: str) -> dict[str, Any] | None:
    try:
        result = json.loads(stdout)
    except ValueError:
        return None
    return result if isinstance(result, dict) else None


def _response(result: dict[str, Any]) -> SimpleNamespace:
    """Claude Code's result in the shape of an API response."""
    note = result.get("structured_output")
    text = json.dumps(note) if note is not None else result.get("result")
    usage = result.get("usage") or {}
    return SimpleNamespace(
        stop_reason="refusal" if note is None and result.get("stop_reason") == "refusal" else "end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)] if text else [],
        usage=SimpleNamespace(**{k: usage.get(k) or 0 for k in USAGE_FIELDS}),
    )


def _error(result: dict[str, Any]) -> CoachError:
    status = result.get("api_error_status")
    detail = str(result.get("result") or "; ".join(result.get("errors") or []) or result.get("subtype"))
    if status == 401 or "login" in detail.lower():
        return CoachError(NOT_SIGNED_IN, 401)
    if status == 429:
        return CoachError(f"Claude Code hit a usage limit: {detail}", 429)
    if status == 404:
        return CoachError(f"Unknown model — check the coach model in Settings. ({detail})", 400)
    return CoachError(f"Claude Code failed: {detail}", 502)


class ClaudeCodeClient:
    """Answers `client.beta.messages.create(...)` like the Anthropic SDK, by running `claude -p`."""

    def __init__(self, executable: str, *, run: Runner = subprocess.run, cwd: Path | None = None):
        self.executable = executable
        self.run = run
        self.cwd = cwd
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def command(self, model: str, effort: str, system: str, schema: dict[str, Any]) -> list[str]:
        return [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--system-prompt",
            system,
            "--model",
            model,
            "--effort",
            effort,
            "--tools",
            "",
            "--safe-mode",
            "--no-chrome",
            "--no-session-persistence",
        ]

    def create(
        self,
        *,
        model: str,
        system: Any,
        messages: list[dict[str, Any]],
        output_config: dict[str, Any],
        **_: Any,  # API-only options: max_tokens, betas, fallbacks
    ) -> SimpleNamespace:
        schema = output_config["format"]["schema"]
        argv = self.command(model, output_config["effort"], _text(system), schema)
        with _SLOTS:
            try:
                done = self.run(
                    argv,
                    input=_prompt(messages),
                    capture_output=True,
                    text=True,
                    env=child_env(),
                    cwd=self.cwd or data_dir(),
                    timeout=TIMEOUT,
                )
            except subprocess.TimeoutExpired as exc:
                raise CoachError(f"Claude Code didn't answer within {TIMEOUT:.0f} seconds.", 504) from exc
            except OSError as exc:
                raise CoachError(f"Couldn't start Claude Code: {exc}", 503) from exc
        result = _parse(done.stdout)
        if result is None:
            detail = (done.stderr or done.stdout).strip()[-500:] or f"exit code {done.returncode}"
            raise CoachError(f"Claude Code failed: {detail}", 502)
        if result.get("subtype") == "error_max_structured_output_retries":
            return _response({})  # no note: the template explanation is used, as for invalid JSON
        if result.get("is_error") or result.get("subtype") != "success":
            raise _error(result)
        return _response(result)


def make_cli_client(run: Runner = subprocess.run) -> ClaudeCodeClient:
    """A client for the installed Claude Code, or a CoachError saying what's missing."""
    executable = shutil.which("claude")
    if executable is None:
        raise CoachError("Claude Code isn't installed: there's no `claude` command on the PATH.", 503)
    try:
        done = run(
            [executable, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            env=child_env(),
            timeout=30,
        )
        status = _parse(done.stdout) or {}
    except (OSError, subprocess.TimeoutExpired):
        status = {}  # can't tell (an older Claude Code, say): the first narration will say what's wrong
    if status.get("loggedIn") is False:
        raise CoachError(NOT_SIGNED_IN, 503)
    return ClaudeCodeClient(executable, run=run)

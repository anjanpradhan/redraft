"""Improve provider: local SLM via Ollama (HTTP, structured JSON output)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from redraft.prompt import build_prompt, build_result

if TYPE_CHECKING:
    from redraft.base import ReviewResult

_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "revised": {"type": "string"},
        "change_notes": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["revised", "change_notes", "risk_flags"],
}


def review(text: str, mode: str, config: dict) -> ReviewResult:
    cfg = config.get("ollama", {})
    url = cfg.get("url", "http://localhost:11434").rstrip("/") + "/api/chat"
    prompt = build_prompt(mode, text, config)  # full template (with <message> spliced in)
    payload = {
        "model": cfg.get("model", "llama3.1:8b"),
        "stream": False,
        "options": {"temperature": 0.2},
        "format": _FORMAT_SCHEMA,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"cannot reach Ollama at {url} ({e}); is `ollama serve` running?") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"Ollama at {url} returned a non-JSON response") from None

    content = (data.get("message") or {}).get("content") if isinstance(data, dict) else None
    if not content:
        raise RuntimeError("Ollama returned an unexpected response")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("Ollama did not return valid JSON") from None
    result = build_result(parsed, "Ollama")
    result.prompt = prompt  # exactly what was sent to the model
    result.raw = content  # the model's raw response content, before JSON parsing
    return result

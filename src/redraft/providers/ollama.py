"""Improve provider: local SLM via Ollama (HTTP, structured JSON output)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from redraft.base import ReviewError
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
    prompt = build_prompt(mode, text, config)  # full template with message data spliced in
    payload = {
        "model": cfg.get("model", "llama3.2:3b"),
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
    except urllib.error.HTTPError as e:
        # The server answered (so it IS running) but rejected the request — surface its reason
        # rather than the misleading "is serve running?" hint. A 404 means the model isn't pulled.
        body = e.read().decode("utf-8", "replace").strip()
        try:
            detail = (json.loads(body) or {}).get("error", "") if body else ""
        except json.JSONDecodeError:
            detail = body
        if e.code == 404:
            raise ReviewError(
                f"Ollama has no model '{payload['model']}' — run: ollama pull {payload['model']}",
                provider="ollama",
                mode=mode,
                prompt=prompt,
                raw=body,
            ) from e
        raise ReviewError(
            f"Ollama at {url} returned HTTP {e.code}" + (f": {detail}" if detail else ""),
            provider="ollama",
            mode=mode,
            prompt=prompt,
            raw=body,
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ReviewError(
            f"cannot reach Ollama at {url} ({e}); is `ollama serve` running?",
            provider="ollama",
            mode=mode,
            prompt=prompt,
        ) from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ReviewError(
            f"Ollama at {url} returned a non-JSON response",
            provider="ollama",
            mode=mode,
            prompt=prompt,
            raw=raw,
        ) from None

    content = (data.get("message") or {}).get("content") if isinstance(data, dict) else None
    if not content:
        raise ReviewError(
            "Ollama returned an unexpected response",
            provider="ollama",
            mode=mode,
            prompt=prompt,
            raw=raw,
        )
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise ReviewError(
            "Ollama did not return valid JSON",
            provider="ollama",
            mode=mode,
            prompt=prompt,
            raw=content,
        ) from None
    try:
        result = build_result(parsed, "Ollama")
    except RuntimeError as e:
        raise ReviewError(str(e), provider="ollama", mode=mode, prompt=prompt, raw=content) from e
    result.prompt = prompt  # exactly what was sent to the model
    result.raw = content  # the model's raw response content, before JSON parsing
    return result

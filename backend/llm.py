"""One Anthropic client, model constants, JSON-tool helper, disk cache (see CONTRACT.md)."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

import anthropic

FAST = "claude-haiku-4-5-20251001"
STRONG = "claude-sonnet-5"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")

_client: anthropic.Anthropic | None = None
_client_lock = threading.Lock()
_log_lock = threading.Lock()
_log_counters: dict[str, int] = {}


def _get_client() -> anthropic.Anthropic:
    global _client
    with _client_lock:
        if _client is None:
            _client = anthropic.Anthropic(max_retries=3, timeout=180.0)
        return _client


def _cache_path(cache_key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha256(cache_key.encode("utf-8")).hexdigest() + ".json")


def _next_log_path(run_dir: str, model: str) -> str:
    llm_dir = os.path.join(run_dir, "llm")
    os.makedirs(llm_dir, exist_ok=True)
    with _log_lock:
        n = _log_counters.get(run_dir)
        if n is None:
            # resume numbering from whatever is on disk
            existing = [f for f in os.listdir(llm_dir) if f[:3].isdigit()]
            n = len(existing)
        n += 1
        _log_counters[run_dir] = n
    return os.path.join(llm_dir, f"{n:03d}_{model}.json")


def _supports_temperature(model: str) -> bool:
    # Sonnet 5 / Opus 5 / Fable reject sampling params with a 400.
    return not any(tag in model for tag in ("sonnet-5", "opus-5", "opus-4-7", "opus-4-8", "fable", "mythos"))


def _one_call(client, *, system, user, schema, model, cache_key, run_dir, extra_note: str | None):
    tool = {"name": "emit", "description": "Emit the structured result.", "input_schema": schema}
    content = user if not extra_note else user + "\n\n" + extra_note
    kwargs = dict(
        model=model,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": content}],
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit"},
    )
    if _supports_temperature(model):
        kwargs["temperature"] = 0
    t0 = time.time()
    resp = client.messages.create(**kwargs)
    elapsed = time.time() - t0
    result = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit":
            result = block.input
            break
    if run_dir:
        try:
            with open(_next_log_path(run_dir, model), "w", encoding="utf-8") as f:
                json.dump({
                    "request": {"model": model, "system": system, "user": content, "schema": schema,
                                "cache_key": cache_key},
                    "response": resp.model_dump(),
                    "elapsed_s": round(elapsed, 2),
                }, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
    return result


def _schema_ok(result, schema: dict) -> bool:
    if not isinstance(result, dict):
        return False
    for key in schema.get("required", []) or []:
        if key not in result:
            return False
    props = schema.get("properties") or {}
    for key, spec in props.items():
        if key in result and isinstance(spec, dict):
            t = spec.get("type")
            v = result[key]
            if t == "array" and not isinstance(v, list):
                return False
            if t == "object" and not isinstance(v, dict):
                return False
            if t == "string" and v is not None and not isinstance(v, str):
                return False
    return True


def call_json(*, system: str, user: str, schema: dict, model: str = FAST,
              cache_key: str | None = None, run_dir: str | None = None) -> dict:
    """Tool-use call with one forced tool; returns the tool input dict."""
    path = None
    if cache_key:
        path = _cache_path(model + "|" + cache_key)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, dict):
                    return cached
            except Exception:
                pass
    client = _get_client()
    result = None
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            result = _one_call(client, system=system, user=user, schema=schema, model=model,
                               cache_key=cache_key, run_dir=run_dir,
                               extra_note=None if attempt == 0 else "Return valid JSON for the tool.")
        except anthropic.BadRequestError as e:
            last_err = e
            result = None
        if result is not None and _schema_ok(result, schema):
            break
        result = None
    if result is None:
        raise RuntimeError(f"call_json failed for model {model}: {last_err or 'no valid tool_use returned'}")
    if path:
        try:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
            except OSError:
                pass  # read-only bundle (serverless): reads still work, writes are best-effort
        except Exception:
            pass
    return result


if __name__ == "__main__":
    schema = {"type": "object", "properties": {"answer": {"type": "string"}, "n": {"type": "integer"}},
              "required": ["answer", "n"]}
    for m in (FAST, STRONG):
        try:
            out = call_json(system="You answer briefly.", user="What is 2+3? Put the word in answer and the number in n.",
                            schema=schema, model=m)
            print(m, "OK", out)
        except Exception as e:
            print(m, "FAILED", type(e).__name__, str(e)[:300])

"""Vercel entry point: exposes the FastAPI app from backend/ as one ASGI function.

vercel.json rewrites every path to /api/index, and the function receives that
rewritten path — so restore the original request path from the forwarded headers
before FastAPI routes it. `?__debug=1` dumps what the function actually received.
"""
import json
import os
import sys
from urllib.parse import parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
os.environ.setdefault("CONCORD_SYNC", "1")

from api import app as _fastapi  # noqa: E402

_PATH_HEADERS = ("x-vercel-original-path", "x-forwarded-uri", "x-original-url", "x-rewrite-url",
                 "x-now-route-matches", "x-vercel-proxied-for")


def _headers(scope):
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


async def app(scope, receive, send):
    if scope["type"] == "http":
        hdrs = _headers(scope)
        path = scope.get("path", "")
        qs = scope.get("query_string", b"").decode("latin-1")
        if "__debug=1" in qs:
            body = json.dumps({"path": path, "raw_path": scope.get("raw_path", b"").decode("latin-1"),
                               "query": qs, "headers": hdrs}, indent=1).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        if path.rstrip("/") == "/api/index" or path == "/api/index.py":
            # the rewrite in vercel.json carries the original path as ?path=/...; Vercel appends
            # the request's own query params after it
            params = parse_qs(qs, keep_blank_values=True)
            orig = (params.get("path") or [None])[0] or next((hdrs[h] for h in _PATH_HEADERS if hdrs.get(h)), None)
            if orig:
                new_path = orig.split("?", 1)[0] or "/"
                rest = "&".join(part for part in qs.split("&") if part and not part.startswith("path="))
                scope = dict(scope)
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode("latin-1", "ignore")
                scope["query_string"] = rest.encode("latin-1", "ignore")
    await _fastapi(scope, receive, send)

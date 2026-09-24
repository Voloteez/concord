"""Vercel entry point: exposes the FastAPI app from backend/ as one ASGI function."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
os.environ.setdefault("CONCORD_SYNC", "1")

from api import app  # noqa: E402,F401

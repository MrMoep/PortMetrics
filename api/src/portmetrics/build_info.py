"""Runtime build metadata for image channel / bake time (set at Docker build)."""

from __future__ import annotations

import os

from portmetrics import __version__


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def image_channel() -> str:
    """`dev` | `release` | empty (local / unmarked builds)."""
    return _env("PORTMETRICS_CHANNEL").lower()


def built_at() -> str:
    """Human-readable build timestamp baked into the image (may be empty)."""
    return _env("PORTMETRICS_BUILT_AT")


def git_sha() -> str:
    return _env("PORTMETRICS_GIT_SHA")


def display_version() -> str:
    """User-facing version string; dev images always include build time when known."""
    channel = image_channel()
    stamped = built_at()
    if channel == "dev":
        if stamped:
            return f"{__version__}-dev · {stamped}"
        return f"{__version__}-dev"
    return __version__

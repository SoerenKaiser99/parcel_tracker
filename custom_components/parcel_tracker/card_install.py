"""Copy the bundled card into <config>/www so /local serves it from HA start."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from aiohttp.web_urldispatcher import StaticResource

from .const import CARD_URL, LOCAL_CARD_URL, VERSION

CARD_FILE = "parcel-tracker-card.js"
BUNDLED_CARD = Path(__file__).parent / "frontend" / CARD_FILE


def card_hash(content: bytes) -> str:
    """Short content hash so every changed card gets a URL clients never saw."""
    return hashlib.sha256(content).hexdigest()[:8]


def install_card(source: Path, target: Path) -> tuple[str, bool, bool]:
    """Copy source to target if the content differs (blocking, run in executor).

    Returns (hash, www_existed_before, written).
    """
    content = source.read_bytes()
    www_existed = target.parent.parent.is_dir()
    written = False
    if not target.is_file() or target.read_bytes() != content:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written = True
    return card_hash(content), www_existed, written


def local_is_served(hass: Any) -> bool | None:
    """Whether the running Home Assistant serves /local; None if that is unknown.

    The frontend registers the /local static route once at startup, and only if
    <config>/www exists at that moment. A www folder created later (by us or by
    another tool) is on disk but not served until the next restart: /local/...
    answers 404, and clients may cache that. So ask the router, not the disk.
    """
    app = getattr(getattr(hass, "http", None), "app", None)
    if app is None:
        return None
    return any(
        isinstance(resource, StaticResource) and resource.canonical == "/local"
        for resource in app.router.resources()
    )


def card_url(digest: str, use_local: bool) -> str:
    """Resource URL for the chosen serving path."""
    return f"{LOCAL_CARD_URL if use_local else CARD_URL}?v={VERSION}-{digest}"

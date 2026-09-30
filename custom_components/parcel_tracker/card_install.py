"""Copy the bundled card into <config>/www so /local serves it from HA start."""

from __future__ import annotations

import hashlib
from pathlib import Path

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


def card_url(digest: str, use_local: bool) -> str:
    """Resource URL for the chosen serving path."""
    return f"{LOCAL_CARD_URL if use_local else CARD_URL}?v={VERSION}-{digest}"

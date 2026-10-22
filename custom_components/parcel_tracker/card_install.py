"""Card URL and cleanup of the copy older versions left in <config>/www."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .const import CARD_URL, VERSION

_LOGGER = logging.getLogger(__name__)

CARD_FILE = "parcel-tracker-card.js"
BUNDLED_CARD = Path(__file__).parent / "frontend" / CARD_FILE


def card_hash(content: bytes) -> str:
    """Short content hash so every changed card gets a URL clients never saw."""
    return hashlib.sha256(content).hexdigest()[:8]


def remove_old_copy(www_dir: Path) -> bool:
    """Delete the card copy v0.3.x wrote to <www>/parcel_tracker (blocking).

    Only our own file goes, and our folder only if it is empty afterwards;
    anything else in www stays. Returns whether the card file was removed.
    Errors are logged, never raised.
    """
    folder = www_dir / "parcel_tracker"
    card = folder / CARD_FILE
    try:
        if folder.is_symlink() or card.is_symlink() or not card.is_file():
            return False  # never follow links out of www
        card.unlink()
        try:
            folder.rmdir()  # fails (and is ignored) when foreign files remain
        except OSError:
            pass
    except OSError as err:
        _LOGGER.warning("Could not remove the old card copy %s: %s", card, err)
        return False
    _LOGGER.info("Removed the old card copy %s; the card is served by the integration", card)
    return True


def card_url(digest: str) -> str:
    """Resource URL of the card served by the integration itself."""
    return f"{CARD_URL}?v={VERSION}-{digest}"

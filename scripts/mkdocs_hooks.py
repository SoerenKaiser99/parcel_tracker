"""MkDocs hook: make the static demo page work on the published site.

docs/demo/index.html loads the card straight from the repository
(``../../custom_components/parcel_tracker/frontend/parcel-tracker-card.js``), so that it
always shows the card as it is shipped. On the site that path leads out of the site. After
the build the card is therefore copied next to the demo and the script tag of the built
page (never of the source) points to the copy.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mkdocs.exceptions import PluginError

CARD = "custom_components/parcel_tracker/frontend/parcel-tracker-card.js"
SOURCE_TAG = f'<script src="../../{CARD}"></script>'
SITE_TAG = '<script src="parcel-tracker-card.js"></script>'


def on_post_build(config, **kwargs) -> None:
    root = Path(config["config_file_path"]).parent
    demo = Path(config["site_dir"]) / "demo"
    page = demo / "index.html"
    if not page.is_file():
        raise PluginError("docs/demo/index.html was not copied to the site")
    html = page.read_text(encoding="utf-8")
    if SOURCE_TAG not in html:
        raise PluginError("docs/demo/index.html no longer loads the card as expected")
    shutil.copyfile(root / CARD, demo / "parcel-tracker-card.js")
    page.write_text(html.replace(SOURCE_TAG, SITE_TAG), encoding="utf-8")

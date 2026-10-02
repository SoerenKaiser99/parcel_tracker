import json
from pathlib import Path

from custom_components.parcel_tracker import const

MANIFEST = Path(const.__file__).parent / "manifest.json"


def test_version_matches_manifest():
    assert const.VERSION == json.loads(MANIFEST.read_text())["version"]


def test_version_is_0_3_10():
    assert const.VERSION == "0.3.10"

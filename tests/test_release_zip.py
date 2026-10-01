"""The release asset that HACS downloads (hacs.json: zip_release)."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "build_release_zip.sh"
SOURCE = ROOT / "custom_components" / "parcel_tracker"

pytestmark = pytest.mark.skipif(
    shutil.which("zip") is None or shutil.which("bash") is None, reason="needs bash and zip"
)


def _build(out: Path) -> Path:
    result = subprocess.run(
        ["bash", str(SCRIPT), str(out)], capture_output=True, text=True, check=True
    )
    path = out / "parcel_tracker.zip"
    assert result.stdout.strip() == str(path.resolve())
    return path


def test_zip_has_the_integration_at_its_root(tmp_path):
    """HACS extracts the asset into custom_components/parcel_tracker/ as it is."""
    with zipfile.ZipFile(_build(tmp_path)) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
        manifest = archive.read("manifest.json")
    assert manifest == (SOURCE / "manifest.json").read_bytes()
    for name in (
        "__init__.py",
        "strings.json",
        "translations/de.json",
        "frontend/parcel-tracker-card.js",
        "brand/icon.png",
        "carriers/__init__.py",
        "mail/__init__.py",
    ):
        assert name in names, name
    assert not any(name.startswith(("custom_components", "/", "./")) for name in names)
    assert not any("__pycache__" in name or name.endswith((".pyc", ".DS_Store")) for name in names)


def test_zip_contains_exactly_the_source_files(tmp_path):
    expected = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
        and path.suffix not in (".pyc", ".pyo")
    }
    with zipfile.ZipFile(_build(tmp_path)) as archive:
        assert set(archive.namelist()) == expected


def test_zip_is_reproducible(tmp_path):
    first = _build(tmp_path / "a").read_bytes()
    second = _build(tmp_path / "b").read_bytes()
    assert first == second


def test_dist_is_ignored_and_the_script_is_executable():
    assert "dist/" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert SCRIPT.stat().st_mode & 0o111

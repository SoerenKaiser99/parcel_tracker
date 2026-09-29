from datetime import UTC, datetime

import pytest

from custom_components.parcel_tracker.models import Parcel
from custom_components.parcel_tracker.store import DuplicateParcel, ParcelStore

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


async def test_add_save_load(hass, hass_storage):
    store = ParcelStore(hass)
    await store.async_load()
    store.add(Parcel("09999999999901", "dpd", "auto", "Test", NOW, NOW))
    await store.async_save()

    fresh = ParcelStore(hass)
    await fresh.async_load()
    assert fresh.get("09999999999901").name == "Test"


async def test_duplicate_and_remove(hass):
    store = ParcelStore(hass)
    await store.async_load()
    store.add(Parcel("1", None, "auto", None, NOW, NOW))
    with pytest.raises(DuplicateParcel):
        store.add(Parcel("1", None, "auto", None, NOW, NOW))
    assert store.remove("1").number == "1"
    with pytest.raises(KeyError):
        store.remove("1")


async def test_load_skips_corrupt_entries(hass, hass_storage, caplog):
    """Test that malformed stored parcel entries are skipped with a warning."""
    valid_parcel = Parcel("VALID123", "dpd", "auto", "Valid", NOW, NOW)
    hass_storage["parcel_tracker"] = {
        "version": 1,
        "minor_version": 1,
        "key": "parcel_tracker",
        "data": {
            "parcels": [
                valid_parcel.to_dict(),  # Valid entry
                {"number": "X"},  # Missing required fields (added_at, last_change_at)
                {
                    "number": "Y",
                    "added_at": "not-a-date",
                    "last_change_at": "also-bad",
                },  # Bad ISO dates
            ]
        },
    }

    store = ParcelStore(hass)
    await store.async_load()

    # Only the valid parcel should be loaded
    assert len(store.parcels) == 1
    assert store.get("VALID123") is not None
    assert store.get("X") is None
    assert store.get("Y") is None

    # Check that warnings were logged
    assert "Skipping unreadable stored parcel" in caplog.text

from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.models import ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"


def _res():
    return TrackingResult(
        ParcelStatus.IN_TRANSIT, "x", None, None, None, "Bonn", None, None, None, []
    )


@pytest.fixture
async def entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    e.add_to_hass(hass)
    with patch(FETCH, return_value=_res()):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


async def test_services_roundtrip(hass, entry):
    with patch(FETCH, return_value=_res()):
        await hass.services.async_call(
            DOMAIN, "add_parcel",
            {"number": "0 0 3 4 0 9 9 9 9 9 9 9 9 9 9 9 9 9 0 1", "name": "Oma"},
            blocking=True,
        )
    coord = entry.runtime_data
    assert coord.store.get("00340999999999999901").name == "Oma"

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": "00340999999999999901"}, blocking=True
        )
    assert err.value.translation_key == "duplicate"

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "add_parcel", {"number": "TBA123"}, blocking=True)
    assert err.value.translation_key == "amazon"

    await hass.services.async_call(
        DOMAIN, "rename_parcel", {"number": "00340999999999999901", "name": "Neu"}, blocking=True
    )
    assert coord.store.get("00340999999999999901").name == "Neu"

    await hass.services.async_call(
        DOMAIN, "remove_parcel", {"number": "00340999999999999901"}, blocking=True
    )
    assert coord.store.get("00340999999999999901") is None

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "remove_parcel", {"number": "00340999999999999901"}, blocking=True
        )
    assert err.value.translation_key == "not_tracked"


async def test_unload(hass, entry):
    assert await hass.config_entries.async_unload(entry.entry_id)

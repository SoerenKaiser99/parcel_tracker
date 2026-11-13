"""Personen-Zuordnung: the persisted owner of a parcel (``Parcel.owner``/``owner_manual``)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_PERSONS, CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.mail.apply import _fold, apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .conftest import DAYTIME

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=BERLIN)
DHL = "00340999999999992557"
AMAZON = "AMZ99999999999994321"
ANNA = "person.anna"
BEN = "person.ben"


def _parcel(number=DHL, carrier="dhl", **fields) -> Parcel:
    return Parcel(number, carrier, "mail", "Fahrrad", NOW, NOW, **fields)


def test_owner_survives_round_trip():
    data = _parcel(owner=ANNA, owner_manual=True).to_dict()
    loaded = Parcel.from_dict(data)
    assert (loaded.owner, loaded.owner_manual) == (ANNA, True)


def test_old_store_and_bad_values_load_as_no_owner():
    data = _parcel().to_dict()
    del data["owner"], data["owner_manual"]
    loaded = Parcel.from_dict(data)
    assert (loaded.owner, loaded.owner_manual) == (None, False)
    for bad in (5, ["person.anna"], "anna", "sensor.anna", True, ""):
        loaded = Parcel.from_dict({**data, "owner": bad, "owner_manual": "yes"})
        assert (loaded.owner, loaded.owner_manual) == (None, False)


def _fold_case(parcel_fields, order_fields):
    order = Parcel(AMAZON, "amazon", "mail", None, NOW, NOW, **order_fields)
    parcel = _parcel(**parcel_fields)
    _fold({AMAZON: order, DHL: parcel}, parcel, order)
    return order.owner, order.owner_manual


def test_fold_target_owner_wins_else_the_others():
    assert _fold_case({"owner": BEN}, {"owner": ANNA}) == (ANNA, False)
    assert _fold_case(
        {"owner": BEN, "owner_manual": True}, {"owner": ANNA, "owner_manual": False}
    ) == (ANNA, False)
    assert _fold_case({"owner": BEN, "owner_manual": True}, {}) == (BEN, True)
    assert _fold_case({"owner": BEN}, {}) == (BEN, False)
    assert _fold_case({}, {"owner": ANNA, "owner_manual": True}) == (ANNA, True)
    assert _fold_case({}, {}) == (None, False)
    # "allen" set by hand on the order is an owner too: the parcel's owner does not win.
    assert _fold_case({"owner": BEN, "owner_manual": True}, {"owner_manual": True}) == (
        None, True,
    )  # fmt: skip
    assert _fold_case({"owner": BEN}, {"owner_manual": True}) == (None, True)


def _ali(number, ref, at):
    return MailUpdate(
        number, "aliexpress", ParcelStatus.IN_TRANSIT, at,
        title="Item", tracking_ref=ref, tracking_carrier="dhl",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("owner", "manual"), [(ANNA, True), (ANNA, False), (None, True), (None, False)]
)
def test_further_parcel_inherits_owner_and_the_manual_mark(owner, manual):
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, _ali("ALI100", DHL, NOW), NOW)
    parcels["ALI100"].owner, parcels["ALI100"].owner_manual = owner, manual
    later = NOW + timedelta(hours=1)
    apply_update(parcels, _ali("ALI100", "JJD000012978217606570", later), later)
    extra = parcels["JJD000012978217606570"]
    # "allen" set by hand (no owner, manual mark) stays "allen" on the further box too.
    assert (extra.owner, extra.owner_manual) == (owner, manual)


def test_new_box_of_an_order_inherits_owner_of_its_siblings():
    parcels: dict[str, Parcel] = {}
    first = MailUpdate("AMZ111", "amazon", ParcelStatus.IN_TRANSIT, NOW, title="Buch")
    apply_update(parcels, first, NOW)
    parcels["AMZ111"].owner, parcels["AMZ111"].owner_manual = ANNA, True
    later = NOW + timedelta(hours=1)
    second = MailUpdate("AMZ111", "amazon", ParcelStatus.IN_TRANSIT, later, title="Lampe")
    apply_update(parcels, second, later)
    assert len(parcels) == 2
    box = next(p for n, p in parcels.items() if n != "AMZ111")
    assert (box.owner, box.owner_manual) == (ANNA, True)


async def test_sensor_attribute_owner(hass, hass_storage, freezer):
    freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    parcels = [
        Parcel(DHL, "dhl", "mail", "Fahrrad", now, now, owner=ANNA),
        Parcel(AMAZON, "amazon", "mail", "Buch", now, now),
    ]
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels], "message_ids": []},
    }
    # The owner counts while she is a person set up under "Personen".
    persons = [{"person": ANNA, "addresses": ["anna@example.org"], "notify_targets": []}]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", "dhl_api_key": "k"},
        options={CONF_PERSONS: persons},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.paket_{DHL.lower()}").attributes["owner"] == ANNA
    assert hass.states.get(f"sensor.paket_{AMAZON.lower()}").attributes["owner"] is None

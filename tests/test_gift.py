"""Geschenkmodus: the flag ``Parcel.gift`` and how it is shown.

A gift is shown as "Geschenk · <neutral name>" everywhere, whatever the option
"Namen ausblenden" says and whatever name (also a typed one) the parcel has. Its public
tracking link and Amazon's shipment id are not given out in the sensor's attributes.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.mail.apply import _fold
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingResult,
    display_name,
    gift_name,
)
from custom_components.parcel_tracker.notification import build_notification

from .conftest import DAYTIME

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)
DHL = "00340999999999992557"
AMAZON = "AMZ99999999999994321"
GIFT_NAME = "Geschenk · DHL-Paket …2557"


def _result(status=ParcelStatus.IN_TRANSIT, eta=None):
    return TrackingResult(status, "Unterwegs", eta, None, None, None, "Packstation 1",
                          None, None, [])


def _parcel(number=DHL, carrier="dhl", name="Fahrrad", **fields) -> Parcel:
    return Parcel(number, carrier, "mail", name, NOW, NOW, **fields)


def test_gift_name_wins_over_manual_name_and_hide_names():
    p = _parcel(name_manual=True, gift=True)
    assert gift_name(p) == GIFT_NAME
    assert display_name(p, False) == display_name(p, True) == GIFT_NAME
    assert display_name(_parcel(gift=True, name=None), False) == GIFT_NAME
    assert display_name(_parcel(), False) == "Fahrrad"


def test_gift_survives_round_trip_and_old_store_loads_false():
    p = _parcel(gift=True)
    data = p.to_dict()
    assert Parcel.from_dict(data).gift is True
    del data["gift"]
    assert Parcel.from_dict(data).gift is False
    assert Parcel.from_dict({**data, "gift": "yes"}).gift is False


def test_notification_label_of_a_gift():
    p = _parcel(gift=True, result=_result(ParcelStatus.DELIVERED))
    for hide in (False, True):
        _, text = build_notification(p, ParcelStatus.IN_TRANSIT, NOW, hide_names=hide)
        assert text == f"✅ {GIFT_NAME} (DHL) wurde zugestellt"
        assert "Fahrrad" not in text
    p.result = _result(ParcelStatus.OUT_FOR_DELIVERY)
    _, text = build_notification(p, ParcelStatus.IN_TRANSIT, NOW)
    assert text.startswith(f"📦 {GIFT_NAME}")
    assert "Fahrrad" not in text


def test_fold_keeps_gift():
    for parcel_gift, order_gift in ((True, False), (False, True), (False, False)):
        order = Parcel(AMAZON, "amazon", "mail", None, NOW, NOW, gift=order_gift)
        parcel = _parcel(gift=parcel_gift)
        parcels = {AMAZON: order, DHL: parcel}
        _fold(parcels, parcel, order)
        assert DHL not in parcels
        assert order.gift is (parcel_gift or order_gift)


async def test_gift_sensor_hides_name_and_links_and_lists_follow(hass, hass_storage, freezer):
    freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    today = dt_util.as_local(now).date()
    later = now + timedelta(hours=2)
    kwargs = dict(last_poll_at=now, next_poll_at=later, tracking_ref=None)
    parcels = [
        Parcel(DHL, "dhl", "mail", "Fahrrad", now, now, name_manual=True, gift=True,
               result=_result(ParcelStatus.OUT_FOR_DELIVERY, today), **kwargs),
        Parcel(AMAZON, "amazon", "mail", "Fahrrad", now, now, gift=True,
               shipment_ids=["SHIP1"], result=_result(ParcelStatus.OUT_FOR_DELIVERY, today),
               **kwargs),
    ]
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in parcels], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    attrs = hass.states.get(f"sensor.paket_{DHL.lower()}").attributes
    assert attrs["name"] == GIFT_NAME
    assert attrs["gift"] is True
    assert attrs["tracking_url"] is None
    assert attrs["status_text"] == "Unterwegs"
    assert attrs["pickup_point"] == "Packstation 1"
    assert attrs["eta_date"] == today.isoformat()
    amazon = hass.states.get(f"sensor.paket_{AMAZON.lower()}").attributes
    assert amazon["amazon_shipment"] is None
    assert amazon["name"] == "Geschenk · Amazon-Bestellung …4321"

    listed = hass.states.get("sensor.pakete_heute").attributes["parcels"]
    assert GIFT_NAME in [item["name"] for item in listed]
    assert "Fahrrad" not in str(hass.states.get("sensor.pakete_heute").attributes)

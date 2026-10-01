"""Notification text: one German line per status change, free of private details."""

import inspect
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.parcel_tracker import notification
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
    carrier_name,
)
from custom_components.parcel_tracker.notification import (
    NOTIFY_EVENTS,
    TITLE,
    build_notification,
)

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)
NUMBER = "00340434161094042557"
# Everything private a parcel can carry; none of it may reach a notification.
CODE = "847261"
STATUS_TEXT = "Die Sendung wurde in der Garage abgelegt, Musterweg 5"
EVENT_TEXT = "Zugestellt an Nachbar Mustermann"
LOCATION = "Ablageort Carport"


def _parcel(status, name="Kopfhörer", carrier="dhl", **result) -> Parcel:
    fields = {
        "status_text": STATUS_TEXT,
        "eta_date": None,
        "eta_from": None,
        "eta_to": None,
        "location": LOCATION,
        "pickup_point": None,
        "pickup_until": None,
        "delivered_at": None,
        "events": [TrackingEvent(NOW, EVENT_TEXT, "Musterstadt")],
    }
    fields.update(result)
    return Parcel(
        number=NUMBER,
        carrier=carrier,
        carrier_mode="manual",
        name=name,
        added_at=NOW,
        last_change_at=NOW,
        result=TrackingResult(status, **fields),
        delivery_code=CODE,
        delivery_code_day=NOW.date(),
    )


def _message(parcel, old=ParcelStatus.IN_TRANSIT, now=NOW) -> str:
    title, message = build_notification(parcel, old, now)
    assert title == TITLE == "Paket Tracker"
    return message


def test_the_four_events():
    assert NOTIFY_EVENTS == ("out_for_delivery", "delivered", "awaiting_pickup", "exception")


def test_out_for_delivery():
    parcel = _parcel(ParcelStatus.OUT_FOR_DELIVERY)
    assert _message(parcel) == "📦 Kopfhörer (DHL) ist in Zustellung"


def test_out_for_delivery_with_a_window_for_today():
    parcel = _parcel(
        ParcelStatus.OUT_FOR_DELIVERY,
        eta_date=date(2026, 9, 29),
        eta_from=datetime(2026, 9, 29, 14, 0, tzinfo=BERLIN),
        eta_to=datetime(2026, 9, 29, 16, 0, tzinfo=BERLIN),
    )
    assert _message(parcel) == "📦 Kopfhörer (DHL) ist in Zustellung – heute 14:00–16:00 Uhr"


def test_window_is_told_in_local_time():
    utc = ZoneInfo("UTC")
    parcel = _parcel(
        ParcelStatus.OUT_FOR_DELIVERY,
        eta_from=datetime(2026, 9, 29, 12, 0, tzinfo=utc),
        eta_to=datetime(2026, 9, 29, 14, 30, tzinfo=utc),
    )
    assert _message(parcel).endswith(" – heute 14:00–16:30 Uhr")


@pytest.mark.parametrize(
    "window",
    [
        # tomorrow
        (datetime(2026, 9, 30, 14, 0, tzinfo=BERLIN), datetime(2026, 9, 30, 16, 0, tzinfo=BERLIN)),
        # yesterday
        (datetime(2026, 9, 28, 14, 0, tzinfo=BERLIN), datetime(2026, 9, 28, 16, 0, tzinfo=BERLIN)),
        # incomplete
        (datetime(2026, 9, 29, 14, 0, tzinfo=BERLIN), None),
        (None, datetime(2026, 9, 29, 16, 0, tzinfo=BERLIN)),
    ],
    ids=["tomorrow", "yesterday", "no-end", "no-start"],
)
def test_no_window_unless_it_is_a_whole_one_for_today(window):
    parcel = _parcel(ParcelStatus.OUT_FOR_DELIVERY, eta_from=window[0], eta_to=window[1])
    assert _message(parcel) == "📦 Kopfhörer (DHL) ist in Zustellung"


def test_delivered():
    parcel = _parcel(ParcelStatus.DELIVERED, delivered_at=NOW)
    assert _message(parcel, ParcelStatus.OUT_FOR_DELIVERY) == "✅ Kopfhörer (DHL) wurde zugestellt"


def test_awaiting_pickup():
    parcel = _parcel(ParcelStatus.AWAITING_PICKUP)
    assert _message(parcel) == "📍 Kopfhörer (DHL) liegt zur Abholung bereit"


def test_awaiting_pickup_with_place_and_last_day():
    parcel = _parcel(
        ParcelStatus.AWAITING_PICKUP, pickup_point="Bonn", pickup_until=date(2026, 10, 6)
    )
    assert _message(parcel) == "📍 Kopfhörer (DHL) liegt zur Abholung bereit – Bonn bis 06.10."


def test_awaiting_pickup_with_last_day_only():
    parcel = _parcel(ParcelStatus.AWAITING_PICKUP, pickup_until=date(2026, 10, 6))
    assert _message(parcel) == "📍 Kopfhörer (DHL) liegt zur Abholung bereit bis 06.10."


def test_pickup_place_only_from_the_carrier():
    """A place that came with a 17track-only result is not the carrier's branch."""
    parcel = _parcel(ParcelStatus.AWAITING_PICKUP, pickup_point="Irgendwo", enriched=("status",))
    assert _message(parcel) == "📍 Kopfhörer (DHL) liegt zur Abholung bereit"
    shop = _parcel(ParcelStatus.AWAITING_PICKUP, carrier="amazon", pickup_point="Irgendwo")
    assert _message(shop) == "📍 Kopfhörer (Amazon) liegt zur Abholung bereit"


def test_exception():
    parcel = _parcel(ParcelStatus.EXCEPTION)
    assert _message(parcel) == "⚠️ Kopfhörer (DHL): Problem bei der Zustellung"


def test_without_a_name_the_last_four_digits_stand_in():
    parcel = _parcel(ParcelStatus.DELIVERED, name=None)
    assert _message(parcel) == "✅ Paket …2557 (DHL) wurde zugestellt"
    parcel.name = "   "
    assert _message(parcel) == "✅ Paket …2557 (DHL) wurde zugestellt"


def test_mail_title_stands_in_for_a_missing_name():
    parcel = _parcel(ParcelStatus.DELIVERED, name=None, carrier="amazon")
    parcel.mail_title = "USB-C Kabel 2 m"
    assert _message(parcel) == "✅ USB-C Kabel 2 m (Amazon) wurde zugestellt"
    parcel.name = "Kabel"
    assert _message(parcel) == "✅ Kabel (Amazon) wurde zugestellt"


def test_name_is_cut_to_40_characters_on_one_line():
    parcel = _parcel(ParcelStatus.DELIVERED, name="Sehr langer Artikel\nmit Umbruch " + "x" * 60)
    message = _message(parcel)
    name = message.removeprefix("✅ ").removesuffix(" (DHL) wurde zugestellt")
    assert len(name) == 40 and name.endswith("…")
    assert name.startswith("Sehr langer Artikel mit Umbruch xxx")
    assert "\n" not in message


def test_carrier_name_as_on_the_sensor():
    other = _parcel(ParcelStatus.DELIVERED, carrier="other")
    other.track17_carrier = 101070
    assert carrier_name(other) == "GLS"
    assert _message(other) == "✅ Kopfhörer (GLS) wurde zugestellt"
    other.track17_carrier = 4711
    assert _message(other) == "✅ Kopfhörer (17track) wurde zugestellt"
    unknown = _parcel(ParcelStatus.DELIVERED, carrier=None)
    assert _message(unknown) == "✅ Kopfhörer wurde zugestellt"


@pytest.mark.parametrize(
    "status",
    [
        ParcelStatus.PRE_TRANSIT,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.AT_DELIVERY_DEPOT,
        ParcelStatus.UNKNOWN,
    ],
)
def test_other_statuses_are_no_notification(status):
    assert build_notification(_parcel(status), ParcelStatus.PRE_TRANSIT, NOW) is None


def test_no_notification_without_a_change_or_a_result():
    parcel = _parcel(ParcelStatus.DELIVERED)
    assert build_notification(parcel, ParcelStatus.DELIVERED, NOW) is None
    parcel.result = None
    assert build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW) is None


@pytest.mark.parametrize("status", [ParcelStatus(value) for value in NOTIFY_EVENTS])
@pytest.mark.parametrize("named", [True, False])
def test_never_code_number_place_or_carrier_texts(status, named):
    parcel = _parcel(
        status,
        name="Kopfhörer" if named else None,
        eta_date=NOW.date(),
        eta_from=NOW + timedelta(hours=1),
        eta_to=NOW + timedelta(hours=3),
        pickup_point="Bonn",
        pickup_until=date(2026, 10, 6),
        delivered_at=NOW,
    )
    parcel.tracking_ref = "1Z999AA10123456784"
    title, message = build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW)
    for text in (title, message):
        for private in (CODE, NUMBER, NUMBER[:-4], parcel.tracking_ref, STATUS_TEXT, "Garage",
                        "Musterweg", EVENT_TEXT, "Mustermann", LOCATION, "Carport",
                        "Musterstadt"):
            assert private not in text, private
    assert "\n" not in message


def test_module_is_free_of_home_assistant():
    assert "homeassistant" not in inspect.getsource(notification)

"""v0.3.34: carrier texts are plain text, never HTML (issue #18).

DHL sent an event text with a link to a Packstation whose ``address=`` parameter named a
place; the card showed the HTML as it came. Every text taken from a carrier's answer is
turned into plain text: tags dropped (a link's visible text stays), entities unescaped,
whitespace collapsed; nothing of a URL or an attribute is kept. Parcels stored with such
texts are cleaned once when the store is loaded, and written back at once.
"""

import copy
import json
import logging
from datetime import UTC, datetime

import pytest

from custom_components.parcel_tracker.carriers.base import plain_text
from custom_components.parcel_tracker.carriers.dhl import parse_dhl
from custom_components.parcel_tracker.carriers.gls import parse_gls
from custom_components.parcel_tracker.carriers.hermes import parse_hermes
from custom_components.parcel_tracker.carriers.track17 import parse_track17
from custom_components.parcel_tracker.carriers.ups import parse_ups
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import load_fixture

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)

# Synthetic, shaped like the text DHL sent (issue #18); the address is invented.
LINK = (
    "https://www.dhl.de/de/privatkunden/dhl-standorte-finden.html"
    "?address=Musterweg%2099%2C%2099999%20Musterstadt&amp;preferPackstation=true"
)
HTML = (
    f"Die Sendung liegt in der <a href='{LINK}' class='arrowLink' target='_blank'>"
    "<span class='arrow'></span>Packstation 909 Musterweg 99, 99999 Musterstadt</a> "
    "zur Abholung bereit."
)
PLAIN = (
    "Die Sendung liegt in der Packstation 909 Musterweg 99, 99999 Musterstadt "
    "zur Abholung bereit."
)
# What must never be left of the HTML, wherever the text ends up.
LEFTOVERS = ("http", "dhl.de", "address=", "preferPackstation", "arrowLink", "_blank",
             "class", "href", "<", ">", "%20")


def _clean(dump: str) -> None:
    for piece in LEFTOVERS:
        assert piece not in dump, piece


# --- the helper -------------------------------------------------------------------------


def test_html_of_the_issue_becomes_the_visible_text():
    assert plain_text(HTML) == PLAIN


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Zugestellt", "Zugestellt"),
        ("  Zugestellt \n am  Nachmittag ", "Zugestellt am Nachmittag"),
        ("Gr&uuml;&szlig;e &amp; mehr", "Grüße & mehr"),
        ("Paket <b>zugestellt</b>", "Paket zugestellt"),
        ("Zeile eins<br>Zeile zwei", "Zeile eins Zeile zwei"),
        ("Zeile eins<br/>Zeile zwei", "Zeile eins Zeile zwei"),
        ("<p>Absatz</p><p>Noch einer</p>", "Absatz Noch einer"),
        ('Ort <a href="https://example.org/?q=9">Musterstadt</a>', "Ort Musterstadt"),
        # A tag that is never closed takes the rest along (its URL is never shown).
        ("Abholung in der <a href='https://example.org/?address=99999", "Abholung in der"),
        # Escaped HTML is HTML as well.
        ("Hier &lt;a href=&quot;https://example.org&quot;&gt;Filiale&lt;/a&gt;", "Hier Filiale"),
        # A ">" inside a quoted attribute does not end the tag.
        ("Vor <a title='a > b' href='https://example.org'>Ort</a> nach", "Vor Ort nach"),
        ("<!-- Kommentar -->Text", "Text"),
        # A "<" that starts no tag is text.
        ("Gewicht < 5 kg", "Gewicht < 5 kg"),
        ("", ""),
        ("<span></span>", ""),
    ],
)
def test_plain_text(raw, expected):
    assert plain_text(raw) == expected


def test_plain_text_is_stable():
    for raw in (HTML, PLAIN, "Gewicht < 5 kg", "A & B"):
        once = plain_text(raw)
        assert plain_text(once) == once


# --- DHL --------------------------------------------------------------------------------


def _dhl_pickup() -> dict:
    data = copy.deepcopy(load_fixture("dhl_synthetic_out_for_delivery.json"))
    shipment = data["shipments"][0]
    shipment["status"]["description"] = HTML
    shipment["status"]["status"] = HTML
    shipment["status"]["location"]["address"]["addressLocality"] = (
        "<a href='https://www.dhl.de/?address=99999'>Musterstadt</a>"
    )
    shipment["events"][0]["description"] = HTML
    shipment["events"][0]["status"] = HTML
    shipment["events"][1]["description"] = ""
    shipment["events"][1]["status"] = "Die Sendung ist in der <b>Zustellbasis</b> eingetroffen."
    return data


def test_dhl_texts_are_plain_text():
    r = parse_dhl(_dhl_pickup())
    assert r.status_text == PLAIN
    assert r.status is ParcelStatus.AWAITING_PICKUP  # the plain text still tells it
    assert r.location == "Musterstadt"
    assert r.pickup_point == "Musterstadt"
    assert r.events[0].text == PLAIN
    assert r.events[0].location == "Bonn"
    assert r.events[1].text == "Die Sendung ist in der Zustellbasis eingetroffen."
    _clean(json.dumps(r.to_dict()))


def test_dhl_status_falls_back_to_the_status_field_when_the_description_is_only_tags():
    data = _dhl_pickup()
    data["shipments"][0]["status"]["description"] = "<span class='arrow'></span>"
    assert parse_dhl(data).status_text == PLAIN


def test_dhl_country_suffix_is_still_cut_after_the_tags_are_gone():
    data = _dhl_pickup()
    data["shipments"][0]["status"]["location"]["address"]["addressLocality"] = (
        "Musterstadt, <b>Deutschland</b>"
    )
    assert parse_dhl(data).location == "Musterstadt"


def test_dhl_plain_answers_are_unchanged():
    r = parse_dhl(load_fixture("dhl_synthetic_out_for_delivery.json"))
    assert r.status_text == "Die Sendung wurde in das Zustellfahrzeug geladen."
    assert r.location == "Bonn"


# --- other carriers that answer with an API ---------------------------------------------


def test_17track_texts_are_plain_text():
    item = copy.deepcopy(
        load_fixture("track17_synthetic_trackinfo.json")["response"]["data"]["accepted"][0]
    )
    info = item["track_info"]
    info["latest_event"]["description"] = HTML
    info["latest_event"]["location"] = "<i>Musterstadt</i>"
    for provider in info["tracking"]["providers"]:
        for event in provider["events"]:
            event["description"] = HTML
            event["location"] = "<i>Musterstadt</i>"
    r = parse_track17(item).result
    assert r.status_text == PLAIN
    assert r.location == "Musterstadt"
    assert {e.text for e in r.events} == {PLAIN}
    _clean(json.dumps(r.to_dict()))


def test_17track_event_that_is_only_tags_is_left_out():
    item = copy.deepcopy(
        load_fixture("track17_synthetic_trackinfo.json")["response"]["data"]["accepted"][0]
    )
    events = item["track_info"]["tracking"]["providers"][0]["events"]
    count = len(parse_track17(copy.deepcopy(item)).result.events)
    events[0]["description"] = "<span class='arrow'></span>"
    assert len(parse_track17(item).result.events) == count - 1


def test_ups_texts_are_plain_text():
    data = copy.deepcopy(load_fixture("ups_synthetic_in_transit.json")["response"])
    package = data["trackResponse"]["shipment"][0]["package"][0]
    package["currentStatus"]["description"] = HTML
    package["activity"][0]["status"]["description"] = HTML
    package["activity"][0]["location"]["address"]["city"] = "<b>K&ouml;ln</b>"
    r = parse_ups(data)
    assert r.status_text == PLAIN
    assert r.events[0].text == PLAIN
    assert r.events[0].location == "Köln"
    _clean(json.dumps(r.to_dict()))


def test_hermes_texts_are_plain_text():
    data = copy.deepcopy(load_fixture("hermes_out_for_delivery.json")["response"])
    for event in data[0]["parcelProgress"]:
        if event.get("historyText"):
            event["historyText"] = HTML
    r = parse_hermes(data)
    assert PLAIN in {e.text for e in r.events}
    _clean(json.dumps(r.to_dict()))


def test_gls_texts_are_plain_text():
    data = copy.deepcopy(load_fixture("gls_synthetic_detail.json")["response"])
    for event in data["history"]:
        event["evtDscr"] = HTML
    r = parse_gls(data, NOW)
    assert {e.text for e in r.events} == {PLAIN}
    _clean(json.dumps(r.to_dict()))


# --- parcels stored with such texts -----------------------------------------------------


def _dirty_result() -> TrackingResult:
    return TrackingResult(
        status=ParcelStatus.AWAITING_PICKUP,
        status_text=HTML,
        eta_date=None,
        eta_from=None,
        eta_to=None,
        location="<b>Musterstadt</b>",
        pickup_point="<b>Musterstadt</b>",
        pickup_until=None,
        delivered_at=None,
        events=[
            TrackingEvent(NOW, HTML, "<i>Bonn</i>"),
            TrackingEvent(NOW, "Die Sendung wurde abgeholt.", "Bonn"),
        ],
    )


def _stored(hass_storage, *parcels: Parcel) -> None:
    hass_storage["parcel_tracker"] = {
        "version": 1,
        "minor_version": 1,
        "key": "parcel_tracker",
        "data": {"parcels": [p.to_dict() for p in parcels]},
    }


async def test_stored_texts_are_cleaned_on_load_and_written_back(hass, hass_storage, caplog):
    caplog.set_level(logging.DEBUG)
    dirty = Parcel("00340999999999999901", "dhl", "auto", "Schuhe", NOW, NOW)
    dirty.result = _dirty_result()
    dirty.track17 = True
    dirty.track17_result = _dirty_result()
    plain = Parcel("00340999999999999902", "dhl", "auto", "Buch", NOW, NOW)
    plain.result = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Unterwegs", None, None, None, "Bonn", None, None, None,
        [TrackingEvent(NOW, "Unterwegs", "Bonn")],
    )
    _stored(hass_storage, dirty, plain)

    store = ParcelStore(hass)
    await store.async_load()

    for result in (store.get(dirty.number).result, store.get(dirty.number).track17_result):
        assert result.status_text == PLAIN
        assert (result.location, result.pickup_point) == ("Musterstadt", "Musterstadt")
        assert [(e.text, e.location) for e in result.events] == [
            (PLAIN, "Bonn"),
            ("Die Sendung wurde abgeholt.", "Bonn"),
        ]
        assert result.events[0].timestamp == NOW
    assert store.get(plain.number).result.to_dict() == plain.result.to_dict()
    # Everything else of the parcel is as it was.
    assert store.get(dirty.number).name == "Schuhe"
    assert store.get(dirty.number).track17 is True

    # Written back at once, so the file no longer holds the link either.
    stored = json.dumps(hass_storage["parcel_tracker"]["data"])
    _clean(stored)
    assert PLAIN in stored
    # Nothing of the removed text in the integration's log (the test harness itself logs
    # what it hands over as the stored file).
    ours = " ".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components.")
    )
    assert "1 parcel" in ours
    for piece in ("Musterweg", "Musterstadt", "address=", "preferPackstation", "dhl.de"):
        assert piece not in ours, piece


async def test_store_without_markup_is_not_written_on_load(hass, hass_storage):
    plain = Parcel("00340999999999999902", "dhl", "auto", "Buch", NOW, NOW)
    plain.result = TrackingResult(
        ParcelStatus.IN_TRANSIT, "Gr&uuml;n & blau", None, None, None, "Bonn", None, None,
        None, [TrackingEvent(NOW, "Unterwegs", None)],
    )
    _stored(hass_storage, plain)
    before = copy.deepcopy(hass_storage["parcel_tracker"])

    store = ParcelStore(hass)
    await store.async_load()

    assert hass_storage["parcel_tracker"] == before
    # Only HTML is cleaned in stored data; an "&" of a plain text stays as it was.
    assert store.get(plain.number).result.status_text == "Gr&uuml;n & blau"


def _raw_parcel(number: str, events: list[dict], status_text=None) -> dict:
    parcel = Parcel(number, "dhl", "auto", None, NOW, NOW).to_dict()
    parcel["result"] = TrackingResult(
        ParcelStatus.DELIVERED, status_text, None, None, None, None, None, None, NOW
    ).to_dict()
    parcel["result"]["events"] = events
    return parcel


async def test_cleaning_never_changes_the_length_of_the_history(hass, hass_storage):
    """The history decides whether an old parcel's delivery was told (``_delivery_told``
    counts its lines): cleaning it must never drop a line."""
    stamp = NOW.isoformat()
    events = [
        {"timestamp": stamp, "text": HTML, "location": None},
        {"timestamp": stamp, "text": "<span class='arrow'></span>", "location": "<i>Bonn</i>"},
        {"timestamp": stamp, "text": None, "location": None},
        {"timestamp": stamp, "text": "Zugestellt", "location": "Bonn"},
    ]
    hass_storage["parcel_tracker"] = {
        "version": 1, "minor_version": 1, "key": "parcel_tracker",
        "data": {"parcels": [_raw_parcel("00340999999999999903", copy.deepcopy(events))]},
    }

    store = ParcelStore(hass)
    await store.async_load()

    loaded = store.get("00340999999999999903").result.events
    assert len(loaded) == len(events)
    assert [(e.text, e.location) for e in loaded] == [
        (PLAIN, None),
        ("", "Bonn"),  # nothing but tags: kept as a line, without its markup
        (None, None),  # a missing text stays as stored
        ("Zugestellt", "Bonn"),
    ]
    stored = hass_storage["parcel_tracker"]["data"]["parcels"][0]["result"]["events"]
    assert len(stored) == len(events)
    _clean(json.dumps(stored))


async def test_events_without_text_or_markup_are_no_reason_to_rewrite(hass, hass_storage):
    stamp = NOW.isoformat()
    events = [
        {"timestamp": stamp, "text": None, "location": None},
        {"timestamp": stamp, "text": "", "location": None},
        {"timestamp": stamp, "text": "Zugestellt", "location": None},
    ]
    hass_storage["parcel_tracker"] = {
        "version": 1, "minor_version": 1, "key": "parcel_tracker",
        "data": {"parcels": [_raw_parcel("00340999999999999904", events)]},
    }
    before = copy.deepcopy(hass_storage["parcel_tracker"])

    store = ParcelStore(hass)
    await store.async_load()

    assert hass_storage["parcel_tracker"] == before
    loaded = store.get("00340999999999999904").result.events
    assert [e.text for e in loaded] == [None, "", "Zugestellt"]

"""Diagnostics download: useful for bug reports, free of secrets and personal data."""

import json
from datetime import date, datetime, timedelta

import pytest
from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.parcel_tracker.carriers.track17 import Quota
from custom_components.parcel_tracker.const import (
    CONF_COUNTRY,
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_INTERVAL,
    CONF_NOTIFY_EVENTS,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    CONF_READ_OTP,
    CONF_TRACK17_API_KEY,
    CONF_UPS_BUDGET,
    CONF_UPS_CLIENT_ID,
    CONF_UPS_CLIENT_SECRET,
    DOMAIN,
    VERSION,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.diagnostics import (
    async_get_config_entry_diagnostics,
    mask_number,
    public_imap_host,
)
from custom_components.parcel_tracker.mail import known_sender_domain
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
)
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

# Everything below is made up.
SECRETS = {
    CONF_DHL_API_KEY: "synthetic-dhl-key-4711",
    CONF_IMAP_PASSWORD: "synthetic-imap-pass-0815",
    CONF_UPS_CLIENT_ID: "synthetic-ups-client-id",
    CONF_UPS_CLIENT_SECRET: "synthetic-ups-client-secret",
    CONF_TRACK17_API_KEY: "synthetic-17track-key",
}
POSTCODE = "48712"
IMAP_USER = "pakete.tester@mailbox.example"
IMAP_HOST = "imap.mailbox.org"
OPTIONS = {
    CONF_POSTCODE: POSTCODE,
    CONF_KEEP_DELIVERED_DAYS: 3,
    CONF_IMAP_HOST: IMAP_HOST,
    CONF_IMAP_USER: IMAP_USER,
    CONF_READ_OTP: True,
    CONF_MAIL_INTERVAL: 7,
    CONF_UPS_BUDGET: 250,
}

JJD = "JJD014600003812345678"
DHL = "00340999999999999917"
DPD = "09999999999902"
GLS = "12345678901"
HERMES = "H1002003004005006007"
UPS = "1Z12AB345678901234"
AMAZON = "AMZ30212345671234567"
AMAZON_REF = "JJD000390007712345678"
EBAY = "EBAY1234567890"
OTHER = "LX123456789CN"
NUMBERS = (JJD, DHL, DPD, GLS, HERMES, UPS, AMAZON, AMAZON_REF, EBAY, OTHER)

MASKED = {
    "CQ999999901DE": "AA999999999AA",
    JJD: "JJD" + "9" * 18,
    DHL: "9" * 20,
    DPD: "9" * 14,
    GLS: "9" * 11,
    HERMES: "H" + "9" * 19,
    UPS: "1Z99AA999999999999",
    AMAZON: "AMZ" + "9" * 17,
    AMAZON_REF: "JJD" + "9" * 18,
    EBAY: "EBAY" + "9" * 10,
    OTHER: "AA999999999AA",
}

NAME = "Geburtstagsgeschenk Tante Erna"
TITLE = "Klemmbaustein Sternenkreuzer"
OTP = "246813"
LOCATION = "Musterhausen"
PICKUP = "Packstation 123 Beispielweg"
EVENT_TEXT = "Zugestellt an Nachbar Mustermann"
EVENT_PLACE = "Beispielstadt"
STATUS_TEXT = "Die Sendung wurde im Zielpaketzentrum bearbeitet"
PLAIN = (NAME, TITLE, OTP, LOCATION, PICKUP, EVENT_TEXT, EVENT_PLACE, STATUS_TEXT)

TOP_LEVEL = [
    "integration_version",
    "home_assistant_version",
    "country",
    "entry",
    "carriers",
    "ups_budget",
    "track17",
    "mail_import",
    "notifications",
    "pending_announcements",
    "parcels",
]


@pytest.mark.parametrize(("number", "masked"), list(MASKED.items()))
def test_mask_number_keeps_format_and_known_prefix(number, masked):
    assert mask_number(number) == masked
    assert len(mask_number(number)) == len(number)


@pytest.mark.parametrize(
    ("number", "masked"),
    [
        ("", ""),
        ("HALLO123", "AAAAA999"),  # an H only stays in front of digits (Hermes)
        ("JJDX12", "AAAA99"),
        ("amz123", "AMZ999"),
        ("12-34 ab", "99-99 AA"),
        ("Straße7", "AAAAAA9"),
        ("12 34☃", "99?99?"),
    ],
)
def test_mask_number_odd_input(number, masked):
    assert mask_number(number) == masked


def test_mask_number_none():
    assert mask_number(None) is None


@pytest.mark.parametrize(
    ("address", "domain"),
    [
        ("order-update@amazon.de", "amazon.de"),
        ("noreply@dhl.de", "dhl.de"),
        ("pkginfo@ups.com", "ups.com"),
        ("ebay@ebay.com", "ebay.com"),
        ("no-reply@gls-pakete.de", "gls-pakete.de"),
        ("noreply@paketankuendigung.myhermes.de", "paketankuendigung.myhermes.de"),
        ("noreply@service.dpd.de", "service.dpd.de"),
        ("paketankuendigung@dhl.de", "dhl.de"),
        ("noreply@gls-group.eu", "gls-group.eu"),
        ("noreply@gls-rtt.com", "gls-rtt.com"),
        ("no_reply@dpd.at", "dpd.at"),
        ("news@marketing.amazon.de", "amazon.de"),  # a sub-domain counts as its known parent
        ("erika.mustermann@privat.example", "other"),
        ("someone@notamazon.de", "other"),
        ("someone@amazon.de.evil.example", "other"),
        ("", "other"),
        ("no-at-sign", "other"),
    ],
)
def test_known_sender_domain(address, domain):
    assert known_sender_domain(address) == domain


def _result(status=ParcelStatus.IN_TRANSIT, **kwargs):
    values = {
        "status": status,
        "status_text": STATUS_TEXT,
        "eta_date": None,
        "eta_from": None,
        "eta_to": None,
        "location": None,
        "pickup_point": None,
        "pickup_until": None,
        "delivered_at": None,
        "events": [],
    }
    return TrackingResult(**{**values, **kwargs})


def _parcels(now: datetime) -> list[Parcel]:
    later = now + timedelta(hours=2)  # nothing is due: setup must not ask any carrier
    events = [
        TrackingEvent(now - timedelta(hours=3), EVENT_TEXT, EVENT_PLACE),
        TrackingEvent(now - timedelta(hours=5), EVENT_TEXT, None),
    ]
    window = _result(
        ParcelStatus.OUT_FOR_DELIVERY,
        eta_date=now.date(),
        eta_from=now + timedelta(hours=1),
        eta_to=now + timedelta(hours=3),
        location=LOCATION,
        events=events,
    )
    return [
        Parcel(JJD, "dhl", "auto", NAME, now, now, now, later, result=window),
        Parcel(DHL, "dhl", "manual", None, now, now, now, later, result=_result()),
        Parcel(
            DPD, "dpd", "auto", None, now, now, now, later,
            last_error="unavailable", error_streak=3, first_error_at=now,
        ),
        Parcel(
            GLS, "gls", "manual", None, now, now, now, later,
            result=_result(ParcelStatus.AWAITING_PICKUP, pickup_point=PICKUP),
        ),
        Parcel(
            HERMES, "hermes", "mail", None, now, now, now, later, mail_title=TITLE,
            result=_result(ParcelStatus.IN_TRANSIT, eta_date=now.date(), enriched=("eta",)),
            track17=True, track17_carrier=100031, track17_next_at=later,
            track17_result=_result(location=LOCATION, events=events),
        ),
        Parcel(UPS, "ups", "auto", None, now, now, now, later, last_error="rate_limited"),
        Parcel(
            AMAZON, "amazon", "mail", None, now, now, mail_title=TITLE,
            next_poll_at=later, result=_result(ParcelStatus.OUT_FOR_DELIVERY),
            tracking_ref=AMAZON_REF, tracking_carrier="dhl",
        ),
        Parcel(
            EBAY, "ebay", "mail", None, now, now, mail_title=TITLE,
            result=_result(ParcelStatus.PRE_TRANSIT), shipping_carrier_hint="hermes",
        ),
        Parcel(
            OTHER, "other", "manual", NAME, now, now,
            result=_result(ParcelStatus.DELIVERED, delivered_at=now, enriched=("status",)),
            track17=True, track17_carrier=3011,
        ),
    ]


async def _setup(hass, hass_storage, freezer=None):
    if freezer is not None:
        freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {
            "parcels": [p.to_dict() for p in _parcels(now)],
            "message_ids": ["<a@synthetic.example>", "<b@synthetic.example>"],
            "ups_budget": {"month": "2026-09", "count": 42},
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "", **SECRETS}, options=OPTIONS)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # The one-time code only ever lives in memory.
    coordinator.store.parcels[AMAZON].delivery_code = OTP
    coordinator.store.parcels[AMAZON].delivery_code_day = date(2026, 9, 29)
    coordinator.track17_quota = Quota(total=200, used=57, remain=143)
    return entry


def _dump(result) -> str:
    """Serialised like the download, plus a variant with unescaped umlauts."""
    return json.dumps(result) + json.dumps(result, ensure_ascii=False)


async def test_diagnostics_top_level(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert list(result) == TOP_LEVEL
    assert result["integration_version"] == VERSION
    assert result["home_assistant_version"] == HA_VERSION
    json.dumps(result)  # serialisable as it is


async def test_diagnostics_contain_no_secret_and_no_personal_value(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    text = _dump(await async_get_config_entry_diagnostics(hass, entry))
    for secret in (*SECRETS.values(), IMAP_USER, "pakete.tester", POSTCODE):
        assert secret not in text
    for plain in PLAIN:
        assert plain not in text
    for number in NUMBERS:
        assert number not in text
        assert number[-8:] not in text
    assert "@" not in text
    assert "synthetic.example" not in text  # stored Message-IDs


async def test_diagnostics_entry_is_redacted_but_still_tells_the_settings(
    hass, hass_storage, freezer
):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    data, options = result["entry"]["data"], result["entry"]["options"]
    for key in SECRETS:
        assert data[key] == REDACTED
    assert data[CONF_POSTCODE] == ""  # empty values stay visible as "not set"
    assert options[CONF_POSTCODE] == REDACTED
    assert options[CONF_IMAP_USER] == REDACTED
    assert options[CONF_IMAP_HOST] == IMAP_HOST
    assert options[CONF_KEEP_DELIVERED_DAYS] == 3
    assert options[CONF_READ_OTP] is True
    assert options[CONF_MAIL_INTERVAL] == 7
    assert options[CONF_UPS_BUDGET] == 250


@pytest.mark.parametrize(
    ("host", "shown"),
    [
        ("imap.mailbox.org", "imap.mailbox.org"),
        ("IMAP.GMX.NET ", "imap.gmx.net"),
        ("imap.gmx.de", "imap.gmx.de"),
        ("imap.web.de", "imap.web.de"),
        ("imap.gmail.com", "imap.gmail.com"),
        ("imap.googlemail.com", "imap.googlemail.com"),
        ("outlook.office365.com", "outlook.office365.com"),
        ("imap-mail.outlook.com", "imap-mail.outlook.com"),
        ("imap.hotmail.com", "imap.hotmail.com"),
        ("imap.mail.me.com", "imap.mail.me.com"),
        ("imap.icloud.com", "imap.icloud.com"),
        ("imap.mail.yahoo.com", "imap.mail.yahoo.com"),
        ("secureimap.t-online.de", "secureimap.t-online.de"),
        ("posteo.de", "posteo.de"),
        ("imap.ionos.de", "imap.ionos.de"),
        ("imap.1und1.de", "imap.1und1.de"),
        ("imap.strato.de", "imap.strato.de"),
        ("mx.freenet.de", "mx.freenet.de"),
        ("imap.aol.com", "imap.aol.com"),
        ("127.0.0.1", "127.0.0.1"),  # Proton Mail Bridge
        ("localhost", "localhost"),
        ("mail.familie-mustermann.example", "custom"),
        ("imap.mailbox.example", "custom"),
        ("mailbox.org.evil.example", "custom"),
        ("notgmx.net", "custom"),
        ("192.168.178.20", "custom"),
        ("nas.fritz.box", "custom"),
        ("imap.gmx.net:993/geheim", "custom"),
        ("", ""),
        (None, None),
        (4711, "custom"),
    ],
)
def test_public_imap_host(host, shown):
    assert public_imap_host(host) == shown


async def test_diagnostics_show_a_private_imap_host_only_as_custom(hass, hass_storage, freezer):
    """An own mail server (often a domain with the family name) is never named."""
    entry = await _setup(hass, hass_storage, freezer)
    host = "mail.familie-mustermann.example"
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_IMAP_HOST: host}, options={**OPTIONS, CONF_IMAP_HOST: host}
    )
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["entry"]["options"][CONF_IMAP_HOST] == "custom"
    assert result["entry"]["data"][CONF_IMAP_HOST] == "custom"
    text = _dump(result)
    assert "mustermann" not in text and "familie" not in text


async def test_diagnostics_redact_unknown_entry_keys(hass, hass_storage, freezer):
    """A key added later is hidden until someone decides it is harmless."""
    entry = await _setup(hass, hass_storage, freezer)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, "future_token": "synthetic-future-token"},
        options={**entry.options, "future_section": {"street": "Beispielweg 5"}},
    )
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["entry"]["data"]["future_token"] == REDACTED
    assert result["entry"]["options"]["future_section"] == REDACTED
    assert "Beispielweg" not in _dump(result)


async def test_diagnostics_parcels(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    now = dt_util.utcnow()
    later = (now + timedelta(hours=2)).isoformat()
    parcels = result["parcels"]
    assert [p["number"] for p in parcels] == [
        MASKED[n] for n in (JJD, DHL, DPD, GLS, HERMES, UPS, AMAZON, EBAY, OTHER)
    ]
    by_number = {p["number"]: p for p in parcels}

    jjd = by_number[MASKED[JJD]]
    assert jjd == {
        "number": MASKED[JJD],
        "carrier": "dhl",
        "carrier_mode": "auto",
        "tracking_carrier": None,
        "has_tracking_ref": False,
        "tracking_ref": None,
        "shipping_carrier_hint": None,
        "status": "out_for_delivery",
        "assumed_delivered": False,
        "order_checked": False,
        "gls_probes": 0,
        "last_error": None,
        "error_streak": 0,
        "first_error_at": None,
        "added_at": now.isoformat(),
        "last_change_at": now.isoformat(),
        "last_poll_at": now.isoformat(),
        "next_poll_at": later,
        "has_name": True,
        "has_mail_title": False,
        "has_eta": True,
        "has_window": True,
        "has_location": True,
        "has_pickup_point": False,
        "has_delivery_code": False,
        "event_count": 2,
        "enriched": [],
        "track17": False,
        "track17_carrier": None,
        "track17_next_at": None,
        "has_track17_result": False,
    }

    dpd = by_number[MASKED[DPD]]
    assert (dpd["status"], dpd["last_error"], dpd["error_streak"]) == (None, "unavailable", 3)
    assert dpd["first_error_at"] == now.isoformat()
    assert (dpd["has_eta"], dpd["has_window"], dpd["event_count"]) == (False, False, 0)

    gls = by_number[MASKED[GLS]]
    assert (gls["status"], gls["has_pickup_point"]) == ("awaiting_pickup", True)
    assert gls["has_location"] is False

    hermes = by_number[MASKED[HERMES]]
    assert hermes["carrier_mode"] == "mail"
    assert (hermes["has_name"], hermes["has_mail_title"]) == (False, True)
    assert (hermes["has_eta"], hermes["has_window"]) == (True, False)
    assert hermes["enriched"] == ["eta"]
    assert (hermes["track17"], hermes["track17_carrier"]) == (True, 100031)
    assert hermes["track17_next_at"] == later
    assert hermes["has_track17_result"] is True

    assert by_number[MASKED[UPS]]["last_error"] == "rate_limited"

    amazon = by_number[MASKED[AMAZON]]
    assert amazon["carrier"] == "amazon"
    assert (amazon["has_tracking_ref"], amazon["tracking_ref"]) == (True, MASKED[AMAZON_REF])
    assert amazon["tracking_carrier"] == "dhl"
    assert amazon["has_delivery_code"] is True

    ebay = by_number[MASKED[EBAY]]
    assert (ebay["status"], ebay["shipping_carrier_hint"]) == ("pre_transit", "hermes")

    other = by_number[MASKED[OTHER]]
    assert (other["carrier"], other["status"], other["enriched"]) == (
        "other", "delivered", ["status"],
    )


async def test_diagnostics_free_text_in_code_fields_is_not_passed_on(hass, hass_storage, freezer):
    """Carrier keys and error codes are short identifiers; anything else is hidden."""
    entry = await _setup(hass, hass_storage, freezer)
    parcel = entry.runtime_data.store.parcels[DPD]
    parcel.last_error = "Timeout bei Beispielstadt"
    parcel.shipping_carrier_hint = "Bote Mustermann"
    result = await async_get_config_entry_diagnostics(hass, entry)
    shown = next(p for p in result["parcels"] if p["number"] == MASKED[DPD])
    assert (shown["last_error"], shown["shipping_carrier_hint"]) == ("other", "other")


async def test_diagnostics_carriers_budget_and_17track(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["carriers"] == {
        "active": ["dhl", "dpd", "hermes", "gls", "ups"],
        "credentials": {"dhl": True, "ups": True, "track17": True, "mail": True},
        "dhl_calls_today": 0,
    }
    assert result["ups_budget"] == {"month": "2026-09", "count": 42, "limit": 250, "active": True}
    track17 = result["track17"]
    assert track17["configured"] is True
    assert track17["blocked"] is False
    assert track17["quota"] == {"total": 200, "used": 57, "remain": 143}

    entry.runtime_data.track17_blocked = True
    entry.runtime_data.track17_quota = None
    track17 = (await async_get_config_entry_diagnostics(hass, entry))["track17"]
    assert (track17["blocked"], track17["quota"]) == (True, None)


async def test_diagnostics_without_any_credentials(hass, hass_storage, freezer):
    freezer.move_to(DAYTIME)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert list(result) == TOP_LEVEL
    assert result["carriers"]["credentials"] == {
        "dhl": False, "ups": False, "track17": False, "mail": False,
    }
    assert "ups" not in result["carriers"]["active"]
    assert result["ups_budget"] == {"month": None, "count": 0, "limit": 100, "active": False}
    assert result["track17"] == {
        "configured": False, "blocked": False, "quota": None,
        "quota_next_check": None, "error_streak": 0,
    }
    assert result["mail_import"] == {
        "configured": False,
        "interval_minutes": 5,
        "last_run": None,
        "next_run": None,
        "last_error": None,
        "error_streak": 0,
        "recognized": 0,
        "unrecognized": 0,
        "amazon_misses": 0,
        "known_message_ids": 0,
        "last_unrecognized": [],
    }
    assert result["parcels"] == []


# ----- mail import state -----

MAIL_SUBJECT = "Geheime Betreffzeile"
MAIL_BODY = "Vertraulicher Mailtext ohne Sendungsnummer"


def _mail(i: int, sender: str, subject: str = MAIL_SUBJECT) -> tuple[str, bytes]:
    return str(i), (
        f"From: Absender Mustermann <{sender}>\r\n"
        f"Message-ID: <diag{i}@synthetic.example>\r\n"
        f"Subject: {subject}\r\n"
        "Date: Tue, 29 Sep 2026 08:00:00 +0000\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{MAIL_BODY}\r\n"
    ).encode()


def _recognised_mail(i: int) -> tuple[str, bytes]:
    return str(i), (
        "From: Shop <versand@shop.example>\r\n"
        f"Message-ID: <diag{i}@synthetic.example>\r\n"
        "Subject: Versandbestaetigung\r\n"
        "Date: Tue, 29 Sep 2026 08:00:00 +0000\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"DHL-Sendungsnummer: {DHL}\r\n"
    ).encode()


class FakeMailbox:
    def __init__(self, mails=(), error: Exception | None = None):
        self.mails = list(mails)
        self.error = error

    def fetch_unseen(self):
        if self.error:
            raise self.error
        mails, self.mails = self.mails, []
        return mails

    def finish(self, dispositions, move):
        pass


async def _mail_entry(hass, mailbox):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: ""}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    coordinator = ParcelCoordinator(hass, entry, store, {}, mailbox)
    entry.runtime_data = coordinator
    await coordinator.async_refresh()  # the first refresh never touches the mailbox
    return entry


async def test_mail_import_state_before_the_first_run(hass, freezer):
    freezer.move_to(DAYTIME)
    entry = await _mail_entry(hass, FakeMailbox())
    state = (await async_get_config_entry_diagnostics(hass, entry))["mail_import"]
    assert state["configured"] is True
    assert (state["last_run"], state["next_run"]) == (None, None)
    assert (state["recognized"], state["unrecognized"]) == (0, 0)
    assert state["last_unrecognized"] == []


async def test_mail_import_counts_and_remembers_only_domain_and_forwarded(hass, freezer):
    freezer.move_to(DAYTIME)
    mailbox = FakeMailbox(
        [
            _mail(1, "erika.mustermann@privat.example"),
            _mail(2, "order-update@amazon.de"),
            _mail(3, "noreply@dhl.de", "WG: " + MAIL_SUBJECT),
            _recognised_mail(4),
            _mail(5, "kunde@privat.example", "Fwd: " + MAIL_SUBJECT),
        ]
    )
    entry = await _mail_entry(hass, mailbox)
    await entry.runtime_data.async_refresh()
    now = dt_util.utcnow()
    result = await async_get_config_entry_diagnostics(hass, entry)
    state = result["mail_import"]
    assert state["last_run"] == now.isoformat()
    assert state["next_run"] == (now + timedelta(minutes=5)).isoformat()
    assert (state["last_error"], state["error_streak"]) == (None, 0)
    assert (state["recognized"], state["unrecognized"]) == (1, 4)
    assert state["amazon_misses"] == 1
    assert state["known_message_ids"] == 5
    assert state["last_unrecognized"] == [
        {"domain": "other", "forwarded": False},
        {"domain": "amazon.de", "forwarded": False},
        {"domain": "dhl.de", "forwarded": True},
        {"domain": "other", "forwarded": True},
    ]
    text = _dump(result)
    for plain in (
        MAIL_SUBJECT, "Betreff", MAIL_BODY, "Mustermann", "privat.example", "@",
        "synthetic.example", DHL,
    ):
        assert plain not in text


def _forwarded_mail(i: int, quoted_sender: str, body: str, subject: str = "WG: Paket"):
    return str(i), (
        "From: Erika Mustermann <erika.mustermann@privat.example>\r\n"
        f"Message-ID: <diag{i}@synthetic.example>\r\n"
        f"Subject: {subject}\r\n"
        "Date: Tue, 29 Sep 2026 08:00:00 +0000\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Zur Info, Erika\r\n\r\n"
        f"Von: Absender <{quoted_sender}>\r\n"
        "Gesendet: Montag, 28. September 2026 11:51\r\n"
        "An: erika.mustermann@privat.example\r\n"
        "Betreff: Ihre Sendung kommt heute\r\n\r\n"
        f"{body}\r\n"
    ).encode()


async def test_forwarded_mail_is_booked_under_its_original_sender(hass, freezer):
    """v0.3.16: recognised when the original's parser reads it; an unrecognised one is
    remembered with the domain of the original sender (if known) and as forwarded."""
    freezer.move_to(DAYTIME)
    mailbox = FakeMailbox(
        [
            _forwarded_mail(1, "zustellung@dhl.de", "Ihre Sendungsnummer\r\n999999999901"),
            _forwarded_mail(2, "zustellung@dhl.de", MAIL_BODY),
            _forwarded_mail(3, "info@shop.example", MAIL_BODY),
            _forwarded_mail(4, "pkginfo@ups.com", MAIL_BODY, subject="Paket"),
            # the same forward again: skipped by its own Message-ID
            _forwarded_mail(1, "zustellung@dhl.de", "Ihre Sendungsnummer\r\n999999999901"),
        ]
    )
    entry = await _mail_entry(hass, mailbox)
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    state = (await async_get_config_entry_diagnostics(hass, entry))["mail_import"]
    assert (state["recognized"], state["unrecognized"]) == (1, 3)
    assert state["known_message_ids"] == 4
    assert state["last_unrecognized"] == [
        {"domain": "dhl.de", "forwarded": True},
        {"domain": "other", "forwarded": True},
        {"domain": "ups.com", "forwarded": True},
    ]
    [parcel] = coordinator.store.parcels.values()
    assert (parcel.number, parcel.carrier) == ("999999999901", "dhl")
    text = _dump(await async_get_config_entry_diagnostics(hass, entry))
    for plain in ("Mustermann", "privat.example", "shop.example", "Zur Info", "@"):
        assert plain not in text


async def test_unrecognised_mails_are_bounded_to_the_last_ten(hass, freezer):
    freezer.move_to(DAYTIME)
    mails = [_mail(i, f"absender{i}@privat.example") for i in range(12)]
    mails += [_mail(12, "pkginfo@ups.com")]
    entry = await _mail_entry(hass, FakeMailbox(mails))
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    state = (await async_get_config_entry_diagnostics(hass, entry))["mail_import"]
    assert state["unrecognized"] == 13
    assert len(state["last_unrecognized"]) == 10
    assert state["last_unrecognized"][-1] == {"domain": "ups.com", "forwarded": False}
    assert state["last_unrecognized"][:-1] == [{"domain": "other", "forwarded": False}] * 9
    # The coordinator itself keeps nothing but these two fields.
    assert coordinator.unrecognized_mails.maxlen == 10
    assert all(set(item) == {"domain", "forwarded"} for item in coordinator.unrecognized_mails)


async def test_unrecognised_mails_are_forgotten_on_reload(hass, freezer):
    freezer.move_to(DAYTIME)
    entry = await _mail_entry(hass, FakeMailbox([_mail(1, "noreply@dhl.de")]))
    await entry.runtime_data.async_refresh()
    assert len(entry.runtime_data.unrecognized_mails) == 1
    fresh = ParcelCoordinator(hass, entry, entry.runtime_data.store, {}, FakeMailbox())
    assert len(fresh.unrecognized_mails) == 0
    assert fresh.diagnostics()["mail_import"]["unrecognized"] == 0


async def test_mail_import_backoff_is_visible(hass, freezer):
    from custom_components.parcel_tracker.mail.imap import ImapUnavailable

    freezer.move_to(DAYTIME)
    entry = await _mail_entry(hass, FakeMailbox(error=ImapUnavailable("synthetic")))
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    coordinator._mail_next = None
    await coordinator.async_refresh()
    now = dt_util.utcnow()
    state = (await async_get_config_entry_diagnostics(hass, entry))["mail_import"]
    assert (state["last_error"], state["error_streak"]) == ("unavailable", 2)
    assert state["last_run"] == now.isoformat()
    assert state["next_run"] == (now + timedelta(minutes=10)).isoformat()
    assert "synthetic" not in _dump(state)


async def test_download_through_home_assistant(hass, hass_storage, hass_client):
    """Home Assistant finds the platform and serves the same, clean content."""
    # Real clock: the access token of the test client is not valid in a frozen past.
    entry = await _setup(hass, hass_storage)
    downloaded = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert downloaded == await async_get_config_entry_diagnostics(hass, entry)
    text = _dump(downloaded)
    for plain in (*SECRETS.values(), IMAP_USER, POSTCODE, *PLAIN, *NUMBERS):
        assert plain not in text


async def test_diagnostics_notifications_off_by_default(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["notifications"] == {
        "targets": 0,
        "entity_targets": 0,
        "service_targets": 0,
        "events": ["out_for_delivery", "delivered"],
    }


async def test_diagnostics_tell_only_the_number_of_notify_targets(hass, hass_storage, freezer):
    """Entity IDs carry device names ("mobile_app_iphone_von_erika"): never shown."""
    entry = await _setup(hass, hass_storage, freezer)
    targets = [
        "notify.mobile_app_iphone_von_erika",
        "notify.tablet_wohnzimmer",
        "service:pushover",
        "service:mobile_app_iphone_von_erika",
        "service:telegram_erika",
        7,
    ]
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_NOTIFY_TARGETS: targets,
            # Anything but the four known events is not passed on.
            CONF_NOTIFY_EVENTS: ["exception", "delivered", "Freitext Musterweg 5", 7],
        },
    )
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["notifications"] == {
        "targets": 5,
        "entity_targets": 2,
        "service_targets": 3,
        "events": ["delivered", "exception"],
    }
    assert result["entry"]["options"][CONF_NOTIFY_TARGETS] == REDACTED
    assert result["entry"]["options"][CONF_NOTIFY_EVENTS] == REDACTED
    text = _dump(result)
    for private in (*targets[:-1], "mobile_app", "erika", "wohnzimmer", "notify.", "Musterweg",
                    "pushover", "telegram", "service:"):
        assert private not in text, private


async def test_diagnostics_count_pending_announcements_only(hass, hass_storage, freezer):
    """Only how many parcels still wait for their status event, nothing about them."""
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["pending_announcements"] == 0
    parcels = entry.runtime_data.store.parcels
    parcels[JJD].unannounced_from = ParcelStatus.PRE_TRANSIT
    # Back at the status it had: nothing is pending for this one.
    parcels[OTHER].unannounced_from = ParcelStatus.DELIVERED
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["pending_announcements"] == 1
    assert all("unannounced_from" not in parcel for parcel in result["parcels"])
    assert "unannounced" not in _dump(result)


async def test_diagnostics_name_the_country_and_never_the_postcode(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["country"] == "de"  # an entry from before v0.3.13
    assert CONF_COUNTRY not in result["entry"]["options"]

    hass.config_entries.async_update_entry(
        entry, options={**OPTIONS, CONF_COUNTRY: "at", CONF_POSTCODE: "4871"}
    )
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["country"] == "at"
    assert result["entry"]["options"][CONF_COUNTRY] == "at"
    assert result["entry"]["options"][CONF_POSTCODE] == REDACTED
    assert "4871" not in _dump(result)


async def test_diagnostics_show_only_a_known_country(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    hass.config_entries.async_update_entry(
        entry, options={**OPTIONS, CONF_COUNTRY: "Musterstraße 1"}
    )
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["country"] == "de"
    assert "Musterstra" not in _dump(result)

import asyncio
import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.parcel_tracker.const import (
    CONF_MAIL_INTERVAL,
    CONF_MOVE_PROCESSED,
    CONF_READ_OTP,
    DOMAIN,
    EVENT_STATUS_CHANGED,
    FOLDER_PROCESSED,
    FOLDER_UNRECOGNIZED,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.imap import ImapAuthError, ImapUnavailable
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import FIXTURES

PLAETTCHEN = "AMZ99991565342587125"
JJD = "JJD000012978217606560"


def raw(name: str) -> bytes:
    return (FIXTURES / "mail" / name).read_bytes()


def unknown_amazon_mail(i: int) -> bytes:
    return (
        "From: Amazon.de <order-update@amazon.de>\r\n"
        f"Message-ID: <unknown{i}@example.org>\r\n"
        "Subject: Deine Meinung ist gefragt\r\n"
        "Date: Wed, 30 Sep 2026 08:00:00 +0000\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Bewerte deinen Kauf\r\n"
    ).encode()


@pytest.fixture(autouse=True)
def accept_old_fixture_mails():
    """The fixtures are real mails from months/years ago; age is tested separately."""
    with patch(
        "custom_components.parcel_tracker.coordinator.MAIL_MAX_AGE", timedelta(days=36500)
    ):
        yield


def dated_mail(i: int, date: str) -> bytes:
    return (
        "From: Shop <shop@example.org>\r\n"
        f"Message-ID: <dated{i}@example.org>\r\n"
        "Subject: Versandbestaetigung\r\n"
        f"Date: {date}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"DHL-Sendungsnummer: 0034099999999999991{i}\r\n"
    ).encode()


class FakeMailbox:
    def __init__(self, mails=(), error: Exception | None = None):
        self.mails = list(mails)
        self.error = error
        self.fetches = 0
        self.finished: list[tuple[list, bool]] = []

    def fetch_unseen(self):
        self.fetches += 1
        if self.error:
            raise self.error
        mails, self.mails = self.mails, []
        return mails

    def finish(self, dispositions, move):
        self.finished.append((dispositions, move))


async def _coordinator(hass, mailbox, options=None):
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options=options or {})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, {}, mailbox)


async def test_first_refresh_does_not_touch_the_mailbox(hass):
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox)
    await coord.async_refresh()
    assert mailbox.fetches == 0
    await coord.async_refresh()
    assert mailbox.fetches == 1


async def test_import_merges_and_files_mails(hass, hass_storage):
    mailbox = FakeMailbox(
        [
            ("1", raw("001_bestellbestaetigung_bestellt.eml")),
            ("2", raw("074_versandbestaetigung_versendet.eml")),
            ("3", raw("045_noreply_ihre_amazon_sendung_ist_unterweg.eml")),
        ]
    )
    coord = await _coordinator(hass, mailbox)
    await coord.async_import_mail()
    parcel = coord.store.get(PLAETTCHEN)
    assert parcel.tracking_ref == JJD
    assert coord.store.get(JJD) is None
    assert mailbox.finished == [
        ([("1", FOLDER_PROCESSED), ("2", FOLDER_PROCESSED), ("3", FOLDER_PROCESSED)], True)
    ]
    saved = hass_storage["parcel_tracker"]["data"]
    assert saved["parcels"][0]["tracking_ref"] == JJD
    assert "<58f5d0e669f8cc94ea92ef2f@example.org>" in saved["message_ids"]


async def test_duplicate_message_id_is_applied_once(hass):
    mailbox = FakeMailbox(
        [
            ("1", raw("071_pkginfo_ups_zustellbenachrichtigung_kont.eml")),
            ("2", raw("072_pkginfo_ups_zustellbenachrichtigung_kont.eml")),
        ]
    )
    coord = await _coordinator(hass, mailbox)
    with patch(
        "custom_components.parcel_tracker.coordinator.apply_update", wraps=apply_update
    ) as apply:
        await coord.async_import_mail()
    assert apply.call_count == 1
    assert coord.store.get("1Z999AA11026832876").status is ParcelStatus.DELIVERED
    assert mailbox.finished[0][0] == [("1", FOLDER_PROCESSED), ("2", FOLDER_PROCESSED)]
    assert coord.store.message_ids == ["<9f564783a8226fbb5012f307@example.org>"]


async def test_unrecognised_ignored_and_broken_mails(hass):
    no_number = (
        b"From: Shop <shop@example.org>\r\nMessage-ID: <n@example.org>\r\n"
        b"Subject: Danke\r\nDate: Wed, 30 Sep 2026 08:00:00 +0000\r\n\r\nDanke\r\n"
    )
    ignored = (
        b"From: Prime Video <no-reply@primevideo.com>\r\nMessage-ID: <p@example.org>\r\n"
        b"Subject: Neu\r\nDate: Wed, 30 Sep 2026 08:00:00 +0000\r\n\r\nFilm\r\n"
    )
    mailbox = FakeMailbox(
        [
            ("1", no_number),
            ("2", ignored),
            ("3", raw("070_pkginfo_ups_versandbenachrichtigung_kont.eml")),
            ("4", raw("001_bestellbestaetigung_bestellt.eml")),
        ]
    )
    coord = await _coordinator(hass, mailbox, {CONF_MOVE_PROCESSED: False})

    def flaky(msg, read_otp):
        if "ups.com" in str(msg["From"]):
            raise ValueError("boom")
        return parse_mail(msg, read_otp)

    with patch("custom_components.parcel_tracker.coordinator.parse_mail", side_effect=flaky):
        await coord.async_import_mail()
    assert mailbox.finished == [
        (
            [
                ("1", FOLDER_UNRECOGNIZED),
                ("2", None),
                ("3", FOLDER_UNRECOGNIZED),
                ("4", FOLDER_PROCESSED),
            ],
            False,
        )
    ]
    assert coord.store.get(PLAETTCHEN) is not None


async def test_amazon_unrecognized_issue_after_five_in_a_row(hass):
    mailbox = FakeMailbox([(str(i), unknown_amazon_mail(i)) for i in range(4)])
    coord = await _coordinator(hass, mailbox)
    await coord.async_import_mail()
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "amazon_unrecognized") is None
    mailbox.mails = [("4", unknown_amazon_mail(4))]
    coord._mail_next = None
    await coord.async_import_mail()
    assert registry.async_get_issue(DOMAIN, "amazon_unrecognized") is not None
    mailbox.mails = [("5", raw("001_bestellbestaetigung_bestellt.eml"))]
    coord._mail_next = None
    await coord.async_import_mail()
    assert registry.async_get_issue(DOMAIN, "amazon_unrecognized") is None


async def test_auth_error_creates_issue_and_backs_off(hass, freezer):
    mailbox = FakeMailbox(error=ImapAuthError("no"))
    coord = await _coordinator(hass, mailbox)
    await coord.async_import_mail()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "imap_auth") is not None
    await coord.async_import_mail()
    assert mailbox.fetches == 1  # still waiting 5 minutes
    freezer.tick(timedelta(minutes=5))
    mailbox.error = None
    await coord.async_import_mail()
    assert mailbox.fetches == 2
    assert ir.async_get(hass).async_get_issue(DOMAIN, "imap_auth") is None


async def test_unavailable_backoff_doubles_up_to_60_minutes(hass, freezer):
    mailbox = FakeMailbox(error=ImapUnavailable("down"))
    coord = await _coordinator(hass, mailbox)
    waits = []
    for _ in range(6):
        start = dt_util.utcnow()
        await coord.async_import_mail()
        waits.append(coord._mail_next - start)
        freezer.tick(coord._mail_next - start)
    assert [w.total_seconds() / 60 for w in waits] == [5, 10, 20, 40, 60, 60]
    assert ir.async_get(hass).async_get_issue(DOMAIN, "imap_auth") is None


async def test_status_change_from_mail_fires_event(hass):
    mailbox = FakeMailbox([("1", raw("001_bestellbestaetigung_bestellt.eml"))])
    coord = await _coordinator(hass, mailbox)
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await coord.async_refresh()  # first refresh: no mail import, no events
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert events == []  # creation is not a status change
    mailbox.mails = [("2", raw("074_versandbestaetigung_versendet.eml"))]
    coord._mail_next = None
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["number"] == PLAETTCHEN
    assert events[0].data["old_status"] == "pre_transit"
    assert events[0].data["new_status"] == "in_transit"
    assert events[0].data["carrier"] == "amazon"


async def test_read_otp_option_keeps_code_in_memory_only(hass, hass_storage):
    mailbox = FakeMailbox([("1", raw("096_shipment_tracking_zustellung_heute_f_r_d.eml"))])
    coord = await _coordinator(hass, mailbox, {CONF_READ_OTP: True})
    await coord.async_import_mail()
    parcel = coord.store.get("AMZ99905626221455530")
    assert parcel.delivery_code == "123456"
    assert "123456" not in str(hass_storage["parcel_tracker"]["data"])


@pytest.mark.parametrize("move", [True, False])
async def test_move_option_is_passed_to_finish(hass, move):
    mailbox = FakeMailbox([("1", raw("001_bestellbestaetigung_bestellt.eml"))])
    coord = await _coordinator(hass, mailbox, {CONF_MOVE_PROCESSED: move})
    await coord.async_import_mail()
    assert mailbox.finished[0][1] is move


async def test_import_error_does_not_break_refresh_and_backs_off(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    mailbox = FakeMailbox(error=RuntimeError("boom"))
    coord = await _coordinator(hass, mailbox)
    await coord.async_refresh()  # first refresh: no import
    data = await coord._async_update_data()
    assert data == {}
    assert coord.last_update_success
    assert mailbox.fetches == 1
    assert coord._mail_next - dt_util.utcnow() == timedelta(minutes=5)
    await coord._async_update_data()
    assert mailbox.fetches == 1  # backing off
    freezer.tick(timedelta(minutes=5))
    await coord._async_update_data()
    assert mailbox.fetches == 2
    assert coord._mail_next - dt_util.utcnow() == timedelta(minutes=10)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "imap_auth") is None


async def test_error_while_applying_is_isolated(hass, caplog):
    mailbox = FakeMailbox([("1", raw("001_bestellbestaetigung_bestellt.eml"))])
    coord = await _coordinator(hass, mailbox)
    with patch.object(coord.store, "async_save", side_effect=RuntimeError("disk")):
        await coord.async_import_mail()
    assert coord._mail_streak == 1
    assert "RuntimeError" in caplog.text
    assert "Metallpl" not in caplog.text  # never mail content in the log


async def test_second_import_while_one_runs_is_skipped(hass):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowMailbox(FakeMailbox):
        def fetch_unseen(self):
            self.fetches += 1
            hass.loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), hass.loop).result()
            return []

    mailbox = SlowMailbox()
    coord = await _coordinator(hass, mailbox)
    first = hass.async_create_task(coord.async_import_mail())
    await started.wait()
    coord._mail_next = None  # even a due import must not start a second fetch
    await coord.async_import_mail()
    release.set()
    await first
    assert mailbox.fetches == 1


async def test_mails_older_than_14_days_are_only_marked_read(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    mailbox = FakeMailbox(
        [
            ("1", dated_mail(1, "Tue, 15 Sep 2026 09:00:00 +0000")),  # 15 days
            ("2", dated_mail(2, "Thu, 17 Sep 2026 09:00:00 +0000")),  # 13 days
            ("3", unknown_amazon_mail(3).replace(b"30 Sep 2026", b"01 Sep 2026")),
        ]
    )
    coord = await _coordinator(hass, mailbox)
    with patch(
        "custom_components.parcel_tracker.coordinator.MAIL_MAX_AGE", timedelta(days=14)
    ), patch("custom_components.parcel_tracker.coordinator.parse_mail", wraps=parse_mail) as parse:
        await coord.async_import_mail()
    assert parse.call_count == 1
    assert coord.store.get("00340999999999999911") is None
    assert coord.store.get("00340999999999999912") is not None
    assert mailbox.finished[0][0] == [("1", None), ("2", FOLDER_PROCESSED), ("3", None)]
    assert coord._amazon_misses == 0


async def test_mails_are_parsed_in_the_executor(hass):
    mailbox = FakeMailbox([("1", raw("001_bestellbestaetigung_bestellt.eml"))])
    coord = await _coordinator(hass, mailbox)
    threads = []

    def spy(msg, read_otp):
        threads.append(threading.current_thread() is threading.main_thread())
        return parse_mail(msg, read_otp)

    with patch("custom_components.parcel_tracker.coordinator.parse_mail", side_effect=spy):
        await coord.async_import_mail()
    assert threads == [False]
    assert coord.store.get(PLAETTCHEN) is not None


async def test_success_schedules_next_import_after_configured_interval(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    mailbox = FakeMailbox()
    coord = await _coordinator(hass, mailbox, {CONF_MAIL_INTERVAL: 17})
    await coord.async_import_mail()
    assert coord._mail_next - dt_util.utcnow() == timedelta(minutes=17)
    freezer.tick(timedelta(minutes=16))
    await coord.async_import_mail()
    assert mailbox.fetches == 1
    freezer.tick(timedelta(minutes=1))
    await coord.async_import_mail()
    assert mailbox.fetches == 2


async def test_backoff_ignores_configured_interval(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    coord = await _coordinator(
        hass, FakeMailbox(error=ImapUnavailable("down")), {CONF_MAIL_INTERVAL: 30}
    )
    await coord.async_import_mail()
    assert coord._mail_next - dt_util.utcnow() == timedelta(minutes=5)


async def test_refresh_forces_immediate_import_even_in_backoff(hass, freezer):
    freezer.move_to("2026-09-30 10:00:00+00:00")
    mailbox = FakeMailbox(error=ImapAuthError("no"))
    coord = await _coordinator(hass, mailbox)
    await coord.async_refresh()  # first refresh: no import
    await coord.async_refresh()
    assert mailbox.fetches == 1
    await coord.async_refresh()
    assert mailbox.fetches == 1  # backing off
    await coord.async_refresh_parcels(None)
    assert mailbox.fetches == 2


GLS_MAILS = [
    "107_shop_versand_ihrer_bestellung_beispiel_g.eml",
    "110_no_reply_dein_paket_wird_an_dem_gew_nsch.eml",
    "108_no_reply_dein_gls_paket_kommt_heute.eml",
    "112_no_reply_dein_paket_wurde_an_deinem_wuns.eml",
    "111_no_reply_dein_paket_wird_in_wenigen_tage.eml",
    "109_no_reply_dein_gls_paket_kommt_heute.eml",
]


async def test_gls_mails_become_two_parcels_and_the_shop_mail_is_unrecognised(
    hass, hass_storage, caplog
):
    mailbox = FakeMailbox([(str(i), raw(name)) for i, name in enumerate(GLS_MAILS)])
    coord = await _coordinator(hass, mailbox)
    with caplog.at_level("DEBUG"):
        await coord.async_import_mail()
    first, second = coord.store.get("99999999901"), coord.store.get("99999999902")
    assert (first.carrier, first.name, first.status) == (
        "gls", "Beispiel GmbH", ParcelStatus.DELIVERED,
    )
    assert (second.carrier, second.status) == ("gls", ParcelStatus.OUT_FOR_DELIVERY)
    assert len(coord.store.parcels) == 2
    [(dispositions, _)] = mailbox.finished
    assert dispositions == [("0", FOLDER_UNRECOGNIZED)] + [
        (str(i), FOLDER_PROCESSED) for i in range(1, 6)
    ]
    # Drop-off place, address, recipient and reference are neither stored nor logged.
    dump = str(hass_storage["parcel_tracker"]["data"]) + caplog.text
    for secret in ("Garage", "Musterstraße", "Musterstadt", "Mustermann", "REF-0001", "+49"):
        assert secret not in dump, secret


# ----- v0.3.15: DPD Austria mails tell the status themselves -----
class _CountingDpd:
    """Stands in for the DPD lookup: counts its calls and answers "in transit"."""

    key = "dpd"
    name = "DPD"

    def __init__(self):
        self.calls = 0

    async def fetch(self, number, postcode):
        from custom_components.parcel_tracker.models import TrackingResult

        self.calls += 1
        return TrackingResult(
            ParcelStatus.IN_TRANSIT, "Paket unterwegs", None, None, None, None, None, None,
            None, [],
        )


async def test_dpd_mail_status_and_the_live_lookup(hass, freezer):
    """The announcing mail creates the parcel and the lookup may move it on; once a mail
    says "delivered", the lookup is never asked again and cannot move the parcel back."""
    from custom_components.parcel_tracker.mail.base import at, sent_at

    from .conftest import load_mail

    new, dropped = "114_dpd_at_neues_paket.eml", "119_dpd_at_abgestellt.eml"
    # just after the second mail was sent (in the evening, before the night window)
    freezer.move_to(sent_at(load_mail(dropped)) + timedelta(minutes=5))
    number = "09999999999901"
    # the second mail speaks about the same parcel here
    same_parcel = raw(dropped).replace(b"09999999999902", number.encode())
    mailbox = FakeMailbox([("1", raw(new))])
    dpd = _CountingDpd()
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "1010", "country": "at"})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    coord = ParcelCoordinator(hass, entry, store, {"dpd": dpd}, mailbox)

    await coord.async_import_mail()
    parcel = coord.store.get(number)
    assert (parcel.carrier, parcel.status) == ("dpd", ParcelStatus.PRE_TRANSIT)
    await coord.async_refresh()
    assert dpd.calls == 1 and parcel.status is ParcelStatus.IN_TRANSIT  # the lookup knows more

    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    mailbox.mails = [("2", same_parcel)]
    freezer.tick(timedelta(minutes=6))  # the next look into the mailbox, no poll due yet
    await coord.async_import_mail()
    assert dpd.calls == 1 and parcel.status is ParcelStatus.DELIVERED
    delivered_at = at(sent_at(load_mail(dropped)).date(), 16, 52)
    assert parcel.result.delivered_at == delivered_at
    await hass.async_block_till_done()
    assert [e.data["new_status"] for e in events] == ["delivered"]

    freezer.tick(timedelta(hours=2))
    await coord.async_refresh()
    await coord.async_refresh_parcels(number)  # even on request
    assert dpd.calls == 1
    assert parcel.status is ParcelStatus.DELIVERED
    assert parcel.result.delivered_at == delivered_at
    # nothing but the number, the status and the time is stored
    assert "Abstellort" not in str(parcel.to_dict()) and parcel.name is None


# ----- v0.3.15: a 12-digit DHL number from a mail is asked at DHL -----
async def test_12_digit_dhl_number_from_a_mail_is_polled_and_can_be_added_by_hand(hass, freezer):
    from custom_components.parcel_tracker.mail.base import sent_at

    from .conftest import load_mail

    name = "120_dhl_zustellung_kommt_heute.eml"
    freezer.move_to(sent_at(load_mail(name)) + timedelta(minutes=5))
    dhl = _CountingDpd()
    dhl.key, dhl.name = "dhl", "DHL"
    from custom_components.parcel_tracker.carriers.dhl import DhlCarrier

    dhl.matches = DhlCarrier.matches
    asked = []

    async def fetch(number, postcode):
        asked.append(number)
        return await _CountingDpd.fetch(dhl, number, postcode)

    dhl.fetch = fetch
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115", "api_key": "invented"})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    coord = ParcelCoordinator(hass, entry, store, {"dhl": dhl}, FakeMailbox([("1", raw(name))]))

    await coord.async_import_mail()
    parcel = coord.store.get("999999999901")
    assert (parcel.carrier, parcel.status, parcel.name) == (
        "dhl", ParcelStatus.OUT_FOR_DELIVERY, None,
    )
    await coord.async_refresh()
    assert asked == ["999999999901"]  # with a key the DHL lookup takes over
    assert parcel.status is ParcelStatus.IN_TRANSIT

    by_hand = await coord.async_add("9999 9999 9902", "dhl", None)
    assert (by_hand.number, by_hand.carrier, by_hand.carrier_mode) == (
        "999999999902", "dhl", "manual",
    )
    automatic = await coord.async_add("999999999903", "auto", None)
    assert automatic.carrier_mode == "auto"
    await coord.async_refresh()
    assert set(asked) == {"999999999901", "999999999902", "999999999903"}

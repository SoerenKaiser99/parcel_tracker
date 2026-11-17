"""v0.3.56: UPS mails from mcinfo@ups.com ("UPS My Choice", #37)."""

from datetime import date, datetime, time
from email import policy
from email.message import EmailMessage

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import is_ignored, parse_mail
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

NUMBER = "1Z999AA10123456784"
TOMORROW = "UPS Update: Paket ist morgen für die Zustellung terminiert"


def _window(day: date, start: time, end: time) -> tuple[datetime, datetime]:
    return datetime.combine(day, start, BERLIN), datetime.combine(day, end, BERLIN)


def test_the_shipping_notice_is_on_its_way_with_day_window_and_shipper():
    [u] = parse_mail(load_mail("212_mcinfo_ups_versandbenachrichtigung.eml")).updates
    assert (u.number, u.carrier, u.status) == (NUMBER, "ups", ParcelStatus.IN_TRANSIT)
    assert u.eta_date == date(2026, 11, 18)
    assert (u.eta_from, u.eta_to) == _window(date(2026, 11, 18), time(9, 45), time(13, 45))
    assert u.title == "YUBICO AB"


def test_the_mail_for_tomorrow_keeps_day_and_window():
    [u] = parse_mail(load_mail("213_mcinfo_ups_morgen_terminiert.eml")).updates
    assert (u.number, u.status) == (NUMBER, ParcelStatus.IN_TRANSIT)
    assert u.eta_date == date(2026, 11, 18)
    assert (u.eta_from, u.eta_to) == _window(date(2026, 11, 18), time(9, 45), time(13, 45))


def test_the_sender_is_not_ignored():
    assert not is_ignored("mcinfo@ups.com")


def _mc(subject: str, body: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = '"UPS" <mcinfo@ups.com>'
    msg["Subject"] = subject
    msg["Date"] = "Tue, 17 Nov 2026 05:25:22 -0500"
    msg.set_content(body)
    return msg


def test_a_person_as_shipper_never_names_the_parcel():
    body = (
        f"Ihr Paket kommt morgen an.\nVon Max Mustermann\nGeschätzte Zustellung\n"
        f"Mittwoch 18/11/2026\n{NUMBER}\n"
    )
    [u] = parse_mail(_mc(TOMORROW, body)).updates
    assert u.title is None


def test_without_a_window_only_the_day_counts():
    body = f"Ihr Paket kommt morgen an.\nGeschätzte Zustellung\nMittwoch 18/11/2026\n{NUMBER}\n"
    [u] = parse_mail(_mc(TOMORROW, body)).updates
    assert (u.eta_date, u.eta_from, u.eta_to) == (date(2026, 11, 18), None, None)


def test_an_impossible_window_is_left_out():
    body = (
        "Ihr Paket kommt morgen an.\nGeschätzte Zustellung\nMittwoch 18/11/2026\n"
        f"zwischen 13:45 - 09:45\n{NUMBER}\n"
    )
    [u] = parse_mail(_mc(TOMORROW, body)).updates
    assert (u.eta_date, u.eta_from, u.eta_to) == (date(2026, 11, 18), None, None)


def test_an_unknown_mcinfo_mail_only_names_the_number():
    body = f"Etwas Neues zu Ihrem Paket.\n{NUMBER}\n"
    [u] = parse_mail(_mc("UPS Update: Neuigkeiten", body)).updates
    assert (u.number, u.carrier, u.status, u.eta_date) == (NUMBER, "ups", None, None)

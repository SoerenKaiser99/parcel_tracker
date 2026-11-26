"""Tester mode: a mail's HTML part keeps what carries text or meaning where it stands, with
every value invented, and loses what is layout (synthetic personal data only)."""

import email
import email.utils
import re
from email import policy
from email.message import EmailMessage
from urllib.parse import quote, unquote

import pytest

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.base import brand_of, is_seller, shorten

from .test_anonymize_tester import _call, _dump

ORDER = "302-4567890-1234567"
TAPE = ("B0TAPE1234", "Echtmarke Maßband 5 m mit Feststellknopf und Gürtelclip gelb")
TIES = ("B0TIES5678", "Echtmarke Kabelbinder 300 Stück schwarz extra lang 30 cm")
SHIPMENT = "DqWeRtZuI"
DHL_NUMBER = "00340434161094012345"
PERSONAL = ("Jörg", "Joerg", "Probst", "privatpost", "Beispielhausen", ORDER, "Echtmarke",
            "Echthandel", "B0TAPE1234", "B0TIES5678", SHIPMENT, DHL_NUMBER, "u1s2e3r4",
            "Fensterbank", "71abcDEF")


def _redirect(target: str) -> str:
    return f"https://www.amazon.de/gp/r.html?C=K9X&amp;U={quote(target, safe='')}&amp;H=Q7Z"


def _item(asin: str, name: str) -> str:
    page = _redirect(f"https://www.amazon.de/dp/{asin}?ref_=pe_123_456_fed_asin_title")
    return (
        '<tr><td><table role="presentation"><tr><td class="productImageTd">'
        f'<a href="{page}" target="_blank"><img class="rio-asin-image" width="96" '
        f'src="https://m.media-amazon.com/images/I/71abcDEF.jpg" alt="{name}"></a>'
        "</td></tr></table></td></tr>"
        f'<tr><td><span class="rio-text"><a href="{page}" title="{name}">{name[:30]}...</a>'
        "</span></td></tr>"
        "<tr><td>Verkauf durch Echthandel GmbH, Händler &amp; Versand aus Deutschland</td></tr>"
        "<tr><td>Zustand: Neu</td></tr><tr><td>Menge: 1</td></tr>"
        '<tr><td><span aria-label="{amount=37.65, currency={code=EUR, symbol=€}}">37,65 €</span>'
        "</td></tr>"
    )


def _amazon(subject: str, status_line: str, items, tracking: bool, date: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = '"Amazon.de" <versandbestaetigung@amazon.de>'
    msg["To"] = "joerg.probst@privatpost.de"
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = f"<{abs(hash(subject))}@amazon.de>"
    text_items = "".join(f"* {name}\n  Menge: 1\n  37,65 EUR\n" for _, name in items)
    track = (f"https://www.amazon.de/progress-tracker/package?orderId={ORDER}"
             f"&shipmentId={SHIPMENT}&packageIndex=0")
    msg.set_content(
        f"Hallo Jörg,\n{status_line}\nAnkunft morgen\nJörg – Beispielhausen\n"
        f"Bestellnr.\n{ORDER}\n" + (f"Lieferung verfolgen\n{track}\n" if tracking else "")
        + text_items + "Summe\n37,65 EUR\n"
    )
    first = items[0][1]
    msg.add_alternative(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Amazon</title>"
        "<style>.rio-text{color:#000}</style></head><body>"
        f'<div style="display:none;max-height:0">{first[:20]}… Ankunft morgen</div>'
        "<!--[if mso]><table><tr><td><![endif]-->"
        '<table role="presentation" width="100%"><tr><td align="center">'
        "<p>Hallo Jörg,</p>"
        '<img src="https://m.media-amazon.com/x.png" aria-label="Abgeschlossen" alt="">'
        '<img src="https://m.media-amazon.com/y.png" aria-label="Ausstehend" alt="">'
        f"<p>{status_line}</p><p>Ankunft morgen</p>"
        '<div data-delivery-window="Heute u1s2e3r4 an der Fensterbank">Jörg – Beispielhausen</div>'
        f"<p>Bestellnr. <span>{ORDER}</span></p>"
        + (f'<p><a href="{_redirect(track)}">Lieferung verfolgen</a></p>' if tracking else "")
        + "<table>" + "".join(_item(asin, name) for asin, name in items) + "</table>"
        '<table data-sonar-role="footer"><tr><td>Datenschutzerklärung</td></tr></table>'
        '<img src="https://www.amazon.de/gp/r.html?u=u1s2e3r4" width="1" height="1">'
        '<svg viewBox="0 0 8 8"><path d="M0 0h8"/></svg>'
        "<!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>",
        subtype="html",
    )
    return bytes(msg)


ORDERED = _amazon("Bestellt: „Echtmarke Maßband 5 m mi…“ und 1 weiterer Artikel",
                  "Vielen Dank für deine Bestellung!", [TAPE, TIES], False,
                  "Mon, 09 Nov 2026 18:10:04 +0000")
SHIPPED = _amazon("Versendet: „Echtmarke Kabelbinder 3…“", "Dein Paket wurde versendet!",
                  [TIES], True, "Tue, 10 Nov 2026 21:57:25 +0000")


def _dhl() -> bytes:
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["To"] = "joerg.probst@privatpost.de"
    msg["Subject"] = "Ihre Beispielversender GmbH Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg["Message-ID"] = "<dhl-1@dhl.de>"
    msg.set_content(f"Hallo Jörg Probst,\nIhre Sendung {DHL_NUMBER} kommt heute.\n")
    link = ("https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html"
            f"?piececode={DHL_NUMBER}&amp;lang=de")
    msg.add_alternative(
        f'<html><body><p>Hallo Jörg Probst,</p><p>Ihre Sendung <a href="{link}">'
        f'{DHL_NUMBER}</a> kommt heute.</p><img alt="DHL Logo" src="https://www.dhl.de/logo.png">'
        "</body></html>",
        subtype="html",
    )
    return bytes(msg)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    src = tmp_path_factory.mktemp("html")
    for name, raw in (("1.eml", ORDERED), ("2.eml", SHIPPED), ("3.eml", _dhl())):
        (src / name).write_bytes(raw)
    # (no own values: the tester mode finds them itself)
    done = _call(src, "--ohne-angaben")
    assert done.returncode == 0, done.stderr
    files = {p.name: p.read_bytes() for p in sorted((src / "anonymisiert").glob("*.eml"))}
    return files, done.stdout


def _msg(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=policy.default)


def _html(raw: bytes) -> str:
    return _msg(raw).get_body(("html",)).get_content()


def _sent_by(run, host: str) -> list[bytes]:
    return [raw for raw in run[0].values() if host in str(_msg(raw)["From"])]


def _invented(name: str) -> bool:
    """An invented item's name: its second word is one of the made-up brands."""
    return re.match(r"\S+ (?:Beispielmarke|Musterfirma)\b", name) is not None


def _amazon_out(run):
    ordered, shipped = sorted(_sent_by(run, "amazon.de"), key=lambda raw: str(_msg(raw)["Date"]))
    return ordered, shipped


def test_a_mail_with_text_and_html_keeps_both(run):
    for raw in run[0].values():
        msg = _msg(raw)
        assert msg.get_body(("plain",)) is not None and msg.get_body(("html",)) is not None


def test_no_personal_value_survives_in_any_part(run):
    for name, raw in run[0].items():
        dump = _dump(raw)
        for value in PERSONAL:
            assert value.lower() not in dump, (name, value)


def test_layout_and_technique_go(run):
    for raw in run[0].values():
        markup = _html(raw)
        for gone in ("<style", "<meta", "<title", "[if mso]", "<table", "<td", "<svg", "<path",
                     "class=", "width=", 'height="1"'):
            assert gone not in markup, gone


def test_what_carries_meaning_stays_in_place(run):
    ordered, _ = _amazon_out(run)
    markup = _html(ordered)
    assert '<div style="display:none">' in markup  # hidden preview text, with its marker
    assert 'aria-label="Abgeschlossen"' in markup and 'aria-label="Ausstehend"' in markup
    assert '<div data-sonar-role="footer">' in markup
    # An attribute nobody knows yet: there, every word of it invented
    found = re.search(r'<div data-delivery-window="([^"]+)">', markup)
    assert found and re.fullmatch(r"[A-Z][a-z]{4} [a-z0-9]{8} [a-z]{2} [a-z]{3} [A-Z][a-z]{10}",
                                  found.group(1))
    assert 'aria-label="{amount=37.65, currency={code=EUR, symbol=€}}"' in markup


def test_an_attribute_without_a_rule_is_told_by_name(run):
    assert "data-delivery-window" in run[1] and "Fensterbank" not in run[1]


def test_amazon_items_get_zz_numbers_and_invented_names_everywhere(run):
    ordered, shipped = _amazon_out(run)
    [box] = [u.items for u in parse_mail(_msg(ordered)).updates]
    tape_id, ties_id = (i.article_id for i in box)
    assert re.fullmatch(r"ZZ\d{8}", tape_id) and re.fullmatch(r"ZZ\d{8}", ties_id)
    assert tape_id != ties_id
    # The same item has the same number in the next mail.
    [[ties]] = [u.items for u in parse_mail(_msg(shipped)).updates]
    assert ties.article_id == ties_id
    tape_name, ties_name = re.findall(r'<img [^>]*alt="([^"]+)"', _html(ordered))
    assert _invented(tape_name) and tape_name != ties_name
    assert re.findall(r'<img [^>]*alt="([^"]+)"', _html(shipped)) == [ties_name]
    # Subject, text, title and the link's text name it as well, cut where Amazon cut it.
    cut = len("Echtmarke Maßband 5 m mi")
    assert str(_msg(ordered)["Subject"]).startswith(f"Bestellt: „{tape_name[:cut].rstrip()}…“")
    assert f"* {tape_name}" in _msg(ordered).get_body(("plain",)).get_content()
    markup = _html(ordered)
    assert f'title="{tape_name}"' in markup and f">{tape_name[:30].rstrip()}...</a>" in markup


def test_the_seller_becomes_an_invented_company_with_its_legal_form(run):
    ordered, _ = _amazon_out(run)
    [update] = parse_mail(_msg(ordered)).updates
    assert re.fullmatch(r"(?:Beispielhandel|Musterladen)(?: \w+)? GmbH", update.seller)


def test_the_importer_reads_the_same_from_both(run):
    for original, written in zip((ORDERED, SHIPPED), _amazon_out(run), strict=True):
        [before], [after] = parse_mail(_msg(original)).updates, parse_mail(_msg(written)).updates
        assert (after.carrier, after.status) == (before.carrier, before.status)
        assert [i.quantity for i in after.items] == [i.quantity for i in before.items]
        assert (after.shipment_id is None) is (before.shipment_id is None)
        # Link text and alt text still begin alike, so each item keeps its invented full name.
        names = [shorten(n) for n in re.findall(r'<img [^>]*alt="([^"]+)"', _html(written))]
        assert [i.title for i in after.items] == names  # (as long as every title)


def test_amazons_shipment_keeps_its_first_letter(run):
    _, shipped = _amazon_out(run)
    [update] = parse_mail(_msg(shipped)).updates
    assert update.shipment_id[0] == "D" and update.shipment_id != SHIPMENT  # (sent by the seller)


def test_a_carriers_link_keeps_its_form_and_the_number_of_the_text(run):
    [dhl] = (_msg(raw) for raw in _sent_by(run, "dhl.de"))
    [number] = re.findall(r"00340\d{15}", dhl.get_body(("plain",)).get_content())
    assert number != DHL_NUMBER
    markup = dhl.get_body(("html",)).get_content()
    assert (
        'href="https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html'
        f'?piececode={number}&amp;lang=de"' in markup
    )
    assert f">{number}</a>" in markup
    # (a picture's text keeps the words of the template; a name only a picture tells is
    # invented, see test_anonymize_numbers.py)
    assert '<img alt="DHL Logo" src="https://www.dhl.de/bild.png">' in markup


def test_an_asin_as_a_links_title_becomes_the_number_of_the_link(tmp_path):
    # Older Amazon mails name the item's ASIN as the title of its link.
    page = _redirect("https://www.amazon.de/dp/B0OLD12345?ref_=pe_1_2_dp_i1")
    msg = EmailMessage()
    msg["From"] = '"Amazon.de" <versandbestaetigung@amazon.de>'
    msg["Subject"] = "Versendet: „Beispiel…“"
    msg["Date"] = "Tue, 10 Nov 2026 21:57:25 +0000"
    msg.set_content(f"Bestellnr.\n{ORDER}\n")
    msg.add_alternative(
        f'<p>Bestellnr. {ORDER}</p><a href="{page}" title="B0OLD12345"><img src="x.png" alt=""></a>'
        "<p>Menge: 1</p>",
        subtype="html",
    )
    (tmp_path / "old.eml").write_bytes(bytes(msg))
    assert _call(tmp_path, "--ohne-angaben").returncode == 0
    [raw] = [p.read_bytes() for p in (tmp_path / "anonymisiert").glob("*.eml")]
    assert "b0old12345" not in _dump(raw)
    markup = _html(raw)
    [number] = set(re.findall(r"ZZ\d{8}", markup))
    assert f'title="{number}"' in markup and f"%2Fdp%2F{number}" in markup


def test_an_item_named_only_by_its_links_text_gets_the_name_of_its_order(tmp_path):
    # Older cancellations: the picture beside the link, the ASIN as the link's title, the name
    # only as the text of a second link. It is the same invented name as in the order, so the
    # importer still finds the item the cancellation means.
    asin, name = TAPE
    page = _redirect(f"https://www.amazon.de/dp/{asin}/ref=pe_1_2_TE_slc_i_id")
    msg = EmailMessage()
    msg["From"] = '"Amazon.de" <bestellbestaetigung@amazon.de>'
    msg["Subject"] = "Erfolgreiche Stornierung von Artikeln aus Ihrer Amazon.de -Bestellung"
    msg["Date"] = "Tue, 10 Nov 2026 08:00:00 +0000"
    msg.set_content(f"Stornierte Artikel\nBestell-Nr.{ORDER}\nAufgegeben am 9. November 2026\n\n"
                    f"        {name}\n        Verkauft von Amazon EU S.a.r.L.\n")
    msg.add_alternative(
        f"<p>Bestell-Nr.{ORDER}</p><p>Aufgegeben am 9. November 2026</p>"
        f'<a href="{page}" title="{asin}"></a><img src="https://m.media-amazon.com/x.jpg">'
        f'<ul><li><a href="{page}">{name}</a></li></ul><p>Verkauft von Amazon EU S.a.r.L.</p>',
        subtype="html",
    )
    (tmp_path / "1.eml").write_bytes(ORDERED)
    (tmp_path / "2.eml").write_bytes(bytes(msg))
    assert _call(tmp_path, "--ohne-angaben").returncode == 0
    out = sorted((_msg(p.read_bytes()) for p in (tmp_path / "anonymisiert").glob("*.eml")),
                 key=lambda m: str(m["Date"]))
    [ordered], [cancelled] = (parse_mail(m).updates for m in out)
    assert "echtmarke" not in _dump(bytes(out[1]))
    assert cancelled.title == ordered.items[0].title and _invented(cancelled.title)


def test_a_name_an_element_splits_from_its_greeting_is_replaced_all_the_same(tmp_path):
    # The greeting split over elements (a template builder's spans): the rule for greetings
    # cannot see past their marks, the name goes all the same, the elements stay.
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg.add_alternative(
        '<p><span data-x="1">Hallo</span> <span data-x="2">Timon Wackerbarth,</span></p>'
        f"<p>Ihre Sendung {DHL_NUMBER} kommt heute.</p>",
        subtype="html",
    )
    (tmp_path / "dhl.eml").write_bytes(bytes(msg))
    assert _call(tmp_path, "--ohne-angaben").returncode == 0
    [raw] = [p.read_bytes() for p in (tmp_path / "anonymisiert").glob("*.eml")]
    dump = _dump(raw)
    assert "timon" not in dump and "wackerbarth" not in dump
    assert '<span data-x="' in _html(raw)


def test_a_mail_forwarded_without_subject_prefix_keeps_the_simple_html_part(tmp_path):
    # Forwarded by hand ("Am … schrieb …:"): the HTML part stays as simple as before (the run
    # names such a mail at its end, see test_anonymize_tester.py).
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg.add_alternative(
        "<p>Schau mal, liebe Grüße Wiebke Quandtberg</p>"
        "<p>Am 10.11.2026 um 07:00 schrieb DHL Paket &lt;noreply@dhl.de&gt;:</p>"
        f'<p>Ihre Sendung <a href="https://www.dhl.de/x?piececode={DHL_NUMBER}">{DHL_NUMBER}</a>'
        " kommt heute.</p>",
        subtype="html",
    )
    (tmp_path / "fwd.eml").write_bytes(bytes(msg))
    assert _call(tmp_path, "--ohne-angaben").returncode == 0
    [raw] = [p.read_bytes() for p in (tmp_path / "anonymisiert").glob("*.eml")]
    assert "<a " not in _html(raw) and DHL_NUMBER not in _dump(raw)


def _results(tmp_path, *mails: bytes) -> list[bytes]:
    """The written mails, in the order of their Date header."""
    for number, raw in enumerate(mails):
        (tmp_path / f"{number}.eml").write_bytes(raw)
    done = _call(tmp_path, "--ohne-angaben")
    assert done.returncode == 0 and "Nicht lesbar" not in done.stdout, done.stdout
    found = [p.read_bytes() for p in (tmp_path / "anonymisiert").glob("*.eml")]
    return sorted(found, key=lambda raw: email.utils.parsedate_to_datetime(str(_msg(raw)["Date"])))


def _alts(raw: bytes) -> list[str]:
    return re.findall(r'<img [^>]*alt="([^"]+)"', _html(raw))


def test_a_name_the_subject_cuts_short_is_invented_there_too(tmp_path):
    # Amazon may cut the name in the subject to a few characters ("WAGO…"): the importer
    # still finds the name from the subject in the text.
    raw = _amazon("Versendet: „Echtmarke…“", "Dein Paket wurde versendet!", [TIES], True,
                  "Tue, 10 Nov 2026 21:57:25 +0000")
    [written] = _results(tmp_path, raw)
    assert "echtmarke" not in _dump(written)
    [before], [after] = parse_mail(_msg(raw)).updates, parse_mail(_msg(written)).updates
    assert before.title and after.title
    cut = re.fullmatch(r"Versendet: „(.+)…“", str(_msg(written)["Subject"]))
    assert cut and after.title.startswith(cut.group(1))


def test_items_that_begin_the_same_keep_nothing_of_their_real_names(tmp_path):
    other = ("B0TIES9999", "Echtmarke Kabelbinder Quarzgrau Profiset extra lang")
    raw = _amazon("Bestellt: „Echtmarke Kabelbinder 3…“ und 1 weiterer Artikel",
                  "Vielen Dank für deine Bestellung!", [TIES, other], False,
                  "Mon, 09 Nov 2026 18:10:04 +0000")
    [written] = _results(tmp_path, raw)
    dump = _dump(written)
    assert "echtmarke" not in dump and "quarzgrau" not in dump and "profiset" not in dump
    [update] = parse_mail(_msg(written)).updates
    assert [i.title for i in update.items] == [shorten(n) for n in _alts(written)]
    assert len(set(_alts(written))) == 2


def test_an_item_has_the_same_name_in_every_mail(tmp_path):
    # More items than invented products: names would meet, but an item keeps its own name in
    # every mail, whichever items stand beside it.
    items = [(f"B0SAME{n:04d}", f"Echtmarke Artikel Nummer {n} mit langem Namen")
             for n in range(24)]
    ordered = _amazon("Bestellt: „Echtmarke Artikel…“ und 23 weitere Artikel",
                      "Vielen Dank für deine Bestellung!", items, False,
                      "Mon, 09 Nov 2026 18:10:04 +0000")
    reversed_ = _amazon("Versendet: „Echtmarke Artikel…“", "Dein Paket wurde versendet!",
                        items[::-1], True, "Tue, 10 Nov 2026 21:57:25 +0000")
    single = _amazon("Versendet: „Echtmarke Artikel…“", "Dein Paket wurde versendet!",
                     items[-1:], True, "Wed, 11 Nov 2026 08:00:00 +0000")
    first, second, third = _results(tmp_path, ordered, reversed_, single)
    names = _alts(first)
    assert len(set(names)) == len(items)
    assert _alts(second) == names[::-1] and _alts(third) == names[-1:]


def test_the_items_of_a_mail_differ_from_their_first_letter(tmp_path):
    # Amazon may cut a name in a subject to a few characters: the items of one order must
    # not look alike there. (16 products: nine items, nine first letters.)
    items = [(f"B0DIFF{n:04d}", f"Echtmarke Artikel Nummer {n} mit langem Namen")
             for n in range(9)]
    [written] = _results(tmp_path, _amazon("Bestellt: „Echtmarke…“ und 8 weitere Artikel",
                                           "Vielen Dank für deine Bestellung!", items, False,
                                           "Mon, 09 Nov 2026 18:10:04 +0000"))
    assert len({name[0] for name in _alts(written)}) == len(items)


def _cancelled(name: str) -> bytes:
    """Amazon's cancellation of one item: its name without a link, text only."""
    msg = EmailMessage()
    msg["From"] = '"Amazon.de" <order-update@amazon.de>'
    msg["To"] = "joerg.probst@privatpost.de"
    msg["Subject"] = f"Artikel erfolgreich storniert: 1 „{name[:24]}…“"
    msg["Date"] = "Wed, 11 Nov 2026 08:00:00 +0000"
    msg["Message-ID"] = "<storno-1@amazon.de>"
    msg.set_content(f"Hallo Jörg,\ndein Artikel wurde storniert.\nBestellnr.\n{ORDER}\n"
                    f"{name}\nMenge: 1\n")
    return bytes(msg)


def test_a_mail_that_names_an_item_without_its_link_gets_its_invented_name(tmp_path):
    # The importer finds the cancelled item of the order by its name.
    ordered, cancelled = _results(tmp_path, ORDERED, _cancelled(TIES[1]))
    invented = _alts(ordered)[1]  # (TIES, the second item of the order)
    assert "echtmarke" not in _dump(cancelled)
    cut = re.search(r"„(.+)…“", str(_msg(cancelled)["Subject"]))
    assert cut and invented.startswith(cut.group(1))
    assert invented in _msg(cancelled).get_body(("plain",)).get_content()


def test_a_name_cut_short_is_cut_from_the_item_the_mail_names_in_full(tmp_path):
    # Two items of the run begin alike; a mail without links names the shorter one in
    # full in its text and cut short in its subject: the importer joins the two again.
    longer = ("B0TIES9999", "Echtmarke Kabelbinder 300 Stück schwarz extra lang 30 cm mit Box")
    ordered = _amazon("Bestellt: „Echtmarke…“ und 1 weiterer Artikel",
                      "Vielen Dank für deine Bestellung!", [TIES, longer], False,
                      "Mon, 09 Nov 2026 18:10:04 +0000")
    shipped = _msg(_cancelled(TIES[1]))
    shipped.replace_header("Subject", f"Versendet: „{TIES[1][:30]}…“")
    raw = bytes(shipped)
    first, written = _results(tmp_path, ordered, raw)
    invented = _alts(first)[0]  # (TIES)
    cut = re.search(r"„(.+)…“", str(_msg(written)["Subject"]))
    assert cut and invented.startswith(cut.group(1))
    assert invented in _msg(written).get_body(("plain",)).get_content()


def test_a_carriers_mail_names_the_seller_as_amazons_mail_does(tmp_path):
    # The importer takes a carrier's box for the seller's own when the brands agree.
    dhl = _dhl().replace(b"Beispielversender GmbH", b"Echthandel GmbH")
    ordered, delivery = _results(tmp_path, ORDERED, dhl)
    [order], [box] = parse_mail(_msg(ordered)).updates, parse_mail(_msg(delivery)).updates
    assert "echthandel" not in _dump(delivery).lower()
    assert is_seller(brand_of(box.title), order.seller)


def test_a_link_keeps_umlauts_and_plus_signs_in_their_form(tmp_path):
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg.add_alternative(
        '<p><a href="https://www.dhl.de/x?ort=Gr%C3%BCnwald&amp;q=Pakete+heute">Verfolgen</a></p>',
        subtype="html",
    )
    [written] = _results(tmp_path, bytes(msg))
    [link] = re.findall(r'href="([^"]+)"', _html(written))
    ort, q = re.fullmatch(r"https://www\.dhl\.de/x\?ort=([^&]+)&amp;q=(.+)", link).groups()
    assert "%C3%83" not in ort and unquote(ort).isalpha()
    assert re.fullmatch(r"[A-Za-z]+\+[A-Za-z]+", q)


def test_a_word_the_text_lost_goes_from_links_too(tmp_path):
    # The greeting's name goes from the text; written in lower case in a link it goes too,
    # also within a word ("twackerbarth").
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg.add_alternative(
        "<p>Hallo Timon Wackerbarth,</p>"
        '<p><a href="https://www.dhl.de/kunde/wackerbarth?vorname=timon&amp;k=twackerbarth">'
        "Verfolgen</a></p>",
        subtype="html",
    )
    [written] = _results(tmp_path, bytes(msg))
    dump = _dump(written)
    assert "timon" not in dump and "wackerbarth" not in dump
    assert re.search(r'href="https://www\.dhl\.de/kunde/[a-z]+\?vorname=[a-z]+&amp;k=[a-z]+"',
                     _html(written))


def test_characters_of_an_icon_font_are_text_not_marks(tmp_path):
    # Icon fonts use the private use area, as the marks of the elements do.
    msg = EmailMessage()
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre Sendung kommt heute"
    msg["Date"] = "Wed, 11 Nov 2026 07:12:00 +0000"
    msg.add_alternative(
        '<p>&#xF0000; Ihre Sendung &#xF0156; <a href="https://www.dhl.de/x">Verfolgen</a>'
        " kommt &#xF4000; heute.</p>",
        subtype="html",
    )
    [written] = _results(tmp_path, bytes(msg))
    markup = _html(written)
    assert markup.count("<a ") == 1 and markup.count("</a>") == 1
    assert ">Verfolgen</a> kommt heute.</p>" in markup


def test_an_item_the_text_names_longer_than_its_picture_is_invented_as_a_whole(tmp_path):
    # Older mails list an item in the text longer, and otherwise, than its picture names it.
    page = _redirect("https://www.amazon.de/dp/B0SCHLEIF1")
    msg = EmailMessage()
    msg["From"] = '"Amazon.de" <versandbestaetigung@amazon.de>'
    msg["Subject"] = "Versendet: „Echtmarke Schleifsch…“"
    msg["Date"] = "Tue, 10 Nov 2026 21:57:25 +0000"
    msg.set_content(f"Bestellnr.\n{ORDER}\n    Echtmarke Schleifscheibe 125 Schleifnetz für Holz\n"
                    "  Menge: 1\n")
    msg.add_alternative(
        f'<p>Bestellnr. {ORDER}</p><a href="{page}"><img src="x.png" '
        'alt="Echtmarke Schleifscheibe 125 mm Klettrücken"></a><p>Menge: 1</p>',
        subtype="html",
    )
    [written] = _results(tmp_path, bytes(msg))
    dump = _dump(written)
    assert "echtmarke" not in dump and "schleifnetz" not in dump and "klettrücken" not in dump
    [name] = _alts(written)
    assert f"\n    {name}\n" in _msg(written).get_body(("plain",)).get_content()

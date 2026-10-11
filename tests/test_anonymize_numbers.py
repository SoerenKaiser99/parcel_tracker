"""Tester mode of the anonymiser: a tracking number always survives as an invented one.

v0.3.15: a submitted DHL mail (newer layout, its text/plain part carries HTML table markup)
had no number left. All mails here are invented.
"""

import email
import re
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

from .test_anonymize_tester import _call

NUMBER = "00340434161094012345"  # invented
GROUPED = "0034 0434 1610 9401 2345"
S10 = "CQ123456785DE"
VALUES = ["--name", "Erika Beispiel", "--postcode", "54321", "--phone", "0151 12345678"]
NOTE = re.compile(r"\[Nummer nur im Link oder Bildtext: ([A-Z0-9]+)\]")
INVENTED = re.compile(r"(?<![A-Za-z0-9])00340\d{15}(?![A-Za-z0-9])")
TRACK_URL = "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html"


def _table(cell: str, href: str = TRACK_URL, image: str = "") -> str:
    """The number block of the newer DHL layout: heading, number cell, button."""
    return (
        '<table border="0" cellpadding="0" width="100%" role="presentation">\n  <tr>\n'
        '    <td align="center" style="font-size:16px;font-weight:700;padding:0 0 4px;">\n'
        "      Ihre Sendungsnummer\n    </td>\n  </tr>\n  <tr>\n"
        f'    <td align="center" style="font-size:14px;line-height:1.3;">\n      {cell}\n'
        "    </td>\n  </tr>\n  <tr>\n    <td>\n"
        f'      <a href="\n\n{href}\n" target="_blank" style="display:block;width:100%;">\n'
        f'        <img src="https://img.dhl.example/track.png" width="58" height="58" {image}>\n'
        f'      </a>\n      <a href="{href}">Sendung verfolgen</a>\n    </td>\n  </tr>\n</table>\n'
    )


def _mail(cell: str = "", href: str = TRACK_URL, image: str = "", html_only: bool = False):
    msg = EmailMessage()
    msg["From"] = "DHL Paketankündigung <paketankuendigung@dhl.de>"
    msg["To"] = "Erika Beispiel <erika@privatpost.example>"
    msg["Subject"] = "Ihre Amazon Sendung ist unterwegs"
    msg["Date"] = "Mon, 05 Oct 2026 02:01:41 +0200"
    table = _table(cell, href, image)
    markup = (
        "<html><head><title>DHL</title></head><body><p>Hallo Erika Beispiel,</p>"
        "<p>Ihre <b>Amazon</b> Sendung ist unterwegs.</p>" + table + "</body></html>"
    )
    if html_only:
        msg.set_content(markup, subtype="html")
    else:
        # DHL's own text part: text with the table markup left in
        msg.set_content("Hallo Erika Beispiel,\nIhre **Amazon** Sendung ist unterwegs\n\n" + table)
        msg.add_alternative(markup, subtype="html")
    return bytes(msg)


def _run(tmp_path: Path, *mails: bytes) -> list[tuple[str, str]]:
    """(text/plain, text/html) of every written mail ('' for a missing part)."""
    src = tmp_path / "mails"
    src.mkdir()
    for i, raw in enumerate(mails):
        (src / f"mail{i}.eml").write_bytes(raw)
    done = _call(src, *VALUES)
    assert done.returncode == 0, done.stderr
    assert NUMBER not in done.stdout + done.stderr
    result = []
    for path in sorted((src / "anonymisiert").glob("*.eml")):
        raw = path.read_bytes()
        assert NUMBER.encode() not in raw and b"piececode" not in raw
        msg = email.message_from_bytes(raw, policy=policy.default)
        parts = {p.get_content_type(): p.get_content() for p in msg.walk() if not p.is_multipart()}
        result.append((parts.get("text/plain", ""), parts.get("text/html", "")))
    return result


def _numbers(text: str) -> list[str]:
    return INVENTED.findall(text)


def test_number_in_a_table_cell_of_the_text_part_survives(tmp_path):
    [(plain, markup)] = _run(tmp_path, _mail(NUMBER))
    [invented] = set(_numbers(plain))
    assert invented != NUMBER
    assert re.search(r"Ihre Sendungsnummer\s*</td>\s*</tr>\s*<tr>\s*<td[^>]*>\s*" + invented, plain)
    assert f"<p>Ihre Sendungsnummer</p>\n<p>{invented}</p>" in markup
    assert not NOTE.search(plain + markup)  # visible: no note needed


@pytest.mark.parametrize("html_only", [False, True])
def test_number_only_in_a_link_is_noted_as_an_invented_number(tmp_path, html_only):
    href = f"{TRACK_URL}?piececode={NUMBER}&zip=54321"
    [(plain, markup)] = _run(tmp_path, _mail(href=href, html_only=html_only))
    for text in filter(None, (plain, markup)):
        [invented] = NOTE.findall(text)  # once, although three links carry it
        assert INVENTED.fullmatch(invented) and invented != NUMBER
        # (the invented number is random digits and may hold "54321" by chance)
        assert "54321" not in text.replace(invented, "")
    if plain:
        assert "https://www.dhl.de/… [Nummer nur" in plain  # the link itself is still cut
    if not html_only:
        assert NOTE.findall(plain) == NOTE.findall(markup)  # the same invented number


def test_number_only_in_an_image_text_is_noted_without_the_text_around_it(tmp_path):
    image = f'alt="Sendung {NUMBER} von Erika Beispiel" title="Paket {NUMBER}"'
    [(plain, markup)] = _run(tmp_path, _mail(image=image, html_only=True))
    assert plain == ""
    [invented] = NOTE.findall(markup)
    assert INVENTED.fullmatch(invented) and invented != NUMBER
    assert "Erika" not in markup and "von Max" not in markup  # only the number is taken


def test_a_number_that_is_visible_gets_no_note_and_one_replacement(tmp_path):
    href = f"{TRACK_URL}?piececode={NUMBER}"
    cell = f'<a href="{href}">{NUMBER}</a>'
    [(plain, markup)] = _run(tmp_path, _mail(cell, href))
    assert not NOTE.search(plain + markup)
    assert len(set(_numbers(plain)) | set(_numbers(markup))) == 1


@pytest.mark.parametrize(
    "cell", [GROUPED, GROUPED.replace(" ", "&nbsp;"), GROUPED.replace(" ", "\xa0")]
)
def test_number_written_in_groups_keeps_its_groups(tmp_path, cell):
    """Digits in groups of four used to become a phone placeholder plus left-over digits."""
    [(plain, markup), (other, _)] = _run(tmp_path, _mail(cell), _mail(NUMBER))
    [same] = set(_numbers(other))
    for text in (plain, markup):
        assert "+49 000" not in text
        [found] = re.findall(r"(?<!\d)\d{4}(?: \d{4}){4}(?!\d)", text)
        # the same number as in the other mail of the run, only written in groups
        assert found.replace(" ", "") == same
        # the replacement is made of random digits and may hold such a group by chance
        rest = text.replace(found, "")
        for group in GROUPED.split()[1:]:
            assert group not in rest, group


def test_international_number_keeps_its_letters(tmp_path):
    [(plain, markup)] = _run(tmp_path, _mail(S10))
    for text in (plain, markup):
        [found] = re.findall(r"(?<![A-Za-z0-9])[A-Z]{2}\d{9}DE(?![A-Za-z0-9])", text)
        assert found != S10 and S10[2:11] not in text


def test_phone_numbers_are_still_replaced_whatever_the_space(tmp_path):
    cell = (
        f"{NUMBER}<br>Fragen: 0211 / 123 45 67, 0151&nbsp;1234&nbsp;5678, "
        "+49\xa0171\xa09876543, Karte 4111 1111 1111 1111"
    )
    [(plain, markup)] = _run(tmp_path, _mail(cell))
    for text in (plain, markup):
        assert text.count("+49 000 0000000") == 3
        [replacement] = set(_numbers(text))
        # the replacement is made of random digits and may hold such a group by chance
        rest = text.replace(replacement, "")
        for secret in ("123 45 67", "1234", "5678", "9876543", "4111", "1111 1111"):
            assert secret not in rest, secret


# ----- v0.3.15 review: numbers in groups with fewer than 16 digits kept original digits -----
def _shape(original: str) -> str:
    """A pattern for the same groups with any digits (a tab may have become a space)."""
    parts = re.split(r"([ \t.-])", original)
    return r"(?<![\d.-])" + "".join(
        "[ \t]" if part in " \t" and len(part) == 1 else re.escape(part) if not part.isalnum()
        else "".join(r"\d" if c.isdigit() else c for c in part)
        for part in parts
    ) + r"(?![\d.-])"


def _replaced(original: str, text: str) -> str:
    """The one invented number of the same shape in ``text``; most digits must differ."""
    [found] = re.findall(_shape(original), text)
    old, new = (re.sub(r"\D", "", value) for value in (original, found))
    assert len(old) == len(new)
    same = sum(a == b for a, b in zip(old, new, strict=True))
    assert same <= 0.7 * len(old), "original digits are left"
    return found


@pytest.mark.parametrize(
    ("lead", "number"),
    [
        ("Paketnummer", "0123 4567 8912 34"),  # 14 digits behind a label
        ("Paketnummer:", "0123 4567 89"),  # 10 digits behind a label
        ("Ihr Paket", "1234 5678 901"),  # 11 digits without a label
        ("Ihr Paket", "9876 5432 1987 65"),  # 14 digits without a label
        ("Ihr Paket", "0987 6543 2198 76"),  # ... also with a leading zero (no phone number)
        ("Ihr Paket", "12345 67890"),
        ("Ihr Paket", "1234 5678 9012 3456 7890 12"),  # 22 digits
        ("Ihr Paket", "0123.4567.8912.34"),
        ("Ihr Paket", "1234.5678.901"),
        ("Ihr Paket", "0123-4567-8912-34"),
        ("Ihr Paket", "0123\t4567\t8912\t34"),
        ("Paketnummer", "1234\t5678\t901"),
        ("Ihr Paket", "1234&nbsp;5678&nbsp;901"),
        ("Ihr Paket", "1234\xa05678\xa0901"),
    ],
)
def test_every_number_in_groups_gets_invented_digits_in_the_same_groups(tmp_path, lead, number):
    plain_number = number.replace("&nbsp;", " ").replace("\xa0", " ")
    [(plain, markup)] = _run(tmp_path, _mail(f"{lead} {number} ist da"))
    for text in (plain, markup):
        _replaced(plain_number, text)
        assert "+49 000" not in text


def test_a_number_in_groups_is_the_same_number_as_without_groups(tmp_path):
    grouped, bare = "9876 5432 1987 65", "98765432198765"
    [(first, _), (second, _)] = _run(
        tmp_path, _mail(f"Ihr Paket {grouped} ist da"), _mail(f"Ihr Paket {bare} ist da")
    )
    [invented] = re.findall(r"Ihr Paket (\d{14}) ist da", second)
    assert _replaced(grouped, first).replace(" ", "") == invented != bare


@pytest.mark.parametrize(
    "number", ["CQ 123 456 785 DE", "CQ123 456 785DE", "CQ.123.456.785.DE", "CQ\t123456785\tDE"]
)
@pytest.mark.parametrize("lead", ["Ihre Sendung", "Sendungsnummer"])
def test_international_number_in_groups_keeps_letters_and_groups(tmp_path, number, lead):
    [(plain, markup), (other, _)] = _run(
        tmp_path, _mail(f"{lead} {number} ist da"), _mail(S10)
    )
    [same] = re.findall(r"(?<![A-Za-z0-9])[A-Z]{2}\d{9}DE(?![A-Za-z0-9])", other)
    for text in (plain, markup):
        found = _replaced(number, text)
        assert re.sub(r"[ \t.]", "", found) == same != S10
        # The invented digits are random: compare the whole number, not single groups
        # (an invented number may contain "456" by chance).
        assert re.sub(r"\D", "", found) != "123456785"


@pytest.mark.parametrize(
    "line",
    [
        "Zustellung am 05.10.2026 zwischen 10:15 und 11:45 Uhr",
        "Zustellung am 05.10.2026 14:30 Uhr, spätestens 07.10.2026 18:00 Uhr",
        "Lieferung 05.10.2026 - 07.10.2026 oder 05.10. - 07.10.",
        "Bestellt am 2026-10-05 um 09:05:17 Uhr",
        "Preis 1.299,00 EUR, 2 x 19,99 EUR, Rabatt 12.50 EUR, Summe 1 338,98 EUR",
        "Regal 12 Fach 345 Karton 6789, Raum 12 34567 frei, 3 Pakete, 250 g",
        "Abholung bis 12.10. 18:00 Uhr in Filiale 512",
    ],
)
def test_dates_times_prices_and_short_numbers_stay(tmp_path, line):
    [(plain, markup)] = _run(tmp_path, _mail(f"{NUMBER}<br>\n{line}<br>\n"))
    for text in (plain, markup):
        assert line in text


@pytest.mark.parametrize(
    "phone",
    ["0151 1234 5678", "0211 123 45 67", "030 1234 5678", "+49 171 9876 5432", "0800-123-4567"],
)
def test_phone_numbers_in_groups_are_still_phone_numbers(tmp_path, phone):
    [(plain, markup)] = _run(tmp_path, _mail(f"{NUMBER}<br>\nHotline {phone} werktags<br>\n"))
    for text in (plain, markup):
        assert "Hotline +49 000 0000000 werktags" in text


def test_address_with_house_number_and_postcode_is_no_number(tmp_path):
    line = "Beispiel Versand, Lagerweg 12, 80331 Hafenstadt"
    [(plain, markup)] = _run(tmp_path, _mail(f"{NUMBER}<br>\n{line}<br>\n"))
    for text in (plain, markup):
        # replaced as an address (or left), never as one long number
        assert not re.search(r"\d{2} \d{5}", text.replace(NUMBER, ""))
        assert "Lagerweg 12, 80331 Hafenstadt" in text or "12345 Musterstadt" in text


# ----- v0.3.15 second review: only the digits of one number count, with one separator -----
@pytest.mark.parametrize(
    "line",
    [
        "Bestellt am 2026-09-28 11:51 Uhr",
        "Abholung 2026-09-28 11:51 bis 2026-09-30 18:00",
        "Liefertermine 2026 2027 2028 2029 geplant",
        "Fächer 10 20 30 40 50 60 belegt",
        "Größen 36 38 40 42 44 46 48 lieferbar",
        "Am 28.09.2026 11:51 Uhr 12 Stück, 3 Kartons",
        "Maße 120 80 60 cm, Gewicht 12 500 g",
    ],
)
def test_dates_years_and_rows_of_small_numbers_are_no_number_in_groups(tmp_path, line):
    [(plain, markup)] = _run(tmp_path, _mail(f"{NUMBER}<br>\n{line}<br>\n"))
    for text in (plain, markup):
        assert line in text


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("Ihr Paket {} kommt am 2026-09-28 11:51 Uhr", "9876 5432 1987 65"),
        ("Am 2026-09-28 11:51 kam Ihr Paket {} an", "1234 5678 901"),
        ("Seit 2026 kam kein Paket wie {} bis 2027 an", "1234.5678.901"),
        ("Ihr Paket {} in Fach 10 20 30", "0034 0434 1610 9401 2345"),
        ("Ihr Paket {} ist da", "2026 0434 1610 2027"),  # not only years
        ("Ihr Paket {} ist da", "12 345 67 890 12"),  # not only pairs
        ("Sendungsnummer: {} ist da", "12 34 56 78 90 12"),  # behind its label also pairs
    ],
)
def test_real_numbers_in_groups_next_to_dates_are_still_replaced(tmp_path, line, number):
    [(plain, markup)] = _run(tmp_path, _mail(line.format(number) + "<br>\n"))
    for text in (plain, markup):
        _replaced(number, text)
        for part in line.split("{}"):
            assert part.strip() in text

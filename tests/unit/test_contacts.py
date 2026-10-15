"""The contact book: phone numbers, names and aliases, matching, and vCard import."""

from __future__ import annotations

import pytest

from jarvis.config import ContactsSettings
from jarvis.storage.db import Database
from jarvis.tools.messaging.contacts import (
    ContactBook,
    ContactError,
    key,
    normalize_phone,
    parse_vcards,
)


@pytest.fixture
def book() -> ContactBook:
    return ContactBook(Database(":memory:"), ContactsSettings(default_country_code="91"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+91 98765 43210", "+919876543210"),
        ("98765-43210", "+919876543210"),
        ("098765 43210", "+919876543210"),
        ("0044 20 7946 0958", "+442079460958"),
        ("919876543210", "+919876543210"),
        ("+1 (555) 010-2030", "+15550102030"),
    ],
)
def test_numbers_become_e164(raw: str, expected: str) -> None:
    assert normalize_phone(raw, "91") == expected


def test_a_number_without_country_code_needs_the_setting() -> None:
    with pytest.raises(ContactError, match="country code"):
        normalize_phone("98765 43210", "")
    with pytest.raises(ContactError, match="does not look like"):
        normalize_phone("12", "91")


def test_key_ignores_case_spacing_and_my() -> None:
    assert key("  My   MOM ") == key("mom") == "mom"
    assert key("the boss on whatsapp") == "boss"


def test_add_find_and_remove(book: ContactBook) -> None:
    amma = book.add("Amma", "98765 43210", ["Mom", "Mummy"])
    assert amma.phone == "+919876543210"
    assert amma.aliases == ("Mom", "Mummy")
    assert book.find("my mom") == [amma]
    assert book.find("Amma") == [amma]
    assert book.find("ama") == [amma]  # a small speech recognition slip
    assert book.find("Ravi") == []
    book.remove("amma")
    assert book.all() == []


def test_names_are_unique_and_need_a_valid_number(book: ContactBook) -> None:
    book.add("Ravi Kumar", "+91 90000 00001")
    with pytest.raises(ContactError, match="already"):
        book.add("ravi  kumar", "+91 90000 00002")
    with pytest.raises(ContactError):
        book.add("Nobody", "123")
    with pytest.raises(ContactError, match="no contact"):
        book.remove("Nobody")


def test_a_shared_first_name_or_alias_returns_every_match(book: ContactBook) -> None:
    kumar = book.add("Ravi Kumar", "+91 90000 00001")
    teja = book.add("Ravi Teja", "+91 90000 00002", ["Ravi"])
    book.add("Priya", "+91 90000 00003")
    assert book.find("Ravi") == [teja]  # an exact alias wins over first names
    book.add_alias("Ravi Kumar", "Ravi")
    assert {c.name for c in book.find("Ravi")} == {kumar.name, teja.name}


def test_first_names_match_when_unique(book: ContactBook) -> None:
    priya = book.add("Priya Sharma", "+91 90000 00003")
    assert book.find("Priya") == [priya]


def test_aliases_can_be_removed(book: ContactBook) -> None:
    book.add("Amma", "+91 98765 43210", ["Mom"])
    assert book.remove_alias("Amma", "mom").aliases == ()
    assert book.find("mom") == []


VCF = """BEGIN:VCARD
VERSION:3.0
FN:Ravi Kumar
N:Kumar;Ravi;;;
TEL;TYPE=HOME:040 2345 6789
TEL;TYPE=CELL:+91 90000 00001
NICKNAME:Ravi,RK
END:VCARD
BEGIN:VCARD
VERSION:2.1
N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:;=E0=A4=85=E0=A4=AE=E0=A5=8D=E0=A4=AE=E0=A4=BE;;;
FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=E0=A4=85=E0=A4=AE=E0=A5=8D=E0=A4=AE=E0=A4=BE
TEL;CELL:98765 43210
END:VCARD
BEGIN:VCARD
VERSION:4.0
N:Sharma;Priya;;;
item1.TEL;type=pref:tel:+91-90000-00003
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Pizza Place
EMAIL:order@example.com
END:VCARD
"""


def test_vcards_are_parsed_with_mobile_numbers_first() -> None:
    cards = parse_vcards(VCF.replace("\n", "\r\n"))
    assert [c.name for c in cards] == ["Ravi Kumar", "अम्मा", "Priya Sharma", "Pizza Place"]
    assert cards[0].phones == ["+91 90000 00001", "040 2345 6789"]
    assert cards[0].nicknames == ["Ravi", "RK"]
    assert cards[2].phones == ["+91-90000-00003"]
    assert cards[3].phones == []


def test_folded_vcard_lines_are_joined() -> None:
    cards = parse_vcards("BEGIN:VCARD\nFN:Ravi\n  Kumar\nTEL:+919000000001\nEND:VCARD\n")
    assert cards[0].name == "Ravi Kumar"


def test_import_adds_what_it_can_and_says_why_it_skipped_the_rest(book: ContactBook) -> None:
    book.add("Priya Sharma", "+91 90000 00003")
    result = book.import_vcard(VCF)
    assert result.added == ["Ravi Kumar", "अम्मा"]
    assert result.skipped == [
        "Priya Sharma: There is already a contact called 'Priya Sharma'.",
        "Pizza Place: no phone number",
    ]
    assert book.find("RK")[0].name == "Ravi Kumar"

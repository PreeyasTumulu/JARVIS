"""The contact book: people you message, with spoken aliases ("Mom", "Amma"), stored locally.

Contacts never come from the model. You add them with `jarvis contacts add`, the Contacts tab of
the web page, or a .vcf file exported from your phone. An alias may point at several people on
purpose ("Ravi"); send_whatsapp then asks which one you mean before anything is confirmed.
"""

from __future__ import annotations

import quopri
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from rapidfuzz import fuzz

from jarvis.config import ContactsSettings
from jarvis.storage.db import Database

MIN_DIGITS = 8
MAX_DIGITS = 15  # E.164
NATIONAL_DIGITS = 10  # longer numbers without a + are taken to include their country code
TIE_POINTS = 5
_FILLER = re.compile(r"^(my|our|the)\s+|\s+(on whatsapp|please)$")


class ContactError(ValueError):
    """A contact could not be added or changed. The message is meant for the user."""


@dataclass(frozen=True)
class Contact:
    id: int
    name: str
    phone: str  # E.164, for example +919876543210
    aliases: tuple[str, ...] = ()
    notes: str = ""

    @property
    def last_digits(self) -> str:
        return self.phone[-4:]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "aliases": list(self.aliases),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ImportResult:
    added: list[str]
    skipped: list[str]  # "Name: why"


def key(text: str) -> str:
    """How names and aliases are compared: lowercase, single spaces, no leading "my"."""
    flat = " ".join(re.sub(r"[^\w\s'.-]", " ", text.casefold()).split())
    return _FILLER.sub("", flat).strip()


def normalize_phone(raw: str, default_country_code: str = "") -> str:
    """A phone number in E.164 form (+919876543210). Raises ContactError if it cannot be one."""
    text = raw.strip()
    if text.startswith("00"):
        text = "+" + text[2:]
    digits = re.sub(r"\D", "", text)
    if not text.startswith("+"):
        digits = digits.lstrip("0")
        if len(digits) <= NATIONAL_DIGITS:
            if not default_country_code:
                raise ContactError(
                    f"'{raw}' has no country code. Write it like +91 98765 43210, or set "
                    "[contacts] default_country_code in config/local.toml."
                )
            digits = default_country_code + digits
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        raise ContactError(f"'{raw}' does not look like a phone number.")
    return "+" + digits


class ContactBook:
    def __init__(self, db: Database, settings: ContactsSettings) -> None:
        self._db = db
        self._settings = settings

    def all(self) -> list[Contact]:
        rows = self._db.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE")
        aliases: dict[int, list[str]] = {}
        for row in self._db.execute("SELECT contact_id, alias FROM contact_aliases ORDER BY alias"):
            aliases.setdefault(row["contact_id"], []).append(row["alias"])
        return [
            Contact(r["id"], r["name"], r["phone"], tuple(aliases.get(r["id"], [])), r["notes"])
            for r in rows
        ]

    def get(self, contact_id: int) -> Contact | None:
        return next((c for c in self.all() if c.id == contact_id), None)

    def named(self, name: str) -> Contact:
        """The contact with exactly this name (or id). Raises ContactError."""
        wanted = key(name)
        for contact in self.all():
            if key(contact.name) == wanted or str(contact.id) == name.strip():
                return contact
        raise ContactError(f"There is no contact called '{name}'.")

    def add(
        self, name: str, phone: str, aliases: list[str] | None = None, notes: str = ""
    ) -> Contact:
        name = " ".join(name.split())
        if not key(name):
            raise ContactError("A contact needs a name.")
        number = normalize_phone(phone, self._settings.default_country_code)
        if any(key(c.name) == key(name) for c in self.all()):
            raise ContactError(f"There is already a contact called '{name}'.")
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO contacts (name, name_key, phone, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, key(name), number, notes.strip(), datetime.now(UTC).isoformat()),
            )
            contact_id = int(cursor.lastrowid or 0)
            for alias in aliases or []:
                self._insert_alias(conn, contact_id, alias)
        found = self.get(contact_id)
        assert found is not None
        return found

    def add_alias(self, name: str, alias: str) -> Contact:
        contact = self.named(name)
        with self._db.transaction() as conn:
            self._insert_alias(conn, contact.id, alias)
        return self.named(contact.name)

    def remove_alias(self, name: str, alias: str) -> Contact:
        contact = self.named(name)
        self._db.execute(
            "DELETE FROM contact_aliases WHERE contact_id = ? AND alias_key = ?",
            (contact.id, key(alias)),
        )
        return self.named(contact.name)

    def remove(self, name: str) -> Contact:
        contact = self.named(name)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM contact_aliases WHERE contact_id = ?", (contact.id,))
            conn.execute("DELETE FROM contacts WHERE id = ?", (contact.id,))
        return contact

    def find(self, spoken: str) -> list[Contact]:
        """Contacts the words could mean, best first. More than one means ask which."""
        wanted = key(spoken)
        if not wanted:
            return []
        contacts = self.all()
        exact = [
            c for c in contacts if key(c.name) == wanted or wanted in {key(a) for a in c.aliases}
        ]
        if exact:
            return exact
        scored = sorted(((self._score(wanted, c), c) for c in contacts), key=lambda pair: -pair[0])
        close = [(s, c) for s, c in scored if s >= self._settings.match_threshold]
        if not close:
            return []
        best = close[0][0]
        return [c for s, c in close if best - s <= TIE_POINTS]

    def import_vcard(self, text: str) -> ImportResult:
        added: list[str] = []
        skipped: list[str] = []
        for card in parse_vcards(text):
            name = card.name or "(no name)"
            if not card.phones:
                skipped.append(f"{name}: no phone number")
                continue
            try:
                contact = self.add(card.name, card.phones[0], aliases=card.nicknames)
            except ContactError as exc:
                skipped.append(f"{name}: {exc}")
                continue
            added.append(contact.name)
        return ImportResult(added, skipped)

    def _insert_alias(self, conn: sqlite3.Connection, contact_id: int, alias: str) -> None:
        alias = " ".join(alias.split())
        if not key(alias):
            raise ContactError("An alias cannot be empty.")
        conn.execute(
            "INSERT OR IGNORE INTO contact_aliases (alias_key, alias, contact_id) VALUES (?, ?, ?)",
            (key(alias), alias, contact_id),
        )

    @staticmethod
    def _score(wanted: str, contact: Contact) -> float:
        names = [key(contact.name), *(key(a) for a in contact.aliases)]
        first = key(contact.name).split()[0] if key(contact.name) else ""
        scores = [fuzz.ratio(wanted, name) for name in names]
        if first:
            scores.append(fuzz.ratio(wanted, first))  # "Ravi" for "Ravi Kumar"
        return max(scores, default=0.0)


@dataclass
class VCard:
    name: str = ""
    phones: list[str] | None = None
    nicknames: list[str] | None = None


def parse_vcards(text: str) -> list[VCard]:
    """Contacts from a .vcf export (vCard 2.1, 3.0, or 4.0). Mobile numbers come first."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]  # folded line
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw  # quoted-printable soft line break
        else:
            lines.append(raw)
    cards: list[VCard] = []
    card: VCard | None = None
    mobiles: list[str] = []
    others: list[str] = []
    structured = ""
    for line in lines:
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        params = head.split(";")
        prop = params[0].split(".")[-1].upper()  # "item1.TEL" is TEL
        upper = head.upper()
        if prop == "BEGIN" and value.strip().upper() == "VCARD":
            card, mobiles, others, structured = VCard(nicknames=[]), [], [], ""
            continue
        if card is None:
            continue
        if "QUOTED-PRINTABLE" in upper:
            value = quopri.decodestring(value.encode("latin-1")).decode("utf-8", "replace")
        value = value.strip()
        if prop == "END":
            card.name = card.name or structured
            card.phones = mobiles + others
            cards.append(card)
            card = None
        elif prop == "FN":
            card.name = value.replace("\\,", ",")
        elif prop == "N" and value:
            parts = [part.strip() for part in value.split(";")]
            structured = " ".join(p for p in (parts[1:2] + parts[0:1]) if p)
        elif prop == "TEL" and value:
            (mobiles if "CELL" in upper or "MOBILE" in upper else others).append(
                value.removeprefix("tel:")
            )
        elif prop == "NICKNAME" and value and card.nicknames is not None:
            card.nicknames.extend(n.strip() for n in value.split(",") if n.strip())
    return cards

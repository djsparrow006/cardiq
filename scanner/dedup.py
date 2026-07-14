"""
Dedup — before inserting a newly scanned contact, check if it's actually a
re-scan of someone already in the shared pool. Multi-user matters here: two
different team members may scan the same card at the same event.

Uses simple, dependency-free fuzzy string matching (difflib) on name +
company/email — good enough for this scale, no extra service needed.
"""
from difflib import SequenceMatcher

from sqlalchemy.orm import Session
from db.models import Contact
from config import DEDUP_THRESHOLD


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_existing_contact(db: Session, fields: dict) -> Contact | None:
    """Returns the best-matching existing Contact if one clears the dedup
    threshold, else None (meaning: treat this as a new contact)."""
    name = fields.get("name") or ""
    # Business cards have company/email; college IDs have roll_no instead —
    # use whichever secondary identifier is present.
    secondary = fields.get("company") or fields.get("email") or fields.get("roll_no") or ""

    if not name:
        return None  # can't dedup without at least a name

    candidates = db.query(Contact).filter(Contact.name.isnot(None)).all()

    best_match, best_score = None, 0.0
    for c in candidates:
        name_score = _similarity(name, c.name or "")
        secondary_score = _similarity(secondary, c.company or c.email or "")
        # Weight name higher, but require some secondary agreement too —
        # avoids merging two different "John Smith"s from different companies.
        combined = (name_score * 0.7) + (secondary_score * 0.3)
        if combined > best_score:
            best_match, best_score = c, combined

    if best_score >= DEDUP_THRESHOLD:
        return best_match
    return None

"""
Applies a parsed question filter against the contacts table. Never guesses
when nothing matches — same grounding principle as the e-commerce chatbot's
guardrails: say "no matches" plainly rather than inventing a plausible one.
"""
from sqlalchemy.orm import Session
from db.models import Contact


def retrieve_contacts(db: Session, category_filter: str | None, entity_name: str | None) -> list[Contact]:
    q = db.query(Contact)
    if category_filter:
        q = q.filter(Contact.category == category_filter)
    if entity_name:
        like = f"%{entity_name}%"
        q = q.filter((Contact.name.ilike(like)) | (Contact.company.ilike(like)))
    return q.order_by(Contact.last_updated_at.desc()).all()


def format_answer(contacts: list[Contact], requested_field: str) -> dict:
    """Returns {"answer": str, "matches": [...]} — answer is a plain-language
    reply, matches is the raw data so the UI can also render a table."""
    if not contacts:
        return {"answer": "No matching contacts found.", "matches": []}

    matches = [
        {"id": c.id, "name": c.name, "company": c.company,
         "phone": c.phone, "email": c.email, "category": c.category}
        for c in contacts
    ]

    if len(contacts) == 1:
        c = contacts[0]
        if requested_field == "email":
            value = c.email or "no email on file"
        elif requested_field == "phone":
            value = c.phone or "no phone on file"
        elif requested_field == "company":
            value = c.company or "no company on file"
        elif requested_field == "name":
            value = c.name or "unknown"
        else:
            value = f"{c.name} — {c.company} — {c.phone} — {c.email}"
        answer = f"{c.name} ({c.company or 'no company listed'}): {value}"
    else:
        names = ", ".join(c.name or "unknown" for c in contacts[:10])
        answer = f"Found {len(contacts)} matching contacts: {names}" + \
                  (" (showing first 10)" if len(contacts) > 10 else "") + \
                  " — which one did you mean?"

    return {"answer": answer, "matches": matches}

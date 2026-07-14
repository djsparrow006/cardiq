"""
Parses a natural-language question ("give me the mail of the company
related to college") into a structured filter the retrieval layer can run
directly against the contacts table. Same pattern as query_processing.py
in the e-commerce project — reused here for contacts instead of docs.
"""
import json
import re

from groq import Groq
from config import GROQ_API_KEY, TEXT_MODEL, CATEGORIES

groq_client = Groq(api_key=GROQ_API_KEY)

_SYSTEM = f"""You are a query-understanding module for a contact database.
Given a user's question, return ONLY a JSON object (no prose, no markdown fences):

{{
  "requested_field": "<one of: email, phone, name, company, all>",
  "category_filter": "<one of: {", ".join(CATEGORIES)}, or null if not specified>",
  "entity_name": "<a specific person or company name mentioned, or null>"
}}

Examples:
"give me the mail of the company related to college" ->
  {{"requested_field": "email", "category_filter": "education", "entity_name": null}}
"what's Ravi's phone number" ->
  {{"requested_field": "phone", "category_filter": null, "entity_name": "Ravi"}}
"show me all vendor contacts" ->
  {{"requested_field": "all", "category_filter": "vendor", "entity_name": null}}
"""


def _fallback(raw: str) -> dict:
    return {"requested_field": "all", "category_filter": None, "entity_name": None,
            "parse_failed": True}


def parse_question(question: str) -> dict:
    try:
        completion = groq_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=150,
        )
        raw = completion.choices[0].message.content or ""
        cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        parsed.setdefault("requested_field", "all")
        parsed.setdefault("category_filter", None)
        parsed.setdefault("entity_name", None)
        parsed["parse_failed"] = False
        return parsed
    except Exception as e:
        print(f"[intent_parser] classification failed: {e!r}")
        return _fallback(question)

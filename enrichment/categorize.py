"""
Categorize a contact into one of CATEGORIES based on extracted fields —
this is what makes "give me the education-related contact's email"
answerable later: the category has to exist as stored data, not be
re-inferred fresh on every query.
"""
import json
import re

from groq import Groq
from config import GROQ_API_KEY, TEXT_MODEL, CATEGORIES

groq_client = Groq(api_key=GROQ_API_KEY)

_SYSTEM = f"""Classify a scanned contact into exactly one category: {", ".join(CATEGORIES)}.

Rules:
- "education" = universities, colleges, schools, research institutes, student/faculty contacts.
- "vendor" = suppliers, service providers, contractors.
- "business" = general corporate/company contacts not covered above.
- "other" = anything unclear or that doesn't fit.

Respond with ONLY a JSON object, no prose: {{"category": "..."}}
"""


def categorize_contact(fields: dict, doc_type: str) -> str:
    context = f"Document type: {doc_type}\nFields: {json.dumps(fields)}"

    try:
        completion = groq_client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": context},
            ],
            temperature=0,
            max_tokens=50,
        )
        raw = completion.choices[0].message.content or ""
        cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        category = parsed.get("category", "other")
        return category if category in CATEGORIES else "other"
    except Exception as e:
        print(f"[categorize] failed: {e!r}")
        # college_id doc_type is a strong deterministic signal even if the
        # LLM call fails — fail toward a reasonable default, not "other" blindly
        return "education" if doc_type == "college_id" else "other"

"""
Vision extraction — sends a captured frame to Groq's vision model and gets
back structured fields. Model choice matters here: llama-3.2-11b-vision and
llama-4-maverick are both deprecated on Groq as of this writing. Using the
current supported vision model instead. If this one gets deprecated later,
check https://console.groq.com/docs/vision for the current recommendation.
"""
import base64
import json
import re

from groq import Groq
from config import GROQ_API_KEY, VISION_MODEL

groq_client = Groq(api_key=GROQ_API_KEY)

FIELD_SCHEMAS = {
    "visiting_card": ["name", "company", "phone", "email"],
    "college_id": ["name", "roll_no", "department", "valid_till"],
}

_PROMPTS = {
    "visiting_card": (
        "This image is a business/visiting card. Extract exactly these fields: "
        "name, company, phone, email. "
        "If a field is not visible or not present, use null — never guess or invent a value. "
        "Respond with ONLY a JSON object, no prose, no markdown fences: "
        '{"name": ..., "company": ..., "phone": ..., "email": ...}'
    ),
    "college_id": (
        "This image is a college/university ID card. Extract exactly these fields: "
        "name, roll_no, department, valid_till. "
        "If a field is not visible or not present, use null — never guess or invent a value. "
        "Respond with ONLY a JSON object, no prose, no markdown fences: "
        '{"name": ..., "roll_no": ..., "department": ..., "valid_till": ...}'
    ),
}


def _strip_json_fences(raw: str) -> str:
    return re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def extract_fields(image_bytes: bytes, doc_type: str) -> dict:
    """Returns {"fields": {...}, "raw_text": "<model's literal reply>", "confidence": "high"/"low"}."""
    if doc_type not in FIELD_SCHEMAS:
        raise ValueError(f"Unknown doc_type: {doc_type!r}")

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    completion = groq_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPTS[doc_type]},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64_image}"
                    }},
                ],
            }
        ],
        temperature=0,
        max_tokens=300,
    )

    raw_out = completion.choices[0].message.content or ""
    cleaned = _strip_json_fences(raw_out)

    expected_fields = FIELD_SCHEMAS[doc_type]
    try:
        parsed = json.loads(cleaned)
        fields = {k: parsed.get(k) or None for k in expected_fields}
    except (json.JSONDecodeError, AttributeError):
        fields = {k: None for k in expected_fields}

    filled = sum(1 for v in fields.values() if v)
    confidence = "high" if filled >= len(expected_fields) - 1 else "low"

    return {"fields": fields, "raw_text": raw_out, "confidence": confidence}


def extract_fields_multi(image_bytes_list: list, doc_type: str) -> dict:
    """Same as extract_fields, but accepts a LIST of one or more images.
    Some cards have every field on a single face — one image is enough —
    but others split details across a second photo (e.g. back side, or a
    second card/note). Each image is extracted independently with
    extract_fields, then merged: fields from the first image take
    priority, and any field still null gets filled from later images in
    order. Existing single-image callers (extract_fields) are completely
    unaffected — this is purely additive.
    """
    if not image_bytes_list:
        raise ValueError("extract_fields_multi requires at least one image")

    per_image_results = [extract_fields(img, doc_type) for img in image_bytes_list]

    expected_fields = FIELD_SCHEMAS[doc_type]
    merged_fields = {k: None for k in expected_fields}
    for result in per_image_results:
        for k in expected_fields:
            if not merged_fields[k] and result["fields"].get(k):
                merged_fields[k] = result["fields"][k]

    combined_raw_text = "\n---\n".join(r["raw_text"] for r in per_image_results)

    filled = sum(1 for v in merged_fields.values() if v)
    confidence = "high" if filled >= len(expected_fields) - 1 else "low"

    return {"fields": merged_fields, "raw_text": combined_raw_text, "confidence": confidence}

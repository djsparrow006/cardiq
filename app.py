"""
CardIQ — Smart Contact Intelligence from Scanned Cards
Run:  python app.py
Open: http://localhost:5001

First run: no users exist yet, so a default admin account is auto-created
(username: admin / password: changeme123 — printed to console on startup).
Log in as admin, change that password, then create real team accounts from
the Admin page. Only admins can create accounts; everyone has equal access
otherwise.
"""
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from flask_cors import CORS
from flask_login import (
    login_user, logout_user, login_required, current_user,
)
import pandas as pd

from db import init_db
from db.session import SessionLocal
from db.models import Contact, ContactTag, ScanEvent, User

from auth import login_manager, verify_password, create_user, bootstrap_first_admin_if_needed
from scanner.vision_extract import extract_fields, extract_fields_multi
from scanner.dedup import find_existing_contact
from enrichment.categorize import categorize_contact
from query.intent_parser import parse_question
from query.retrieval import retrieve_contacts, format_answer

import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
CORS(app, supports_credentials=True)

login_manager.init_app(app)

init_db()

_bootstrap_db = SessionLocal()
bootstrap_first_admin_if_needed(_bootstrap_db)
_bootstrap_db.close()


# ── Auth pages ───────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    name = (request.form.get("name") or "").strip()
    password = request.form.get("password") or ""

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == name).first()
        if not user or not verify_password(user, password):
            return render_template("login.html", error="Invalid username or password.")
        login_user(user)
        return redirect(url_for("index"))
    finally:
        db.close()


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET"])
@login_required
def admin_page():
    if not current_user.is_admin():
        return "Admins only.", 403
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.name).all()
        return render_template("admin.html", users=users)
    finally:
        db.close()


@app.route("/admin/create-user", methods=["POST"])
@login_required
def admin_create_user():
    if not current_user.is_admin():
        return jsonify({"success": False, "error": "Admins only"}), 403

    name = (request.form.get("name") or "").strip()
    password = request.form.get("password") or ""
    role = request.form.get("role") or "member"

    if not name or not password:
        return redirect(url_for("admin_page"))

    db = SessionLocal()
    try:
        if db.query(User).filter(User.name == name).first():
            return redirect(url_for("admin_page"))  # name taken, silently skip for now
        create_user(db, name=name, password=password, role=role if role == "admin" else "member")
        return redirect(url_for("admin_page"))
    finally:
        db.close()


# ── Pages (all require login) ───────────────────────────────────────────
@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/")
@login_required
def index():
    return render_template("scan.html")


@app.route("/contacts")
@login_required
def contacts_page():
    return render_template("contacts.html")


@app.route("/ask")
@login_required
def ask_page():
    return render_template("ask.html")


# ── Scan ────────────────────────────────────────────────────────────────

@app.route("/scan-frame", methods=["POST"])
@login_required
def scan_frame():
    """PREVIEW ONLY — extracts fields but does NOT save to the DB. The user
    reviews/edits the extracted fields in the UI, then calls /scan-confirm
    to actually persist. This exists specifically so a bad OCR/vision read
    doesn't silently corrupt the shared team contact pool — the person who
    scanned it gets a chance to catch and fix mistakes first."""
    doc_type = request.form.get("doc_type", "visiting_card")
    frame = request.files.get("frame")
    frame2 = request.files.get("frame2")  # optional — for cards needing a second photo

    if doc_type not in ("visiting_card", "college_id"):
        return jsonify({"success": False, "error": "Invalid doc_type"}), 400
    if not frame:
        return jsonify({"success": False, "error": "No frame provided"}), 400

    try:
        image_bytes = frame.read()
        if frame2:
            # Two-photo path: merge fields from both images. Existing
            # single-photo behavior below is untouched.
            image_bytes_2 = frame2.read()
            result = extract_fields_multi([image_bytes, image_bytes_2], doc_type)
        else:
            result = extract_fields(image_bytes, doc_type)
        return jsonify({
            "success": True,
            "fields": result["fields"],
            "confidence": result["confidence"],
            "raw_text": result["raw_text"],
            "doc_type": doc_type,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/scan-confirm", methods=["POST"])
@login_required
def scan_confirm():
    """Actually saves a (possibly user-edited) set of extracted fields to
    the DB — dedup + categorize + insert/update, same logic /scan-frame
    used to do directly. Called only after the user reviews and confirms."""
    payload = request.json or {}
    doc_type = payload.get("doc_type", "visiting_card")
    fields = payload.get("fields", {})
    raw_text = payload.get("raw_text", "")
    confidence = payload.get("confidence", "low")
    scanned_by = current_user.id  # server-derived, never trust the client

    if doc_type not in ("visiting_card", "college_id"):
        return jsonify({"success": False, "error": "Invalid doc_type"}), 400
    if not fields.get("name"):
        return jsonify({"success": False, "error": "Name is required to save a contact"}), 400

    db = SessionLocal()
    try:
        existing = find_existing_contact(db, fields)

        if existing:
            for k, v in fields.items():
                if v and hasattr(existing, k) and not getattr(existing, k):
                    setattr(existing, k, v)
            contact = existing
            matched_existing = True
        else:
            category = categorize_contact(fields, doc_type)
            contact = Contact(
                name=fields.get("name"),
                company=fields.get("company"),
                phone=fields.get("phone"),
                email=fields.get("email"),
                category=category,
                source_doc_type=doc_type,
                scanned_by=scanned_by,
            )
            db.add(contact)
            db.flush()
            db.add(ContactTag(contact_id=contact.id, tag=category))
            matched_existing = False

        db.add(ScanEvent(
            contact_id=contact.id,
            scanned_by=scanned_by,
            doc_type=doc_type,
            confidence=confidence,
            matched_existing=matched_existing,
            raw_ocr_text=raw_text,
        ))
        db.commit()
        db.refresh(contact)

        return jsonify({
            "success": True,
            "category": contact.category,
            "matched_existing": matched_existing,
            "contact_id": contact.id,
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# ── Contacts list/filter ───────────────────────────────────────────────────

@app.route("/api/contacts", methods=["GET"])
@login_required
def api_contacts():
    category = request.args.get("category")
    db = SessionLocal()
    try:
        q = db.query(Contact)
        if category:
            q = q.filter(Contact.category == category)
        contacts = q.order_by(Contact.last_updated_at.desc()).all()
        return jsonify([
            {"id": c.id, "name": c.name, "company": c.company, "phone": c.phone,
             "email": c.email, "category": c.category, "source_doc_type": c.source_doc_type,
             "first_scanned_at": c.first_scanned_at.isoformat() if c.first_scanned_at else None}
            for c in contacts
        ])
    finally:
        db.close()


@app.route("/api/contacts/export.xlsx", methods=["GET"])
@login_required
def api_contacts_export():
    category = request.args.get("category")
    db = SessionLocal()
    try:
        q = db.query(Contact)
        if category:
            q = q.filter(Contact.category == category)
        contacts = q.order_by(Contact.last_updated_at.desc()).all()

        rows = [
            {"Name": c.name, "Company": c.company, "Email": c.email, "Phone": c.phone,
             "Category": c.category, "Source": c.source_doc_type,
             "First Scanned": c.first_scanned_at.isoformat() if c.first_scanned_at else None}
            for c in contacts
        ]
        df = pd.DataFrame(rows)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Contacts")
            ws = writer.sheets["Contacts"]
            for col_cells in ws.columns:
                length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col_cells)
                ws.column_dimensions[col_cells[0].column_letter].width = min(length + 2, 40)
        buffer.seek(0)

        filename = f"cardiq_contacts{'_' + category if category else ''}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    finally:
        db.close()


@app.route("/api/contacts/<int:contact_id>", methods=["DELETE"])
@login_required
def api_delete_contact(contact_id):
    if not current_user.is_admin():
        return jsonify({"success": False, "error": "Admins only"}), 403

    db = SessionLocal()
    try:
        contact = db.query(Contact).get(contact_id)
        if not contact:
            return jsonify({"success": False, "error": "Contact not found"}), 404
        # Clean up dependent rows first — no ON DELETE CASCADE configured
        db.query(ContactTag).filter(ContactTag.contact_id == contact_id).delete()
        db.query(ScanEvent).filter(ScanEvent.contact_id == contact_id).delete()
        db.delete(contact)
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# ── Natural-language ask ────────────────────────────────────────────────

@app.route("/api/ask", methods=["POST"])
@login_required
def api_ask():
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify({"success": False, "error": "Question required"}), 400

    db = SessionLocal()
    try:
        parsed = parse_question(question)
        contacts = retrieve_contacts(db, parsed.get("category_filter"), parsed.get("entity_name"))
        result = format_answer(contacts, parsed.get("requested_field", "all"))
        return jsonify({"success": True, "parsed": parsed, **result})
    finally:
        db.close()


if __name__ == "__main__":
    app.run(debug=True, port=5001)

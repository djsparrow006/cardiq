from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base
from flask_login import UserMixin

Base = declarative_base()


class User(Base, UserMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="member")   # "admin" or "member" — equal access otherwise,
                                                 # admin just gets account-creation rights
    created_at = Column(DateTime, default=datetime.utcnow)

    def is_admin(self) -> bool:
        return self.role == "admin"


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    company = Column(String, index=True)
    phone = Column(String)
    email = Column(String, index=True)
    category = Column(String, index=True)          # education / business / vendor / other
    source_doc_type = Column(String)                # visiting_card / college_id
    scanned_by = Column(Integer, ForeignKey("users.id"))
    first_scanned_at = Column(DateTime, default=datetime.utcnow)
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text)


class ContactTag(Base):
    __tablename__ = "contact_tags"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    tag = Column(String, index=True)


class ScanEvent(Base):
    __tablename__ = "scan_events"
    id = Column(Integer, primary_key=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    scanned_by = Column(Integer, ForeignKey("users.id"))
    doc_type = Column(String)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    confidence = Column(String)          # high / low
    matched_existing = Column(Boolean, default=False)
    raw_ocr_text = Column(Text)          # audit trail — the model's literal raw reply

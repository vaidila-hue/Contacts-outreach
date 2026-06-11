"""PDF text extraction and contact discovery."""

from __future__ import annotations

import io

import pdfplumber

from src.extract_contacts import (
    ContactCandidate,
    extract_contacts_from_text,
    select_best_contact,
)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:20]:
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(text)
    except Exception:
        return ""
    return "\n".join(parts)


def extract_contacts_from_pdf(pdf_bytes: bytes, source_url: str) -> list[ContactCandidate]:
    text = extract_text_from_pdf(pdf_bytes)
    if not text or len(text) < 50:
        return []
    return extract_contacts_from_text(text, source_url)


def best_contact_from_pdf(pdf_bytes: bytes, source_url: str):
    candidates = extract_contacts_from_pdf(pdf_bytes, source_url)
    return select_best_contact(candidates)

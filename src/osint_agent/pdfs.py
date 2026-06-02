from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import requests
from pypdf import PdfReader

from .memory import OsintMemory


@dataclass(slots=True)
class PdfDocument:
    source: str
    text: str
    page_count: int


def _load_pdf_bytes(source: str) -> bytes:
    path = Path(source)
    if path.exists():
        return path.read_bytes()

    response = requests.get(source, timeout=60)
    response.raise_for_status()
    return response.content


def extract_pdf_text(source: str, memory: OsintMemory | None = None) -> PdfDocument:
    if memory is not None:
        cached = memory.get_pdf_cache(source)
        if cached is not None:
            return PdfDocument(source=cached.source, text=cached.text, page_count=cached.page_count)

    pdf_bytes = _load_pdf_bytes(source)
    reader = PdfReader(BytesIO(pdf_bytes))

    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        cleaned = text.strip()
        if cleaned:
            pages.append(cleaned)

    return PdfDocument(
        source=source,
        text="\n\n".join(pages),
        page_count=len(reader.pages),
    )


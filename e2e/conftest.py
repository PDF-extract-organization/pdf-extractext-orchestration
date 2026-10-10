"""Configuración de las pruebas de extremo a extremo.

Todas entran por Traefik, nunca por el puerto de un servicio: se conectan a
TRAEFIK_URL (por defecto http://localhost, el puerto 80) con la cabecera
Host: APP_HOST (por defecto pdf.localhost). Es exactamente lo que hace un navegador
con http://pdf.localhost, pero sin depender de que el sistema resuelva *.localhost
(Windows no lo hace; los navegadores y curl sí).

Si el stack no está levantado, se saltan.
"""

import io
import os

import httpx
import pytest
from docx import Document

TRAEFIK_URL = os.environ.get("TRAEFIK_URL", "http://localhost")
APP_HOST = os.environ.get("APP_HOST", "pdf.localhost")
TRAEFIK_API_URL = os.environ.get("TRAEFIK_API_URL", "http://localhost:8080")

# El resumen espera a la IA: más que el timeout del summarizer (60 s)
TIMEOUT_SECONDS = 120


@pytest.fixture(scope="session")
def client():
    with httpx.Client(
        base_url=TRAEFIK_URL, headers={"Host": APP_HOST}, timeout=TIMEOUT_SECONDS
    ) as client:
        try:
            client.get("/health", timeout=3).raise_for_status()
        except httpx.HTTPError:
            pytest.skip(f"el stack no responde en http://{APP_HOST}: docker compose up -d --wait")
        yield client


@pytest.fixture(scope="session")
def ai_available(client) -> bool:
    return client.get("/api/health").json()["services"]["summarizer"]


@pytest.fixture
def requires_ai(ai_available):
    if not ai_available:
        pytest.skip("summarizer degradado: falta OPENROUTER_API_KEY o no se llega a OpenRouter")


def build_pdf(pages: list[str]) -> bytes:
    """PDF mínimo y válido con el texto indicado, una página por elemento."""
    objects: list[bytes] = []
    page_ids = [4 + i for i in range(len(pages))]
    content_ids = [4 + len(pages) + i for i in range(len(pages))]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(pages))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for content_id in content_ids:
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )

    for text in pages:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = b"BT /F1 12 Tf 72 720 Td (" + escaped.encode("latin-1") + b") Tj ET"
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref_offset = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_offset
    return bytes(out)


PDF_TEXT = "La fotosintesis convierte la luz del sol en energia quimica en las plantas."


@pytest.fixture
def pdf_bytes() -> bytes:
    return build_pdf([PDF_TEXT])


def docx_paragraphs(content: bytes) -> list[tuple[str, str]]:
    return [(p.style.name, p.text) for p in Document(io.BytesIO(content)).paragraphs]

"""Cada servicio, probado por su prefijo en Traefik (que lo quita antes de reenviar)."""

import pytest

from e2e.conftest import PDF_TEXT, build_pdf, docx_paragraphs

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("service", ["extractor", "summarizer", "summaries", "exporter"])
def test_cada_servicio_responde_en_su_prefijo(client, service):
    response = client.get(f"/{service}/health")

    assert response.status_code == 200
    assert response.json()["service"] == service


# --- extractor ---


def test_extractor_devuelve_el_texto_de_un_pdf(client, pdf_bytes):
    response = client.post("/extractor/extract", files={"file": ("doc.pdf", pdf_bytes)})

    assert response.status_code == 200
    assert response.json()["text"] == PDF_TEXT
    assert response.json()["page_count"] == 1


def test_extractor_rechaza_un_archivo_que_no_es_pdf(client):
    response = client.post("/extractor/extract", files={"file": ("x.pdf", b"no es un pdf")})

    assert response.status_code == 400


def test_extractor_rechaza_un_pdf_sin_texto(client):
    response = client.post("/extractor/extract", files={"file": ("x.pdf", build_pdf([""]))})

    assert response.status_code == 422


def test_extractor_rechaza_un_archivo_demasiado_grande(client):
    response = client.post(
        "/extractor/extract", files={"file": ("grande.pdf", b"0" * (11 * 1024 * 1024))}
    )

    assert response.status_code == 413


# --- summarizer ---


def test_summarizer_rechaza_un_texto_vacio(client):
    assert client.post("/summarizer/summarize", json={"text": "  "}).status_code == 422


def test_summarizer_sin_ia_explica_el_motivo(client, ai_available):
    if ai_available:
        pytest.skip("la IA está disponible: este caso no aplica")

    response = client.post("/summarizer/summarize", json={"text": PDF_TEXT})

    assert response.status_code in (502, 503)
    assert response.json()["detail"]


@pytest.mark.requires_ai
def test_summarizer_genera_un_resumen(client, requires_ai):
    response = client.post("/summarizer/summarize", json={"text": PDF_TEXT})

    assert response.status_code == 200
    assert response.json()["summary"].strip()


# --- summaries ---


def test_summaries_ciclo_completo_crear_listar_obtener_borrar(client):
    created = client.post(
        "/summaries/", json={"original_filename": "e2e.pdf", "summary_text": "Resumen e2e"}
    )
    assert created.status_code == 201
    summary_id = created.json()["id"]

    listed = client.get("/summaries/", params={"limit": 1000}).json()["summaries"]
    assert summary_id in [s["id"] for s in listed]
    assert client.get(f"/summaries/{summary_id}").json()["summary_text"] == "Resumen e2e"

    assert client.delete(f"/summaries/{summary_id}").status_code == 204
    assert client.get(f"/summaries/{summary_id}").status_code == 404


# --- exporter ---


def test_exporter_devuelve_un_docx_con_el_markdown(client):
    response = client.post(
        "/exporter/docx",
        json={"title": "Resumen: e2e.pdf", "markdown": "# Hola\n\n- **uno**", "filename": "e2e"},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="e2e.docx"'
    assert docx_paragraphs(response.content) == [
        ("Heading 1", "Resumen: e2e.pdf"),
        ("Heading 2", "Hola"),
        ("List Bullet", "uno"),
    ]

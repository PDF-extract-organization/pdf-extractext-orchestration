"""La interfaz y la API pública de web, que orquesta a los demás servicios."""

import pytest

from e2e.conftest import build_pdf, docx_paragraphs

pytestmark = pytest.mark.integration


def test_la_portada_se_sirve_con_su_css_e_imagenes(client):
    page = client.get("/")

    assert page.status_code == 200
    assert "PDF Summarizer" in page.text
    for asset in ("/static/css/output.css", "/static/media/s2.png", "/static/media/t.png"):
        assert client.get(asset).status_code == 200, asset


def test_api_health_informa_de_los_cuatro_servicios(client):
    body = client.get("/api/health").json()

    assert set(body["services"]) == {"extractor", "summarizer", "summaries", "exporter"}
    assert body["services"]["extractor"] is True
    assert body["services"]["summaries"] is True
    assert body["services"]["exporter"] is True


def test_un_error_del_extractor_llega_al_usuario_por_web(client):
    response = client.post("/api/summarize", files={"file": ("x.pdf", build_pdf([""]))})

    assert response.status_code == 422
    assert "escaneado" in response.json()["detail"]


def test_historial_exportar_y_borrar_por_web_sin_ia(client):
    """El resumen se crea en summaries; el resto del ciclo va por la API de web."""
    created = client.post(
        "/summaries/",
        json={"original_filename": "informe.pdf", "summary_text": "# Resumen\n\n- punto"},
    ).json()
    summary_id = created["id"]

    assert client.get(f"/api/summaries/{summary_id}").json() == created

    exported = client.get(f"/api/summaries/{summary_id}/export")
    assert exported.headers["content-disposition"] == (
        'attachment; filename="resumen_informe.docx"'
    )
    assert docx_paragraphs(exported.content)[0] == ("Heading 1", "Resumen: informe.pdf")

    assert client.delete(f"/api/summaries/{summary_id}").status_code == 204
    assert client.get(f"/summaries/{summary_id}").status_code == 404


def test_un_id_que_no_es_uuid_devuelve_422(client):
    assert client.get("/api/summaries/no-es-uuid").status_code == 422


@pytest.mark.requires_ai
def test_ciclo_completo_subir_resumir_guardar_descargar_borrar(client, requires_ai, pdf_bytes):
    uploaded = client.post("/api/summarize", files={"file": ("ciclo.pdf", pdf_bytes)})
    assert uploaded.status_code == 200, uploaded.text
    summary = uploaded.json()
    assert summary["summary_text"].strip()

    history = client.get("/api/summaries").json()["summaries"]
    assert summary["id"] in [s["id"] for s in history]

    exported = client.get(f"/api/summaries/{summary['id']}/export")
    assert exported.status_code == 200
    assert docx_paragraphs(exported.content)[0] == ("Heading 1", "Resumen: ciclo.pdf")

    assert client.delete(f"/api/summaries/{summary['id']}").status_code == 204
    assert client.get(f"/api/summaries/{summary['id']}").status_code == 404

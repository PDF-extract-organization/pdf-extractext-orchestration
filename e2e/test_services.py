"""Cada servicio, probado por su prefijo en Traefik (que lo quita antes de reenviar)."""

import pytest

from uuid import uuid4

from e2e.conftest import CONSUL_HOST, PDF_TEXT, build_pdf, docx_paragraphs

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "service", ["extractor", "summarizer", "summaries", "exporter", "config"]
)
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


# --- config ---


@pytest.fixture
def config_key(client):
    """Una clave propia de la prueba, bajo e2e/, que se borra al terminar."""
    key = f"e2e/clave-{uuid4().hex[:12]}"
    yield key
    client.delete(f"/config/{key}")


def test_config_ciclo_completo_crear_leer_listar_actualizar_borrar(client, config_key):
    created = client.post("/config/", json={"key": config_key, "value": "5000"})
    assert created.status_code == 201
    index = created.json()["index"]

    assert client.get(f"/config/{config_key}").json()["value"] == "5000"
    listed = client.get("/config/", params={"prefix": "e2e/"}).json()["entries"]
    assert config_key in [e["key"] for e in listed]

    updated = client.put(f"/config/{config_key}", json={"value": "6000", "index": index})
    assert updated.status_code == 200
    assert updated.json()["value"] == "6000"

    # Con el índice ya usado, otro cambio entre medio: no pisa
    stale = client.put(f"/config/{config_key}", json={"value": "7000", "index": index})
    assert stale.status_code == 409
    assert client.get(f"/config/{config_key}").json()["value"] == "6000"

    assert client.delete(f"/config/{config_key}").status_code == 204
    assert client.get(f"/config/{config_key}").status_code == 404


def test_config_no_crea_dos_veces_la_misma_clave(client, config_key):
    client.post("/config/", json={"key": config_key, "value": "a"})

    assert client.post("/config/", json={"key": config_key, "value": "b"}).status_code == 409


def test_config_rechaza_claves_invalidas(client):
    assert client.post("/config/", json={"key": "health", "value": "x"}).status_code == 422


def test_config_y_consul_comparten_el_mismo_kv(client, config_key):
    client.post("/config/", json={"key": config_key, "value": "desde config"})

    # La API de Consul por su host en Traefik: la clave vive bajo el prefijo del servicio
    in_consul = client.get(
        f"/v1/kv/pdf-extractext/{config_key}", params={"raw": ""}, headers={"Host": CONSUL_HOST}
    )

    assert in_consul.status_code == 200
    assert in_consul.text == "desde config"


# --- summarizer lee sus parámetros de config ---

MAX_TOKENS_KEY = "summarizer/max_tokens"


@pytest.fixture
def max_tokens_en_config(client):
    """Deja `summarizer/max_tokens` como estaba antes de la prueba (o sin crear)."""
    before = client.get(f"/config/{MAX_TOKENS_KEY}")
    client.delete(f"/config/{MAX_TOKENS_KEY}")
    env_value = client.get("/summarizer/parameters").json()["max_tokens"]

    def set_value(value: str) -> None:
        if client.put(f"/config/{MAX_TOKENS_KEY}", json={"value": value}).status_code == 404:
            client.post("/config/", json={"key": MAX_TOKENS_KEY, "value": value})

    yield set_value, env_value

    client.delete(f"/config/{MAX_TOKENS_KEY}")
    if before.status_code == 200:
        client.post("/config/", json={"key": MAX_TOKENS_KEY, "value": before.json()["value"]})


def max_tokens_en_uso(client) -> int:
    return client.get("/summarizer/parameters").json()["max_tokens"]


def test_summarizer_llega_a_config(client):
    assert client.get("/summarizer/parameters").json()["config_status"] == "ok"


def test_summarizer_aplica_un_cambio_de_config_sin_reiniciar(client, max_tokens_en_config):
    set_value, env_value = max_tokens_en_config

    set_value("1234")
    assert max_tokens_en_uso(client) == 1234

    set_value("4321")
    assert max_tokens_en_uso(client) == 4321

    client.delete(f"/config/{MAX_TOKENS_KEY}")
    assert max_tokens_en_uso(client) == env_value


def test_summarizer_ignora_un_valor_invalido_de_config(client, max_tokens_en_config):
    set_value, env_value = max_tokens_en_config

    set_value("abc")

    assert max_tokens_en_uso(client) == env_value


def test_summarizer_no_expone_la_api_key(client):
    response = client.get("/summarizer/parameters")

    assert response.status_code == 200
    assert not any("key" in name for name in response.json())

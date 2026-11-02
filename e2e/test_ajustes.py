"""La página Ajustes y los ajustes del usuario (épica pdf-extractext#72), por Traefik.

Los ajustes viajan como campos del formulario de POST /api/summarize, igual que los
manda la interfaz. Ninguno se guarda en el servidor.
"""

import pytest

pytestmark = pytest.mark.integration

# Misma clave de localStorage en la portada y en Ajustes: si no coinciden, lo que se
# guarda en Ajustes nunca llega a los resúmenes
SETTINGS_KEY = "pdf_extractext_settings"
FAKE_KEY = "sk-or-v1-clave-inventada-e2e-000000"


def history_ids(client) -> set[str]:
    summaries = client.get("/api/summaries", params={"limit": 1000}).json()["summaries"]
    return {s["id"] for s in summaries}


def summarize(client, pdf_bytes, filename="ajustes.pdf", **ajustes):
    return client.post(
        "/api/summarize",
        files={"file": (filename, pdf_bytes)},
        data={k: str(v) for k, v in ajustes.items()},
    )


@pytest.fixture
def no_new_summaries(client):
    """Comprueba al final que la prueba no dejó resúmenes en el historial."""
    before = history_ids(client)
    yield
    assert history_ids(client) == before


@pytest.fixture
def cleanup(client):
    """Borra los resúmenes que cree la prueba."""
    created: list[str] = []
    yield created
    for summary_id in created:
        client.delete(f"/api/summaries/{summary_id}")


# --- Las páginas ---


def test_la_portada_tiene_el_boton_de_ajustes_y_no_la_x(client):
    html = client.get("/").text

    assert 'href="/ajustes"' in html
    assert 'aria-label="Ajustes"' in html
    assert 'aria-label="Close summary"' not in html


def test_la_pagina_ajustes_se_sirve_con_su_css(client):
    page = client.get("/ajustes")

    assert page.status_code == 200
    assert "Ajustes" in page.text
    assert "/static/css/output.css" in page.text
    assert client.get("/static/css/output.css").status_code == 200


def test_ajustes_pide_la_clave_como_contrasena(client):
    assert 'type="password"' in client.get("/ajustes").text


def test_portada_y_ajustes_comparten_donde_se_guardan_los_ajustes(client):
    assert SETTINGS_KEY in client.get("/").text
    assert SETTINGS_KEY in client.get("/ajustes").text


# --- Valores del servidor ---


def test_los_valores_por_defecto_son_los_que_usa_summarizer(client):
    defaults = client.get("/api/settings/defaults").json()
    parameters = client.get("/summarizer/parameters").json()

    assert defaults == {
        "model": parameters["model"],
        "max_tokens": parameters["max_tokens"],
        "max_tokens_limit": parameters["max_tokens_limit"],
    }


# --- Ajustes inválidos: no llegan a guardarse ---


def test_max_tokens_por_encima_del_tope_se_rechaza_sin_guardar(client, pdf_bytes, no_new_summaries):
    limit = client.get("/api/settings/defaults").json()["max_tokens_limit"]

    response = summarize(client, pdf_bytes, max_tokens=limit + 1)

    assert response.status_code == 400
    assert str(limit) in response.json()["detail"]


def test_max_tokens_mal_escrito_da_422_sin_devolver_la_clave(client, pdf_bytes, no_new_summaries):
    response = summarize(client, pdf_bytes, max_tokens="muchos", api_key=FAKE_KEY)

    assert response.status_code == 422
    assert FAKE_KEY not in response.text


def test_una_clave_inventada_da_401_sin_devolverla_ni_guardar(client, pdf_bytes, no_new_summaries):
    """OpenRouter la rechaza antes de generar nada: no gasta cuota."""
    model = client.get("/api/settings/defaults").json()["model"]

    response = summarize(client, pdf_bytes, model=model, api_key=FAKE_KEY)

    assert response.status_code == 401
    assert response.json()["detail"] == "La API key no es válida."
    assert FAKE_KEY not in response.text


# --- Con IA ---


@pytest.mark.requires_ai
def test_con_pocos_tokens_el_resumen_nunca_pasa_por_completo(client, requires_ai, pdf_bytes, cleanup):
    """O llega marcado como incompleto, o un 502 que explica que faltaron tokens.
    Lo que no puede pasar es que se dé por bueno un resumen cortado."""
    response = summarize(client, pdf_bytes, max_tokens=20)

    if response.status_code == 200:
        cleanup.append(response.json()["id"])
        assert response.json()["truncated"] is True
    else:
        assert response.status_code == 502, response.text
        assert "tokens" in response.json()["detail"]


@pytest.mark.requires_ai
def test_un_resumen_con_los_ajustes_del_usuario_llega_completo(client, requires_ai, pdf_bytes, cleanup):
    defaults = client.get("/api/settings/defaults").json()

    response = summarize(
        client, pdf_bytes, model=defaults["model"], max_tokens=defaults["max_tokens"]
    )

    assert response.status_code == 200, response.text
    summary = response.json()
    cleanup.append(summary["id"])
    assert summary["truncated"] is False
    assert summary["summary_text"].strip()
    # truncated solo viaja al generarlo: el historial guarda el resumen sin él
    assert "truncated" not in client.get(f"/api/summaries/{summary['id']}").json()

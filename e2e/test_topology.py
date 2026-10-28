"""La topología: Traefik es la única puerta de entrada."""

import socket

import httpx
import pytest

from e2e.conftest import CONSUL_HOST, TRAEFIK_API_URL

pytestmark = pytest.mark.integration

ROUTERS = {"extractor", "summarizer", "summaries", "exporter", "web", "consul"}


def test_el_panel_de_traefik_muestra_todas_las_rutas_activas(client):
    routers = httpx.get(f"{TRAEFIK_API_URL}/api/http/routers", timeout=5).json()

    docker_routers = {
        r["name"].removesuffix("@docker"): r["status"]
        for r in routers
        if r["provider"] == "docker"
    }
    assert docker_routers == {name: "enabled" for name in ROUTERS}


@pytest.mark.parametrize("port", [8000, 27017, 8500])
def test_los_servicios_mongo_y_consul_no_publican_puertos_al_host(client, port):
    with pytest.raises(OSError):
        socket.create_connection(("localhost", port), timeout=2).close()


def test_una_ruta_desconocida_devuelve_404_y_no_500(client):
    assert client.get("/no-existe").status_code == 404


def test_un_host_distinto_no_llega_a_ningun_servicio(client):
    response = client.get("/health", headers={"Host": "otro.localhost"})

    assert response.status_code == 404


def test_consul_tiene_lider_a_traves_de_traefik(client):
    # Sin líder, Consul responde "" y el KV no funciona
    response = client.get("/v1/status/leader", headers={"Host": CONSUL_HOST})

    assert response.status_code == 200
    assert response.json().endswith(":8300")


def test_la_interfaz_de_consul_se_sirve_por_su_host(client):
    response = client.get("/ui/", headers={"Host": CONSUL_HOST})

    assert response.status_code == 200
    assert "consul" in response.text.lower()

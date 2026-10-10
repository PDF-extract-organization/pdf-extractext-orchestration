"""La topología: Traefik es la única puerta de entrada."""

import socket

import httpx
import pytest

from e2e.conftest import TRAEFIK_API_URL

pytestmark = pytest.mark.integration

ROUTERS = {"extractor", "summarizer", "summaries", "exporter", "web"}


def test_el_panel_de_traefik_muestra_las_cinco_rutas_activas(client):
    routers = httpx.get(f"{TRAEFIK_API_URL}/api/http/routers", timeout=5).json()

    docker_routers = {
        r["name"].removesuffix("@docker"): r["status"]
        for r in routers
        if r["provider"] == "docker"
    }
    assert docker_routers == {name: "enabled" for name in ROUTERS}


@pytest.mark.parametrize("port", [8000, 27017])
def test_los_servicios_y_mongo_no_publican_puertos_al_host(client, port):
    with pytest.raises(OSError):
        socket.create_connection(("localhost", port), timeout=2).close()


def test_una_ruta_desconocida_devuelve_404_y_no_500(client):
    assert client.get("/no-existe").status_code == 404


def test_un_host_distinto_no_llega_a_ningun_servicio(client):
    response = client.get("/health", headers={"Host": "otro.localhost"})

    assert response.status_code == 404

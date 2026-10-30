# pdf-extractext-orchestration

Orquestación de [pdf-extractext](https://github.com/PDF-extract-organization/pdf-extractext)
dividido en microservicios (épica: pdf-extractext#64): el `docker-compose` con Traefik
delante de los seis servicios y de Consul, y las pruebas de extremo a extremo que entran
por Traefik.

Aquí no hay código de ningún servicio: cada uno vive en su repositorio.

## Arquitectura

```
                            http://pdf.localhost                          http://consul.localhost
                                    │                                               │
                                Traefik :80          (panel en :8080) ──────────────┤
         ┌──────────┬──────────┬────┴─────┬──────────┬───────────────┐              │
   /extractor  /summarizer  /summaries  /exporter   /config   / y /api (el resto)   │
         │          │          │          │          │               │              │
     extractor  summarizer  summaries  exporter    config           web ──► los cuatro
                    │          │                     │                              │
                OpenRouter   MongoDB                 └──────────────────────────► Consul
                                                                            (KV de configuración)
```

| Servicio | Repositorio | Ruta en Traefik | Qué hace |
|---|---|---|---|
| web | [pdf-extractext-web](https://github.com/PDF-extract-organization/pdf-extractext-web) | `/` y `/api` | Interfaz y orquestador: el navegador solo habla con él |
| extractor | [pdf-extractext-extractor](https://github.com/PDF-extract-organization/pdf-extractext-extractor) | `/extractor` | PDF → texto |
| summarizer | [pdf-extractext-summarizer](https://github.com/PDF-extract-organization/pdf-extractext-summarizer) | `/summarizer` | Texto → resumen con IA |
| summaries | [pdf-extractext-summaries](https://github.com/PDF-extract-organization/pdf-extractext-summaries) | `/summaries` | Historial en MongoDB |
| exporter | [pdf-extractext-exporter](https://github.com/PDF-extract-organization/pdf-extractext-exporter) | `/exporter` | Markdown → `.docx` |
| config | [pdf-extractext-config](https://github.com/PDF-extract-organization/pdf-extractext-config) | `/config` | CRUD sobre el KV de Consul con `py-consul` |
| consul | imagen oficial `hashicorp/consul` | host `consul.localhost` | Configuración centralizada en su KV (épica: pdf-extractext#74) |

Consul es un único servidor (`-server -bootstrap-expect=1`) que se elige líder a sí
mismo: sin líder, el KV no responde. Va por host y no por prefijo porque su interfaz pide
rutas absolutas (`/ui`, `/v1`). Los servicios le hablan por la red interna
(`http://consul:8500`).

`config` es el único servicio que escribe en Consul. Guarda las claves bajo el prefijo
`pdf-extractext/`, así que lo que crea en `/config/summarizer/max_tokens` aparece en la
interfaz de Consul como `pdf-extractext/summarizer/max_tokens`. Arranca después de que
Consul tenga líder.

Traefik quita el prefijo antes de reenviar (`/extractor/health` llega al servicio como
`/health`), así que ningún servicio sabe que existe Traefik. Las reglas viven en las
etiquetas de `docker-compose.yml`, no en los repositorios de los servicios. `web` tiene
la prioridad mínima, para que `/` no se coma los prefijos de los demás.

Los servicios se hablan entre sí por la red interna de Docker (`http://extractor:8000`…),
sin pasar por Traefik.

## Puesta en marcha

Requisitos: Docker con Compose v2.

```bash
cp .env.example .env              # y rellena MONGO_ROOT_PASSWORD y, si la tienes, OPENROUTER_API_KEY
docker compose up -d --wait
```

`--wait` espera a que todos los contenedores estén sanos. Después:

| URL | Qué es |
|---|---|
| http://pdf.localhost | La aplicación |
| http://pdf.localhost/api/health | Estado de los cuatro servicios |
| http://pdf.localhost/extractor/health (y `/summarizer`, `/summaries`, `/exporter`, `/config`) | Cada servicio por su prefijo |
| http://pdf.localhost/config/ | La configuración guardada en Consul |
| http://localhost:8080 | Panel de Traefik con las rutas detectadas |
| http://consul.localhost | Interfaz de Consul (Key/Value para ver y editar la configuración) |

### Configuración centralizada

```bash
# Crear, leer, cambiar y borrar una clave (<servicio>/<nombre>)
curl -H "Content-Type: application/json" \
  -d '{"key": "summarizer/max_tokens", "value": "5000"}' http://pdf.localhost/config/
curl http://pdf.localhost/config/summarizer/max_tokens
curl -X PUT -H "Content-Type: application/json" \
  -d '{"value": "6000"}' http://pdf.localhost/config/summarizer/max_tokens
curl -X DELETE http://pdf.localhost/config/summarizer/max_tokens
```

El contrato completo (errores `404`, `409`, `422`, `503` y el `index` para no pisar
cambios ajenos) está en el README de
[pdf-extractext-config](https://github.com/PDF-extract-organization/pdf-extractext-config).

**summarizer lee sus parámetros de config en cada resumen**, con su `.env` como
respaldo. Un cambio vale en el siguiente resumen, sin reiniciar nada:

| Clave | Sustituye a |
|---|---|
| `summarizer/model` | `OPENROUTER_MODEL` |
| `summarizer/max_tokens` | `MAX_TOKENS` |
| `summarizer/temperature` | `TEMPERATURE` |
| `summarizer/max_prompt_chars` | `MAX_PROMPT_CHARS` |

```bash
curl http://pdf.localhost/summarizer/parameters   # los valores que usaría ahora
```

Un valor inválido se ignora. Si config no responde, summarizer usa su `.env` (tarda
como mucho 2 s más en decidirlo) y `/summarizer/parameters` lo indica con
`config_status: unavailable`. La API key nunca sale de config: solo del `.env`.

Los navegadores y `curl` resuelven `*.localhost` a tu propia máquina sin configurar
nada. Otros programas (por ejemplo Python en Windows) no: envíales la petición a
`http://localhost` con la cabecera `Host: pdf.localhost`, que es lo que hacen las
pruebas.

### Sin clave de OpenRouter

Todo funciona salvo generar resúmenes: `/api/health` marca `summarizer` como degradado
y subir un PDF responde `503` explicando que falta la clave. El historial, la
exportación y el borrado funcionan igual.

### Desarrollo: construir desde los repositorios

Mientras las imágenes no estén publicadas en ghcr (la CI de cada servicio las publica
al integrar en `main`), o para probar cambios locales, clona los siete repositorios uno
al lado del otro:

```
ProyectoDesarrollo/
├── pdf-extractext-orchestration/   ← este
├── pdf-extractext-extractor/
├── pdf-extractext-summarizer/
├── pdf-extractext-summaries/
├── pdf-extractext-exporter/
├── pdf-extractext-config/
└── pdf-extractext-web/
```

y levanta el stack con el archivo de desarrollo:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build --wait
```

| Cambio | ¿Hace falta reconstruir? |
|---|---|
| `index.html` de web | No: se ve al recargar el navegador |
| Código Python de web | No: uvicorn se recarga solo |
| CSS (clases de Tailwind nuevas) de web | Sí: `--build web` |
| Cualquier cosa de los otros servicios | Sí: `--build <servicio>` |
| Dependencias de cualquier servicio | Sí |

## Seguridad

- **Solo Traefik publica puertos** al host (80 y 8080). Ni los servicios, ni MongoDB,
  ni Consul son accesibles desde fuera de la red de Docker.
- **MongoDB arranca con autenticación** (`MONGO_ROOT_USERNAME` y `MONGO_ROOT_PASSWORD`).
  Solo `summaries` recibe las credenciales.
- **La API key de OpenRouter** solo llega al contenedor `summarizer`.
- **El socket de Docker** se monta en Traefik, en solo lectura, para que descubra los
  servicios por sus etiquetas. Es una decisión consciente y habitual en local, pero da a
  Traefik acceso al demonio de Docker: no usar así en producción.
- **El panel de Traefik** (`:8080`) va sin autenticación. Solo para desarrollo.
- **Consul** va sin ACL: cualquiera que llegue a `consul.localhost` puede leer y cambiar
  el KV. Solo para desarrollo. Por eso **el KV no guarda secretos**: las API keys siguen
  en el `.env` o en el navegador de cada usuario.
- **`/config`** tampoco tiene autenticación: cualquiera que llegue a `pdf.localhost` puede
  cambiar la configuración. Solo para desarrollo, igual que la interfaz de Consul.

## Pruebas de extremo a extremo

En `e2e/`. Todas entran por Traefik, nunca por el puerto de un servicio, y cubren:

- **Topología:** el panel muestra las siete rutas activas, los puertos de los
  servicios, de Mongo y de Consul no están expuestos, una ruta o un host desconocidos
  dan `404`, y Consul tiene líder y sirve su interfaz por `consul.localhost`.
- **Cada servicio por su prefijo:** extractor (`200`, `400`, `422`, `413`), summarizer
  (`422` y, con IA, un resumen real), summaries (crear, listar, obtener, borrar),
  exporter (el `.docx` con su contenido) y config (crear, leer, listar, actualizar, `409`
  con un índice viejo, borrar, y que lo escrito se vea en la API de Consul). Las claves
  de prueba viven bajo `e2e/` y se borran al terminar.
- **summarizer lee de config:** un cambio en `summarizer/max_tokens` se ve en
  `/summarizer/parameters` sin reiniciar, al borrarlo vuelve el del `.env`, y un valor
  inválido se ignora. La prueba deja la clave como estaba.
- **web:** la portada con su CSS e imágenes, `/api/health`, errores que llegan al
  usuario, historial, exportación y borrado; y, con IA, el ciclo completo subir PDF →
  resumen → guardado → descarga → borrado.

```bash
docker compose up -d --wait       # o con docker-compose.build.yml
uv sync --group dev
uv run pytest -rs                 # -rs muestra por qué se salta cada prueba
```

Si el stack no está levantado, las pruebas se saltan y `uv run pytest` sigue en verde.
Las que necesitan la IA (`requires_ai`) se saltan si `summarizer` está degradado.

| Variable | Por defecto | Uso |
|---|---|---|
| `TRAEFIK_URL` | `http://localhost` | Dónde escucha Traefik |
| `APP_HOST` | `pdf.localhost` | Cabecera `Host` de las peticiones |
| `TRAEFIK_API_URL` | `http://localhost:8080` | API del panel de Traefik |
| `CONSUL_HOST` | `consul.localhost` | Cabecera `Host` de las peticiones a Consul |

## CI

- En cada pull request: comprueba que el `docker-compose` es válido.
- A mano (`workflow_dispatch`): levanta el stack con las imágenes de ghcr y ejecuta las
  pruebas de extremo a extremo. Si el secreto `OPENROUTER_API_KEY` está configurado en
  el repositorio, incluye las que usan la IA.

## Configuración

Ver `.env.example`.

| Variable | Obligatoria | Uso |
|---|---|---|
| `MONGO_ROOT_USERNAME`, `MONGO_ROOT_PASSWORD` | Sí | Credenciales de MongoDB. La contraseña va dentro de una URL: evita `@ : / ? # %` y los caracteres no ASCII |
| `OPENROUTER_API_KEY` | Sí | Sin ella no se generan resúmenes |
| `OPENROUTER_MODEL` | No | Por defecto `openrouter/free` |
| `TAG` | No | Versión de las imágenes de ghcr. Por defecto `latest` |
| `APP_HOST` | No | Dominio de Traefik. Por defecto `pdf.localhost` |
| `CONSUL_HOST` | No | Dominio de la interfaz y la API de Consul. Por defecto `consul.localhost` |
| `MAX_FILE_SIZE_MB` | No | Tamaño máximo por PDF. Por defecto `10` |

## Flujo de trabajo

`main` y `develop` son las ramas principales. Los cambios entran por pull request a
`develop`. Los commits citan el issue (`#1`).

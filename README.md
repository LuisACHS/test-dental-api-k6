# API de reservas de horas dentales

API de agendamiento en FastAPI + PostgreSQL, pensada para quedar corriendo en
Docker y ser **el sujeto de pruebas de carga de un harness externo**. Trae
metricas Prometheus y una perilla para inyectar latencia y errores en caliente.

Alcance actual: registro/login con JWT, dentistas, gestion de pacientes y
creacion de citas con no-solape garantizado por la base.

---

## Levantar

```bash
docker compose up -d --build
docker compose ps          # db y api deben quedar "healthy"
```

Levanta **dos instancias de la misma API** contra la misma base:

| | Puerto | Caos | Para que |
|---|---|---|---|
| `dental-api` | **8000** | apagado | Linea base limpia y desarrollo. |
| `dental-api-chaos` | **8001** | **encendido** | Blanco de las pruebas de carga con fallas. |

Misma imagen, mismo codigo, misma base de datos: la unica diferencia son las
variables de [.env.chaos](.env.chaos). Correr el mismo escenario de k6 contra
los dos puertos y comparar es justamente la gracia.

| | 8000 (limpia) | 8001 (con caos) |
|---|---|---|
| Swagger | http://localhost:8000/docs | http://localhost:8001/docs |
| Metricas | http://localhost:8000/metrics | http://localhost:8001/metrics |
| Health | http://localhost:8000/health | http://localhost:8001/health |

Postgres queda en `localhost:5432` (`dental` / `dental`).

La configuracion sale de [.env](.env) (plantilla documentada en
[.env.example](.env.example)). Las migraciones se aplican solas al arrancar el
contenedor, desde [entrypoint.sh](entrypoint.sh).

Al arrancar se crea el admin de `BOOTSTRAP_ADMIN_EMAIL` /
`BOOTSTRAP_ADMIN_PASSWORD` si no existe: **admin@dental.local / admin12345**.

## Probar a mano en 30 segundos

```bash
# 1. login del admin
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -d "username=admin@dental.local&password=admin12345" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. crear un dentista
curl -s -X POST localhost:8000/api/v1/dentists \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"full_name":"Dra. Ana Soto","specialty":"Ortodoncia"}'

# 3. crear una cita (con el id del paso anterior)
curl -s -X POST localhost:8000/api/v1/appointments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dentist_id":"<UUID>","starts_at":"2026-12-01T14:00:00Z","ends_at":"2026-12-01T14:30:00Z"}'
```

En Swagger: registrar un usuario en `POST /api/v1/auth/register`, apretar
**Authorize** y entrar con ese email y password.

## Endpoints

| Metodo | Ruta | Auth |
|---|---|---|
| POST | `/api/v1/auth/register` | — |
| POST | `/api/v1/auth/login` | — |
| GET | `/api/v1/auth/me` | JWT |
| GET | `/api/v1/dentists` | JWT |
| POST | `/api/v1/dentists` | JWT admin |
| GET | `/api/v1/dentists/{id}` | JWT |
| GET | `/api/v1/dentists/{id}/availability` | JWT |
| POST | `/api/v1/patients` | JWT admin |
| GET | `/api/v1/patients` | JWT admin |
| GET | `/api/v1/patients/{id}` | JWT (admin o el propio paciente) |
| PATCH | `/api/v1/patients/{id}` | JWT (admin o el propio paciente) |
| GET | `/api/v1/patients/{id}/appointments` | JWT (admin o el propio paciente) |
| POST | `/api/v1/appointments` | JWT |
| GET | `/api/v1/appointments` | JWT |
| GET | `/api/v1/appointments/{id}` | JWT |
| GET / PUT / POST | `/admin/chaos`, `/admin/chaos/reset` | `X-Admin-Token` |
| GET | `/metrics`, `/health` | — |

Un paciente solo ve y agenda lo suyo; un admin ve todo y puede agendar a
nombre de otro pasando `patient_id`.

Un paciente es un `User` con `role=patient`: no hay tabla propia. `/patients`
es la gestion administrativa de esos usuarios (alta directa, listado, edicion)
mas su relacion con `/appointments`; un paciente puede ver/editar su propio
registro y sus propias citas, pero solo un admin puede crear, listar a todos
o activar/desactivar. No hay `DELETE`: se desactiva con
`PATCH {"is_active": false}` para no arrastrar en cascada las citas del
paciente.

---

## Disponibilidad

`GET /api/v1/dentists/{id}/availability?date=YYYY-MM-DD` devuelve los bloques
libres del dia, ya descontadas las citas existentes:

```bash
curl -s "localhost:8000/api/v1/dentists/$DID/availability?date=2026-10-01&slot_minutes=30" \
  -H "Authorization: Bearer $TOKEN"

{
  "dentist_id": "...", "date": "2026-10-01",
  "timezone": "America/Santiago", "slot_minutes": 30,
  "free": [{"starts_at":"2026-10-01T12:00:00Z","ends_at":"2026-10-01T12:30:00Z"}, ...]
}
```

Cada bloque sirve **tal cual** para `POST /appointments`: se emite en UTC, igual
que el resto de la API. El horario de atencion sale de `CLINIC_OPEN_HOUR`,
`CLINIC_CLOSE_HOUR` y `CLINIC_TIMEZONE` (default 09:00-18:00 America/Santiago);
`slot_minutes` se puede pasar por query y por defecto usa `DEFAULT_SLOT_MINUTES`.
Las citas canceladas no ocupan, mismo criterio que el EXCLUDE constraint, y los
bloques que ya pasaron no se ofrecen.

**Para la prueba de carga:** este es el flujo realista de dos pasos. Un harness
que solo hace POST a ciegas produce mayoria de 409 y mide el camino de error;
consultando primero, mide el camino feliz. Ademas es una ruta de solo lectura,
una sola consulta apoyada en el indice `(dentist_id, starts_at)`, util para
separar el costo de leer del de escribir.

---

## Caos: latencia y errores a pedido

Todo vive en [app/chaos/](app/chaos/) y se engancha con **una linea** en
[app/main.py](app/main.py#L96) (`app.add_middleware(ChaosMiddleware)`).
Ninguna ruta, modelo o servicio importa nada de ese paquete: borrando la
carpeta y esa linea, la API queda intacta.

Estado inicial por variables de entorno, y cambios en caliente sin reiniciar:

```bash
ADMIN=dev-admin-token-change-me

# ver el estado vigente
curl -s localhost:8000/admin/chaos -H "X-Admin-Token: $ADMIN"

# 200 ms +/- 50 ms de latencia, y 5% de 503, solo sobre las citas
curl -s -X PUT localhost:8000/admin/chaos \
  -H "X-Admin-Token: $ADMIN" -H "Content-Type: application/json" \
  -d '{"enabled":true,"latency_ms":200,"latency_jitter_ms":50,
       "error_rate":0.05,"error_status":503,"routes":["/api/v1/appointments*"]}'

# volver a los valores del .env
curl -s -X POST localhost:8000/admin/chaos/reset -H "X-Admin-Token: $ADMIN"
```

El `PUT` es parcial: los campos que no mandas quedan como estaban.

| Campo | Env | Que hace |
|---|---|---|
| `enabled` | `CHAOS_ENABLED` | Interruptor general. |
| `latency_ms` | `CHAOS_LATENCY_MS` | Retardo base antes de procesar. |
| `latency_jitter_ms` | `CHAOS_LATENCY_JITTER_MS` | Variacion uniforme +/- sobre el retardo. |
| `error_rate` | `CHAOS_ERROR_RATE` | Probabilidad (0–1) de cortar con error. |
| `error_status` | `CHAOS_ERROR_STATUS` | Status del error inyectado. |
| `routes` | `CHAOS_ROUTES` | Patrones glob sobre el path. |

La respuesta inyectada trae `X-Chaos-Injected: error` y el cuerpo
`{"detail":"chaos: error inyectado","chaos":true}`, asi que el harness puede
separar los errores provocados de los reales.

**`/admin`, `/health`, `/metrics`, `/docs` y `/openapi.json` estan siempre
exentos.** Si no lo estuvieran, un `error_rate` de 1.0 dejaria la API imposible
de recuperar sin reiniciar el contenedor.

---

### La instancia con caos (8001)

Arranca ya con esto puesto, sin que tengas que llamar a nada:

```
CHAOS_ENABLED=true
CHAOS_LATENCY_MS=150        # +/- 75 ms de jitter
CHAOS_ERROR_RATE=0.10       # 1 de cada 10 requests corta con 503
CHAOS_ROUTES=/api/v1/*      # solo la API de negocio
ACCESS_LOG=false            # es el blanco de carga
```

Se cambia de dos maneras: editando [.env.chaos](.env.chaos) y reiniciando con
`docker compose up -d api-chaos`, o en caliente contra el **8001**, que es lo
que conviene entre escenarios de k6:

```bash
curl -X PUT localhost:8001/admin/chaos -H "X-Admin-Token: $ADMIN" \
  -H "Content-Type: application/json" -d '{"error_rate":0.25,"latency_ms":400}'
curl -X POST localhost:8001/admin/chaos/reset -H "X-Admin-Token: $ADMIN"  # vuelve al .env.chaos
```

Tres cosas que conviene tener claras al medirla:

- Los 503 inyectados traen `X-Chaos-Injected: error`. **En k6 no son fallos
  de la API**: hay que contarlos aparte o `http_req_failed` miente.
- `/admin`, `/health`, `/metrics` y `/docs` siguen exentos, tambien aca:
  responden en ~3 ms mientras el resto arrastra los 150 ms.
- Cada instancia tiene su propio registro de metricas y su propio estado de
  caos. `chaos_injected_total` solo aparece en el 8001.

Las dos comparten la base, asi que lo que escribes por el 8001 lo ve el 8000.
Si necesitas aislarlas, dale a `api-chaos` su propio `POSTGRES_DB`.

---

## Medir

`GET /metrics` en formato Prometheus:

| Metrica | Tipo | Labels |
|---|---|---|
| `http_requests_total` | counter | `method`, `route`, `status` |
| `http_request_duration_seconds` | histogram | `method`, `route` |
| `http_requests_in_progress` | gauge | `method` |
| `chaos_injected_total` | counter | `kind` (`latency` / `error`) |

`route` es siempre el **patron** (`/api/v1/appointments/{appointment_id}`) y
nunca la URL con el UUID: con la URL literal, cada id de una corrida abriria
una serie nueva. Los 404 reales caen en `__unmatched__`.

La duracion se mide en el middleware mas externo, o sea **incluye la latencia
inyectada**: es lo que ve el cliente. `chaos_injected_total` permite descontarla.

### Antes de una corrida de carga

Cuatro cosas de este repo que van a distorsionar los numeros si no las tocas:

1. **`BCRYPT_ROUNDS=12`.** bcrypt es CPU-bound a proposito: un login cuesta
   ~250 ms y domina cualquier medicion que incluya `/auth/login`. Para medir el
   resto de la API, loguearse una vez y reutilizar el token, o bajar a 4–6.
   El hashing corre en un threadpool, asi que no bloquea el event loop, pero
   sigue quemando CPU del contenedor.
2. **`ACCESS_LOG=false`.** El access log de uvicorn cuesta throughput.
3. **`RELOAD=false`.** El reloader agrega overhead y ruido.
4. **`WORKERS=1`** (default). Con mas de uno, cada worker tiene su propio
   estado de caos y su propio registro de metricas, asi que `PUT /admin/chaos`
   solo afecta al worker que atendio ese request y `/metrics` solo reporta uno.
   Para subir workers hay que montar `PROMETHEUS_MULTIPROC_DIR` y mover el caos
   a un almacen compartido.

Tambien `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`: con mas concurrencia que conexiones,
lo que se mide es la espera por el pool.

---

## Decisiones que conviene conocer

**No-solape en la base, no en el codigo.** La migracion
[0001_initial.py](migrations/versions/0001_initial.py) crea un EXCLUDE
constraint sobre `(dentist_id, tstzrange(starts_at, ends_at, '[)'))`. Un
`SELECT` previo en Python tiene una ventana de carrera y bajo concurrencia
produce dobles reservas; el constraint se lo delega al motor, sin locks. La
ruta traduce la violacion a **409**. El rango es `[)`, asi que 14:00–14:30 y
14:30–15:00 conviven.

**Todo async.** Engine async de SQLAlchemy + asyncpg. Con un pool sync bajo
carga concurrente se mediria el bloqueo del event loop, no la API.

**Dependencias.** Ver la cabecera de [requirements.txt](requirements.txt):
PyJWT en vez de python-jose (sin releases desde 2021, arrastra `ecdsa` con
CVEs), `bcrypt` directo en vez de passlib (sin mantencion desde 2020, roto con
bcrypt >= 4.1), `prometheus-client` en vez del instrumentator, y nada de
`fastapi[standard]`.

### Congelar el lock

[requirements.lock.txt](requirements.lock.txt) fija las versiones exactas y el
Dockerfile lo prefiere si existe. Despues de tocar `requirements.txt`:

```bash
docker compose build --no-cache api        # resuelve los rangos de nuevo
docker compose exec -T api pip freeze > requirements.lock.txt
docker compose up -d --build api
```

---

## Pruebas

```bash
docker compose exec api pytest -q          # instancia limpia
docker compose exec api-chaos pytest -q    # tambien pasa ahi
```

35 pruebas smoke sobre la base real del compose: auth, creacion de citas,
conflicto 409, citas contiguas, permisos por rol, disponibilidad, caos y
cardinalidad de las metricas. Cada test crea sus propios datos con ids unicos, asi que son
repetibles aunque la base quede sucia.

> Los archivos de la raiz (`pytest.ini`, `alembic.ini`, `requirements*.txt`)
> viven en la imagen; el compose solo monta `app/`, `migrations/` y `tests/`.
> Cambiar uno de la raiz pide `docker compose up -d --build api`.

## Estructura

```
app/
├─ main.py              # app factory, routers, middlewares
├─ core/                # config, security (bcrypt + JWT), deps
├─ db/                  # base declarativa y engine async
├─ models/              # users, dentists, appointments
├─ schemas/             # entrada/salida Pydantic
├─ api/v1/              # auth, dentists, patients, appointments
├─ api/admin.py         # perillas del caos
├─ chaos/               # estado + middleware  <- apartado aislado
└─ observability/       # metricas Prometheus
migrations/             # Alembic (async)
tests/                  # smoke
```

## Fuera de alcance

Suite de performance (la trae el harness externo), seed masivo y reset de datos
entre corridas, refresh tokens, cancelar/reagendar, rate limiting, HTTPS.
La disponibilidad se calcula sobre el horario fijo de la clinica: todavia no
hay agenda propia por dentista ni bloqueos por vacaciones o feriados.

Lo primero que probablemente haga falta al empezar a medir es el **seed masivo**
(N pacientes con password conocida para login en paralelo) y el **reset de
citas** entre corridas: sin eso, cada corrida deja la base sucia y los numeros
dejan de ser comparables.

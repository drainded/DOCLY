"""
webapp/main.py
================
Punto de entrada del servidor web de Mostrador (seccion 2, seccion 9.1).

Esta es la capa que:
  - lee configuracion de os.environ (regla seccion 9.1: engine/ nunca lo hace,
    ver webapp/api/routes.py::_build_config),
  - conoce FastAPI/HTTP,
  - sirve el frontend estatico del panel (webapp/static/).

Traduce peticiones HTTP en llamadas a engine.core.pipeline.run() y
engine.document.store — ver webapp/api/routes.py para los endpoints.

Variables de entorno
----------------------
GEMINI_API_KEY        (obligatoria)  credencial de Gemini (Paso 3, seccion 3)
GROQ_API_KEY          (opcional)     fallback ante rate limit (seccion 9)
MOSTRADOR_STORAGE_DIR (opcional)     directorio de almacenamiento (seccion 9); default "./storage"
MOSTRADOR_SESSION_TTL_MINUTES (opcional) inactividad tras la que se borra una sesion; default 60
LIBREOFFICE_BIN       (opcional)     binario de LibreOffice headless; default "libreoffice"
MAX_FILE_SIZE_BYTES   (opcional)     limite de tamano de archivo; default 50 MB (seccion 3)

Ejecucion local
-----------------
    uvicorn webapp.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from webapp.api.routes import router, sweep_expired

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECONDS = 300


async def _sweep_loop() -> None:
    """Borra las sesiones caducadas al arrancar y despues cada pocos minutos."""
    while True:
        try:
            await asyncio.to_thread(sweep_expired)
        except Exception:  # noqa: BLE001 - la limpieza nunca debe tumbar el servidor
            logger.exception("[Sesion] Fallo la limpieza de sesiones caducadas")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Mostrador", version="1.0.0", lifespan=lifespan)
app.include_router(router, prefix="/api")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")

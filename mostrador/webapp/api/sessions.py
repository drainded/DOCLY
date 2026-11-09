"""
webapp/api/sessions.py
=========================
Sesiones efimeras del panel: cada carga de la pagina es una sesion nueva y sus
documentos viven solo mientras ella (SPEC seccion 9, "almacenamiento efimero").

Modelo
------
- El navegador genera un uuid4 al cargar la pagina (solo en memoria: recargar
  genera otro) y lo manda como `sid` en cada llamada a /api.
- Los documentos de una sesion viven en `{storage}/{sid}/`; el motor y
  engine/document/store.py no saben de sesiones: reciben ese directorio como su
  `storage_dir` de siempre.
- Una sesion solo ve su propio directorio, asi que ya no hay un historial
  compartido entre visitantes. El `sid` es un secreto de 122 bits: quien no lo
  conoce no puede listar, descargar ni borrar esos documentos.
- La sesion se borra cuando la pagina avisa de que se va (`POST /api/session/end`
  via sendBeacon al recargar o cerrar) y, como respaldo, cuando lleva mas de
  `ttl` sin actividad: el navegador no garantiza el aviso (cierre brusco, bateria,
  perdida de red), asi que `purge_expired` barre lo que haya quedado.

Seguridad: `sid` llega desde la URL; se valida contra el formato exacto de uuid4
ANTES de construir ninguna ruta (igual que store._is_valid_processing_id), para
que no pueda usarse en un path traversal.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def is_valid_sid(sid: str) -> bool:
    return bool(_SID_PATTERN.fullmatch(sid))


def session_dir(root: Path, sid: str) -> Path:
    """Directorio de una sesion. `sid` debe haberse validado con `is_valid_sid`."""
    return root / sid


def touch(directory: Path) -> None:
    """Marca actividad: la caducidad cuenta desde la ultima vez que la sesion se uso."""
    try:
        os.utime(directory)
    except OSError:
        pass  # la sesion aun no tiene directorio (no ha subido nada) o ya se borro


def delete_session(root: Path, sid: str) -> bool:
    """Borra todos los archivos de la sesion. True si existia; idempotente."""
    if not is_valid_sid(sid):
        return False
    directory = session_dir(root, sid)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    logger.info("[Sesion] Sesion eliminada: %s", sid)
    return True


def purge_expired(root: Path, max_age_seconds: float, now: float | None = None) -> int:
    """
    Borra las sesiones sin actividad desde hace mas de `max_age_seconds`.

    Solo toca subdirectorios cuyo nombre es un uuid4 de sesion: los archivos
    sueltos del almacenamiento anterior (sin sesiones) y cualquier otra cosa en
    `root` se dejan como estan.

    Returns
    -------
    int
        Cantidad de sesiones eliminadas.
    """
    if not root.is_dir():
        return 0
    current = time.time() if now is None else now
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir() or not is_valid_sid(entry.name):
            continue
        try:
            age = current - entry.stat().st_mtime
        except OSError:
            continue
        if age > max_age_seconds:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
            logger.info("[Sesion] Sesion caducada eliminada: %s", entry.name)
    return removed

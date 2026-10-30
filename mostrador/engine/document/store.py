"""
engine/document/store.py
==========================
Almacenamiento y eliminacion de documentos procesados (seccion 9):
"Se almacenan todos los documentos procesados (originales y resultantes).
El usuario tiene un boton para eliminar cada documento individualmente
desde el panel."

Convencion de nombres dentro de un unico directorio plano `storage_dir`,
namespaced por processing_id (el mismo uuid4 que core/pipeline.py ya
genera para nombrar sus artefactos de salida, seccion 5):

    {processing_id}.meta.json       metadatos (StoredDocument serializado)
    {processing_id}_original{ext}   copia del archivo subido por el usuario
    {processing_id}.docx            documento final (mismo nombre que pipeline.py ya usa)
    {processing_id}_preview.png     vista previa (mismo nombre que pipeline.py ya usa)

Asi, si el caller (webapp/api/routes.py) pasa ProcessingConfig.output_dir
= storage_dir al invocar pipeline.run(), el .docx y la preview quedan
escritos directamente en su ubicacion final — este modulo solo necesita
copiar el original y persistir los metadatos despues.

Regla seccion 9.1: recibe `storage_dir` como parametro explicito en cada
funcion — nunca lee rutas de os.environ ni mantiene estado global. No
ejecuta el pipeline ni conoce HTTP (eso vive en webapp/) — solo administra
el ciclo de vida de archivos ya producidos por engine.core.pipeline.run().

Seguridad: `processing_id` llega desde una URL HTTP en el caller
(GET/DELETE /documents/{processing_id}), es decir, es un valor con el que
un cliente podria intentar path traversal (ej. "../../etc/passwd"). Toda
funcion que lo recibe como parametro externo (get_document,
delete_document) lo valida contra el formato exacto de uuid4 ANTES de
construir ninguna ruta de archivo.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engine.document.models import FormatStyle, ProcessingResult

logger = logging.getLogger(__name__)

_META_SUFFIX = ".meta.json"
_ORIGINAL_INFIX = "_original"
_PREVIEW_SUFFIX = "_preview.png"
_OUTPUT_SUFFIX = ".docx"

# pipeline.py genera processing_id via str(uuid.uuid4()) — cualquier otro
# formato se rechaza antes de tocar el sistema de archivos (ver docstring
# del modulo, seccion "Seguridad").
_VALID_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _is_valid_processing_id(processing_id: str) -> bool:
    return bool(_VALID_ID_PATTERN.fullmatch(processing_id))


# ---------------------------------------------------------------------------
# Modelo de datos persistido
# ---------------------------------------------------------------------------

@dataclass
class StoredDocument:
    """Registro persistente de un documento procesado (seccion 9)."""

    processing_id: str
    original_filename: str
    style: FormatStyle
    created_at: datetime
    success: bool
    error_code: str | None = None
    error_message: str | None = None

    def original_path(self, storage_dir: Path) -> Path | None:
        ext = Path(self.original_filename).suffix
        path = storage_dir / f"{self.processing_id}{_ORIGINAL_INFIX}{ext}"
        return path if path.exists() else None

    def output_path(self, storage_dir: Path) -> Path | None:
        path = storage_dir / f"{self.processing_id}{_OUTPUT_SUFFIX}"
        return path if (self.success and path.exists()) else None

    def preview_path(self, storage_dir: Path) -> Path | None:
        path = storage_dir / f"{self.processing_id}{_PREVIEW_SUFFIX}"
        return path if path.exists() else None


# ===========================================================================
# API publica
# ===========================================================================

def save_processed_document(
    storage_dir: Path,
    original_path: Path,
    original_filename: str,
    style: FormatStyle,
    result: ProcessingResult,
) -> StoredDocument:
    """
    Persiste el resultado de un pipeline.run() ya ejecutado: copia el
    archivo original bajo el processing_id del resultado y escribe los
    metadatos (seccion 9). Se llama tanto si `result.success` es True
    como False — el historial del panel tambien muestra los intentos
    fallidos (documento corrupto, rate limit, etc.).

    Parameters
    ----------
    storage_dir:
        Directorio de almacenamiento persistente (se crea si no existe).
    original_path:
        Ruta al archivo tal como se le paso a pipeline.run(). pipeline.py
        nunca la modifica ni la elimina (solo limpia su copia temporal
        interna), asi que sigue disponible aqui despues de que run() retorne.
    original_filename:
        Nombre original del archivo (para preservar la extension y
        mostrarlo en el panel).
    style:
        Estilo de formato solicitado.
    result:
        ProcessingResult devuelto por pipeline.run().

    Returns
    -------
    StoredDocument
        El registro persistido (tambien recuperable luego via
        get_document/list_documents).
    """
    storage_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(original_filename).suffix
    stored_original_path = storage_dir / f"{result.processing_id}{_ORIGINAL_INFIX}{ext}"
    shutil.copy2(original_path, stored_original_path)

    document = StoredDocument(
        processing_id=result.processing_id,
        original_filename=original_filename,
        style=style,
        created_at=datetime.now(timezone.utc),
        success=result.success,
        error_code=result.error_code,
        error_message=result.error_message,
    )
    _write_meta(storage_dir, document)
    logger.info("[Store] Documento persistido: %s (success=%s)", document.processing_id, document.success)
    return document


def list_documents(storage_dir: Path) -> list[StoredDocument]:
    """Devuelve todos los documentos almacenados, mas recientes primero."""
    if not storage_dir.exists():
        return []

    documents = [_read_meta(meta_path) for meta_path in storage_dir.glob(f"*{_META_SUFFIX}")]
    valid_documents = [d for d in documents if d is not None]
    valid_documents.sort(key=lambda d: d.created_at, reverse=True)
    return valid_documents


def get_document(storage_dir: Path, processing_id: str) -> StoredDocument | None:
    """Devuelve un documento por su processing_id, o None si no existe o el id es invalido."""
    if not _is_valid_processing_id(processing_id):
        logger.warning("[Store] processing_id con formato invalido rechazado: %r", processing_id)
        return None

    meta_path = storage_dir / f"{processing_id}{_META_SUFFIX}"
    if not meta_path.exists():
        return None
    return _read_meta(meta_path)


def delete_document(storage_dir: Path, processing_id: str) -> bool:
    """
    Elimina PERMANENTEMENTE todos los archivos de un documento (original,
    resultado, preview, metadatos) — seccion 9: "el usuario tiene un boton
    para eliminar cada documento individualmente".

    Returns
    -------
    bool
        True si el documento existia y se elimino; False si no existia o
        el processing_id no tiene el formato esperado (idempotente: borrar
        dos veces no es un error).
    """
    if not _is_valid_processing_id(processing_id):
        logger.warning("[Store] processing_id con formato invalido rechazado: %r", processing_id)
        return False

    meta_path = storage_dir / f"{processing_id}{_META_SUFFIX}"
    if not meta_path.exists():
        return False

    for path in storage_dir.glob(f"{processing_id}*"):
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("[Store] No se pudo eliminar %s: %s", path, exc)

    logger.info("[Store] Documento eliminado: %s", processing_id)
    return True


# ===========================================================================
# Serializacion de metadatos
# ===========================================================================

def _write_meta(storage_dir: Path, document: StoredDocument) -> None:
    meta_path = storage_dir / f"{document.processing_id}{_META_SUFFIX}"
    payload = {
        "processing_id": document.processing_id,
        "original_filename": document.original_filename,
        "style": document.style.value,
        "created_at": document.created_at.isoformat(),
        "success": document.success,
        "error_code": document.error_code,
        "error_message": document.error_message,
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_meta(meta_path: Path) -> StoredDocument | None:
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        processing_id = payload["processing_id"]
        if not _is_valid_processing_id(processing_id) or processing_id != meta_path.stem.removesuffix(".meta"):
            raise ValueError(f"processing_id inconsistente en {meta_path}")
        return StoredDocument(
            processing_id=processing_id,
            original_filename=payload["original_filename"],
            style=FormatStyle(payload["style"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            success=payload["success"],
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("[Store] Metadatos corruptos en %s — se ignora: %s", meta_path, exc)
        return None

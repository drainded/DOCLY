"""
webapp/api/routes.py
=======================
Endpoints HTTP del panel de Mostrador (seccion 2):
  POST   /api/upload
  POST   /api/documents/{pending_id}/confirm-overwrite
  POST   /api/documents/{pending_id}/cancel-overwrite
  GET    /api/documents
  GET    /api/documents/{processing_id}/download
  GET    /api/documents/{processing_id}/preview
  DELETE /api/documents/{processing_id}

Esta es la UNICA capa que conoce FastAPI, lee os.environ, o mantiene
estado de sesion HTTP (regla seccion 9.1: engine/ es agnostico del
framework web — solo recibe ProcessingConfig ya construido).

Concurrencia (seccion 9): v1 procesa 1 documento a la vez, sin cola
paralela. `_PROCESSING_LOCK` serializa las llamadas a pipeline.run() —
cualquier /upload adicional espera aqui a que termine el que esta en
curso, exactamente como pide el spec.

Flujo de conflicto de estilos (seccion 7)
--------------------------------------------
1. POST /upload ejecuta pipeline.run() sin overwrite_styles. Si el
   documento tiene estilos conflictivos, el resultado trae
   error_code="CONFLICTING_STYLES" y esta funcion guarda el archivo
   subido en `_PENDING_OVERWRITES` bajo su processing_id (como `pending_id`
   en la respuesta), sin persistirlo aun en el store permanente.
2. El frontend muestra un dialogo de confirmacion (seccion 7).
3. Si el usuario confirma: POST /documents/{pending_id}/confirm-overwrite
   reintenta el pipeline completo con overwrite_styles=True sobre el
   MISMO archivo subido. pipeline.run() genera un processing_id NUEVO
   para este segundo intento (no reutiliza `pending_id` — cada llamada a
   run() genera el suyo), asi que la respuesta trae un `processing_id`
   distinto al `pending_id` original.
4. Si el usuario cancela: POST /documents/{pending_id}/cancel-overwrite
   descarta el archivo subido sin procesarlo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from engine.core import pipeline
from engine.document import store
from engine.document.models import FormatStyle, ProcessingConfig, ProcessingResult
from webapp.config import MissingAPIKeyError, load_processing_config

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_FILENAME = "documento.docx"

# Seccion 9: 1 documento a la vez, sin cola paralela.
_PROCESSING_LOCK = asyncio.Lock()


class _PendingUpload:
    """Subida en espera de confirmacion de sobrescritura de estilos (seccion 7).

    Vive solo en memoria del proceso — aceptable para v1 (concurrencia = 1,
    sin necesidad de persistir estado entre reinicios del servidor).
    """

    __slots__ = ("staged_path", "original_filename", "style")

    def __init__(self, staged_path: Path, original_filename: str, style: FormatStyle) -> None:
        self.staged_path = staged_path
        self.original_filename = original_filename
        self.style = style


_PENDING_OVERWRITES: dict[str, _PendingUpload] = {}


# ===========================================================================
# Configuracion (unico punto donde se lee os.environ, regla seccion 9.1)
# ===========================================================================

def _storage_dir() -> Path:
    return Path(os.environ.get("MOSTRADOR_STORAGE_DIR", "storage")).resolve()


def _build_config(style: FormatStyle) -> ProcessingConfig:
    """
    Construye el ProcessingConfig via webapp.config.load_processing_config()
    (carga GEMINI_API_KEY/GROQ_API_KEY/GEMINI_MODEL/... desde .env, seccion
    9.1) y fuerza `output_dir` al directorio de almacenamiento persistente,
    para que pipeline.run() escriba el .docx y la preview directamente en
    su ubicacion final (engine/document/store.py los recoge desde ahi sin
    necesidad de moverlos despues).
    """
    try:
        config = load_processing_config(style=style)
    except MissingAPIKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    config.output_dir = _storage_dir()
    return config


def _safe_filename(raw: str | None) -> str:
    """
    Nombre de archivo del cliente reducido a su ultimo componente.

    El cliente controla `filename`: un valor como "../../x.docx" o
    "C:\\x.docx" haria que `staged_dir / filename` apunte fuera del directorio
    temporal (se escribiria ahi y luego `_cleanup_staged_file` lo borraria).
    Se corta en ambos separadores ("/" y "\\") sin importar el sistema operativo.
    """
    name = re.split(r"[\\/]", raw or "")[-1].strip()
    if name in ("", ".", "..") or ":" in name:
        return _DEFAULT_FILENAME
    return name


def _parse_style(style: str) -> FormatStyle:
    try:
        return FormatStyle(style)
    except ValueError:
        valid = ", ".join(s.value for s in FormatStyle)
        raise HTTPException(status_code=400, detail=f"Estilo '{style}' invalido. Valores validos: {valid}.")


# ===========================================================================
# Endpoints
# ===========================================================================

@router.post("/upload")
async def upload_document(file: UploadFile = File(...), style: str = Form(...)) -> dict:
    """Sube un documento y lo procesa (seccion 2)."""
    format_style = _parse_style(style)
    original_filename = _safe_filename(file.filename)
    config = _build_config(format_style)

    staged_dir = Path(tempfile.mkdtemp(prefix="mostrador_upload_"))
    staged_path = staged_dir / original_filename
    staged_path.write_bytes(await file.read())

    async with _PROCESSING_LOCK:
        result = await asyncio.to_thread(pipeline.run, staged_path, config)

    if result.error_code == "CONFLICTING_STYLES":
        _PENDING_OVERWRITES[result.processing_id] = _PendingUpload(
            staged_path=staged_path, original_filename=original_filename, style=format_style,
        )
        return _result_payload(result, pending_id=result.processing_id)

    store.save_processed_document(_storage_dir(), staged_path, original_filename, format_style, result)
    _cleanup_staged_file(staged_path)
    return _result_payload(result)


@router.post("/documents/{pending_id}/confirm-overwrite")
async def confirm_overwrite(pending_id: str) -> dict:
    """Confirma sobrescribir estilos conflictivos (seccion 7) y reintenta el pipeline."""
    pending = _PENDING_OVERWRITES.pop(pending_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="No hay ninguna subida pendiente con ese id.")

    config = _build_config(pending.style)

    async with _PROCESSING_LOCK:
        result = await asyncio.to_thread(pipeline.run, pending.staged_path, config, overwrite_styles=True)

    store.save_processed_document(
        _storage_dir(), pending.staged_path, pending.original_filename, pending.style, result,
    )
    _cleanup_staged_file(pending.staged_path)
    return _result_payload(result)


@router.post("/documents/{pending_id}/cancel-overwrite")
def cancel_overwrite(pending_id: str) -> dict:
    """Cancela una subida pausada por conflicto de estilos, sin procesarla."""
    pending = _PENDING_OVERWRITES.pop(pending_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="No hay ninguna subida pendiente con ese id.")
    _cleanup_staged_file(pending.staged_path)
    return {"cancelled": True}


@router.get("/documents")
def list_documents() -> list[dict]:
    return [_document_payload(doc) for doc in store.list_documents(_storage_dir())]


@router.get("/documents/{processing_id}/download")
def download_document(processing_id: str) -> FileResponse:
    document = store.get_document(_storage_dir(), processing_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    output_path = document.output_path(_storage_dir())
    if output_path is None:
        raise HTTPException(status_code=404, detail="Este documento no tiene un resultado descargable.")
    download_name = f"{Path(document.original_filename).stem}_{document.style.value}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=download_name,
    )


@router.get("/documents/{processing_id}/preview")
def preview_document(processing_id: str) -> FileResponse:
    document = store.get_document(_storage_dir(), processing_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    preview_path = document.preview_path(_storage_dir())
    if preview_path is None:
        raise HTTPException(status_code=404, detail="Este documento no tiene vista previa disponible.")
    return FileResponse(preview_path, media_type="image/png")


@router.delete("/documents/{processing_id}")
def delete_document(processing_id: str) -> dict:
    """Elimina un documento (seccion 9: boton de eliminacion individual)."""
    deleted = store.delete_document(_storage_dir(), processing_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    return {"deleted": True}


# ===========================================================================
# Helpers
# ===========================================================================

def _cleanup_staged_file(staged_path: Path) -> None:
    try:
        staged_path.unlink(missing_ok=True)
        staged_path.parent.rmdir()
    except OSError:
        pass  # directorio no vacio o ya eliminado — no es fatal


def _result_payload(result: ProcessingResult, pending_id: str | None = None) -> dict:
    payload = {
        "processing_id": result.processing_id,
        "success": result.success,
        "error_code": result.error_code,
        "message": result.user_message,
        "gemini_rate_limited": result.gemini_rate_limited,
        "fallback_used": result.fallback_used,
    }
    if pending_id is not None:
        payload["pending_id"] = pending_id
    return payload


def _document_payload(document: store.StoredDocument) -> dict:
    storage_dir = _storage_dir()
    return {
        "processing_id": document.processing_id,
        "original_filename": document.original_filename,
        "style": document.style.value,
        "created_at": document.created_at.isoformat(),
        "success": document.success,
        "error_code": document.error_code,
        "error_message": document.error_message,
        "has_preview": document.preview_path(storage_dir) is not None,
    }

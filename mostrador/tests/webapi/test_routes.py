"""
tests/webapp/test_routes.py
=============================
Tests de webapp/api/routes.py con TestClient. El pipeline se sustituye por un
doble (sin Gemini ni LibreOffice); se prueba la capa HTTP: validacion de
entrada, flujo de conflicto de estilos, almacenamiento y borrado.
"""

import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

from engine.document.models import DocumentMeta, ProcessingConfig, ProcessingResult
from webapp.api import routes
from webapp.api.routes import _safe_filename
from webapp.main import app

_DOCX_BYTES = b"PK\x03\x04 contenido de prueba"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    directory = tmp_path / "storage"
    monkeypatch.setenv("MOSTRADOR_STORAGE_DIR", str(directory))
    monkeypatch.setattr(
        routes, "_build_config",
        lambda style: ProcessingConfig(gemini_api_key="k", style=style, output_dir=directory),
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(staging))  # mkdtemp de las subidas
    routes._PENDING_OVERWRITES.clear()
    return directory


@pytest.fixture
def client():
    return TestClient(app)


def _fake_pipeline(monkeypatch, conflict_first=False):
    calls = []

    def run(doc_path, config, *, overwrite_styles=False):
        calls.append({"name": doc_path.name, "overwrite": overwrite_styles})
        result = ProcessingResult(processing_id=str(uuid.uuid4()))
        if conflict_first and not overwrite_styles:
            result.error_code = "CONFLICTING_STYLES"
            result.error_message = "estilos en conflicto"
            return result
        config.output_dir.mkdir(parents=True, exist_ok=True)
        output = config.output_dir / f"{result.processing_id}.docx"
        output.write_bytes(_DOCX_BYTES)
        result.success = True
        result.output_docx_path = output
        result.doc_meta = DocumentMeta(processing_id=result.processing_id)
        return result

    monkeypatch.setattr(routes.pipeline, "run", run)
    return calls


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("informe.docx", "informe.docx"),
        ("../../etc/informe.docx", "informe.docx"),
        ("..\\..\\Windows\\informe.docx", "informe.docx"),
        ("C:\\Users\\x\\informe.docx", "informe.docx"),
        ("C:informe.docx", "documento.docx"),
        ("..", "documento.docx"),
        ("", "documento.docx"),
        (None, "documento.docx"),
    ],
)
def test_safe_filename(raw, expected):
    assert _safe_filename(raw) == expected


def test_upload_with_traversal_filename_does_not_touch_files_outside_staging(storage, client, monkeypatch, tmp_path):
    _fake_pipeline(monkeypatch)
    canary = tmp_path / "staging" / "canario.docx"  # donde apuntaria "../canario.docx"
    canary.write_text("original")

    response = client.post(
        "/api/upload", data={"style": "apa"},
        files={"file": ("../canario.docx", _DOCX_BYTES)},
    )

    assert response.status_code == 200
    assert canary.read_text() == "original"


def test_upload_rejects_unknown_style(storage, client):
    response = client.post("/api/upload", data={"style": "mla"}, files={"file": ("a.docx", _DOCX_BYTES)})

    assert response.status_code == 400


def test_upload_list_download_delete_flow(storage, client, monkeypatch):
    _fake_pipeline(monkeypatch)

    uploaded = client.post("/api/upload", data={"style": "ieee"}, files={"file": ("tesis.docx", _DOCX_BYTES)}).json()
    assert uploaded["success"] is True

    listed = client.get("/api/documents").json()
    assert [(d["original_filename"], d["style"], d["success"]) for d in listed] == [("tesis.docx", "ieee", True)]

    download = client.get(f"/api/documents/{uploaded['processing_id']}/download")
    assert download.status_code == 200
    assert download.content == _DOCX_BYTES
    assert "tesis_ieee.docx" in download.headers["content-disposition"]

    assert client.get(f"/api/documents/{uploaded['processing_id']}/preview").status_code == 404
    assert client.delete(f"/api/documents/{uploaded['processing_id']}").json() == {"deleted": True}
    assert client.get("/api/documents").json() == []
    assert client.delete(f"/api/documents/{uploaded['processing_id']}").status_code == 404


def test_conflicting_styles_pause_then_confirm(storage, client, monkeypatch):
    calls = _fake_pipeline(monkeypatch, conflict_first=True)

    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)}).json()
    assert paused["error_code"] == "CONFLICTING_STYLES"
    assert paused["pending_id"] == paused["processing_id"]
    assert client.get("/api/documents").json() == []  # aun no se persiste

    confirmed = client.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite").json()

    assert confirmed["success"] is True
    assert confirmed["processing_id"] != paused["pending_id"]
    assert [c["overwrite"] for c in calls] == [False, True]
    assert len(client.get("/api/documents").json()) == 1


def test_conflicting_styles_cancel_discards_upload(storage, client, monkeypatch):
    _fake_pipeline(monkeypatch, conflict_first=True)
    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)}).json()

    assert client.post(f"/api/documents/{paused['pending_id']}/cancel-overwrite").json() == {"cancelled": True}
    assert client.post(f"/api/documents/{paused['pending_id']}/cancel-overwrite").status_code == 404
    assert client.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite").status_code == 404
    assert client.get("/api/documents").json() == []


@pytest.mark.parametrize("path", ["../mostrador", "no-existe", "..%5Cmostrador"])
def test_invalid_document_ids_are_not_found(storage, client, path):
    assert client.get(f"/api/documents/{path}/download").status_code == 404
    assert client.delete(f"/api/documents/{path}").status_code in (404, 307)


def test_staging_directory_is_cleaned_after_upload(storage, client, monkeypatch, tmp_path):
    _fake_pipeline(monkeypatch)

    client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)})

    assert list((tmp_path / "staging").iterdir()) == []


class _BusyLock:
    """Simula un documento en proceso: el candado aparece tomado."""

    def locked(self):
        return True


def test_upload_is_rejected_while_another_document_is_processing(storage, client, monkeypatch, tmp_path):
    calls = _fake_pipeline(monkeypatch)
    monkeypatch.setattr(routes, "_PROCESSING_LOCK", _BusyLock())

    response = client.post("/api/upload", data={"style": "mejora"}, files={"file": ("a.docx", _DOCX_BYTES)})

    assert response.status_code == 409
    assert calls == []
    assert list((tmp_path / "staging").iterdir()) == []  # no queda nada en staging


def test_confirm_overwrite_is_rejected_while_busy_and_keeps_the_pending_upload(storage, client, monkeypatch):
    _fake_pipeline(monkeypatch, conflict_first=True)
    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)}).json()
    monkeypatch.setattr(routes, "_PROCESSING_LOCK", _BusyLock())

    response = client.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite")

    assert response.status_code == 409
    assert paused["pending_id"] in routes._PENDING_OVERWRITES


def test_improvement_style_is_accepted(storage, client, monkeypatch):
    _fake_pipeline(monkeypatch)

    uploaded = client.post("/api/upload", data={"style": "mejora"}, files={"file": ("a.docx", _DOCX_BYTES)}).json()

    assert uploaded["success"] is True
    assert client.get("/api/documents").json()[0]["style"] == "mejora"

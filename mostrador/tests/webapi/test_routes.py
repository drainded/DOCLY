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
_SID = "11111111-1111-4111-8111-111111111111"
_OTHER_SID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Directorio de la sesion de prueba (_SID): {raiz}/{_SID}. La raiz va en MOSTRADOR_STORAGE_DIR."""
    root = tmp_path / "storage"
    monkeypatch.setenv("MOSTRADOR_STORAGE_DIR", str(root))
    monkeypatch.setattr(
        routes, "_build_config",
        lambda style, output_dir: ProcessingConfig(gemini_api_key="k", style=style, output_dir=output_dir),
    )
    directory = root / _SID
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(staging))  # mkdtemp de las subidas
    routes._PENDING_OVERWRITES.clear()
    return directory


@pytest.fixture
def client():
    test_client = TestClient(app)
    test_client.params = {"sid": _SID}  # toda llamada de la sesion de prueba lleva su id
    return test_client


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


# --- vista previa en PDF -----------------------------------------------------------------

def _upload_ok(client, monkeypatch, name="tesis.docx"):
    _fake_pipeline(monkeypatch)
    return client.post("/api/upload", data={"style": "apa"}, files={"file": (name, _DOCX_BYTES)}).json()


def _fake_render_pdf(monkeypatch):
    calls = []

    def render(docx_path, output_path, libreoffice_bin):
        calls.append(docx_path.name)
        output_path.write_bytes(b"%PDF-1.7 falso")

    monkeypatch.setattr(routes, "render_pdf", render)
    return calls


def test_pdf_is_generated_on_demand_and_served_inline(storage, client, monkeypatch):
    uploaded = _upload_ok(client, monkeypatch)
    calls = _fake_render_pdf(monkeypatch)

    response = client.get(f"/api/documents/{uploaded['processing_id']}/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"%PDF-1.7 falso"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline") and "tesis_apa.pdf" in disposition
    assert calls == [f"{uploaded['processing_id']}.docx"]


def test_pdf_is_cached_after_the_first_conversion(storage, client, monkeypatch):
    uploaded = _upload_ok(client, monkeypatch)
    calls = _fake_render_pdf(monkeypatch)

    first = client.get(f"/api/documents/{uploaded['processing_id']}/pdf")
    second = client.get(f"/api/documents/{uploaded['processing_id']}/pdf")

    assert first.status_code == second.status_code == 200
    assert len(calls) == 1


def test_pdf_conversion_failure_answers_503_without_leaving_a_file(storage, client, monkeypatch):
    from engine.core.exceptions import PreviewRenderError

    uploaded = _upload_ok(client, monkeypatch)

    def render(docx_path, output_path, libreoffice_bin):
        raise PreviewRenderError(returncode=1, stderr="fallo simulado")

    monkeypatch.setattr(routes, "render_pdf", render)

    response = client.get(f"/api/documents/{uploaded['processing_id']}/pdf")

    assert response.status_code == 503
    assert "docx" in response.json()["detail"]
    assert not (storage / f"{uploaded['processing_id']}.pdf").exists()


def test_pdf_of_unknown_document_is_not_found(storage, client):
    assert client.get(f"/api/documents/{uuid.uuid4()}/pdf").status_code == 404
    assert client.get("/api/documents/no-existe/pdf").status_code == 404


def test_pdf_of_a_failed_document_is_not_found(storage, client, monkeypatch):
    from engine.document import store as store_module
    from engine.document.models import FormatStyle

    result = ProcessingResult(processing_id=str(uuid.uuid4()))  # success=False: no hay .docx
    original = storage.parent / "a.docx"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(_DOCX_BYTES)
    store_module.save_processed_document(storage, original, "a.docx", FormatStyle.APA, result)
    calls = _fake_render_pdf(monkeypatch)

    assert client.get(f"/api/documents/{result.processing_id}/pdf").status_code == 404
    assert calls == []


def test_deleting_a_document_also_removes_its_pdf(storage, client, monkeypatch):
    uploaded = _upload_ok(client, monkeypatch)
    _fake_render_pdf(monkeypatch)
    client.get(f"/api/documents/{uploaded['processing_id']}/pdf")
    assert (storage / f"{uploaded['processing_id']}.pdf").exists()

    client.delete(f"/api/documents/{uploaded['processing_id']}")

    assert list(storage.glob(f"{uploaded['processing_id']}*")) == []


# --- sesiones efimeras -------------------------------------------------------------------

def _as_session(sid):
    other = TestClient(app)
    other.params = {"sid": sid}
    return other


def test_a_session_only_sees_its_own_documents(storage, client, monkeypatch):
    uploaded = _upload_ok(client, monkeypatch)
    _fake_render_pdf(monkeypatch)
    other = _as_session(_OTHER_SID)
    doc_id = uploaded["processing_id"]

    assert other.get("/api/documents").json() == []
    assert other.get(f"/api/documents/{doc_id}/download").status_code == 404
    assert other.get(f"/api/documents/{doc_id}/pdf").status_code == 404
    assert other.delete(f"/api/documents/{doc_id}").status_code == 404
    assert len(client.get("/api/documents").json()) == 1  # y el dueno sigue teniendolo


def test_sid_is_required_and_must_be_a_uuid4(storage, client):
    bare = TestClient(app)

    assert bare.get("/api/documents").status_code == 422  # falta sid
    assert bare.get("/api/documents", params={"sid": "../../etc"}).status_code == 400
    assert bare.get("/api/documents", params={"sid": "no-es-uuid"}).status_code == 400
    assert bare.post("/api/session/end", params={"sid": ".."}).status_code == 400


def test_documents_are_stored_inside_the_session_directory(storage, client, monkeypatch):
    uploaded = _upload_ok(client, monkeypatch)

    assert (storage / f"{uploaded['processing_id']}.docx").exists()
    assert (storage.parent / f"{uploaded['processing_id']}.docx").exists() is False


def test_ending_the_session_deletes_its_files_and_pending_uploads(storage, client, monkeypatch, tmp_path):
    _fake_pipeline(monkeypatch)
    client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)})
    _fake_pipeline(monkeypatch, conflict_first=True)
    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("b.docx", _DOCX_BYTES)}).json()
    assert storage.is_dir() and paused["pending_id"] in routes._PENDING_OVERWRITES

    response = client.post("/api/session/end")

    assert response.json() == {"ended": True, "deleted": True}
    assert not storage.exists()
    assert routes._PENDING_OVERWRITES == {}
    assert list((tmp_path / "staging").iterdir()) == []


def test_ending_one_session_leaves_the_others_untouched(storage, client, monkeypatch):
    _upload_ok(client, monkeypatch)
    other = _as_session(_OTHER_SID)
    _fake_pipeline(monkeypatch)
    other.post("/api/upload", data={"style": "apa"}, files={"file": ("o.docx", _DOCX_BYTES)})

    client.post("/api/session/end")

    assert client.get("/api/documents").json() == []
    assert len(other.get("/api/documents").json()) == 1


def test_ending_a_session_without_files_is_harmless(storage, client):
    assert client.post("/api/session/end").json() == {"ended": True, "deleted": False}


def test_pending_upload_of_another_session_cannot_be_confirmed_or_cancelled(storage, client, monkeypatch):
    _fake_pipeline(monkeypatch, conflict_first=True)
    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)}).json()
    other = _as_session(_OTHER_SID)

    assert other.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite").status_code == 404
    assert other.post(f"/api/documents/{paused['pending_id']}/cancel-overwrite").status_code == 404
    assert paused["pending_id"] in routes._PENDING_OVERWRITES  # sigue pendiente para su dueno


def test_sweep_expired_removes_idle_sessions_and_stale_pending_uploads(storage, client, monkeypatch):
    import os
    import time

    _upload_ok(client, monkeypatch)
    _fake_pipeline(monkeypatch, conflict_first=True)
    paused = client.post("/api/upload", data={"style": "apa"}, files={"file": ("b.docx", _DOCX_BYTES)}).json()
    monkeypatch.setenv("MOSTRADOR_SESSION_TTL_MINUTES", "60")

    assert routes.sweep_expired() == 0  # todo es reciente
    assert storage.is_dir() and paused["pending_id"] in routes._PENDING_OVERWRITES

    old = time.time() - 2 * 3600
    os.utime(storage, (old, old))
    routes._PENDING_OVERWRITES[paused["pending_id"]].created -= 2 * 3600

    assert routes.sweep_expired() == 1
    assert not storage.exists()
    assert routes._PENDING_OVERWRITES == {}

"""
tests/document/test_store.py
==============================
Tests de engine/document/store.py (seccion 9: almacenamiento y
eliminacion de documentos procesados).
"""

from engine.document.models import FormatStyle, ProcessingResult
from engine.document import store


def _make_result(processing_id: str, success: bool = True, **kwargs) -> ProcessingResult:
    return ProcessingResult(processing_id=processing_id, success=success, **kwargs)


class TestSaveAndRetrieve:
    def test_save_then_get_round_trips(self, tmp_path):
        original = tmp_path / "mi_trabajo.docx"
        original.write_bytes(b"contenido original")
        storage_dir = tmp_path / "storage"

        result = _make_result("11111111-2222-4333-8444-555555555555")
        saved = store.save_processed_document(
            storage_dir, original, "mi_trabajo.docx", FormatStyle.APA, result
        )

        fetched = store.get_document(storage_dir, result.processing_id)
        assert fetched == saved
        assert fetched.original_filename == "mi_trabajo.docx"
        assert fetched.style == FormatStyle.APA
        assert fetched.success is True

    def test_original_file_is_copied_not_moved(self, tmp_path):
        original = tmp_path / "mi_trabajo.docx"
        original.write_bytes(b"contenido original")
        storage_dir = tmp_path / "storage"

        result = _make_result("22222222-2222-4333-8444-555555555555")
        saved = store.save_processed_document(
            storage_dir, original, "mi_trabajo.docx", FormatStyle.APA, result
        )

        assert original.exists()  # el original del caller no se toca
        assert saved.original_path(storage_dir).read_bytes() == b"contenido original"

    def test_failed_result_is_still_persisted(self, tmp_path):
        original = tmp_path / "corrupto.docx"
        original.write_bytes(b"no es un docx valido")
        storage_dir = tmp_path / "storage"

        result = _make_result(
            "33333333-2222-4333-8444-555555555555",
            success=False, error_code="DOCUMENT_CORRUPTED",
            error_message="El documento esta corrupto.",
        )
        saved = store.save_processed_document(
            storage_dir, original, "corrupto.docx", FormatStyle.IEEE, result
        )

        assert saved.success is False
        assert saved.error_code == "DOCUMENT_CORRUPTED"
        assert saved.output_path(storage_dir) is None  # nunca hay .docx de salida si fallo


class TestListDocuments:
    def test_empty_storage_dir_returns_empty_list(self, tmp_path):
        assert store.list_documents(tmp_path / "no-existe-aun") == []

    def test_lists_most_recent_first(self, tmp_path):
        storage_dir = tmp_path / "storage"
        original = tmp_path / "doc.docx"
        original.write_bytes(b"x")

        first = store.save_processed_document(
            storage_dir, original, "doc.docx", FormatStyle.APA,
            _make_result("11111111-2222-4333-8444-555555555555"),
        )
        second = store.save_processed_document(
            storage_dir, original, "doc.docx", FormatStyle.APA,
            _make_result("22222222-2222-4333-8444-555555555555"),
        )
        # forzar orden temporal explicito para no depender de la resolucion del reloj
        first.created_at, second.created_at = second.created_at, first.created_at
        store._write_meta(storage_dir, first)
        store._write_meta(storage_dir, second)

        documents = store.list_documents(storage_dir)
        assert [d.processing_id for d in documents] == [first.processing_id, second.processing_id]

    def test_corrupt_meta_file_is_skipped(self, tmp_path):
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        (storage_dir / "11111111-2222-4333-8444-555555555555.meta.json").write_text("esto no es json")

        assert store.list_documents(storage_dir) == []


class TestDeleteDocument:
    def test_delete_removes_all_related_files(self, tmp_path):
        original = tmp_path / "doc.docx"
        original.write_bytes(b"x")
        storage_dir = tmp_path / "storage"

        result = _make_result("11111111-2222-4333-8444-555555555555")
        store.save_processed_document(storage_dir, original, "doc.docx", FormatStyle.APA, result)

        deleted = store.delete_document(storage_dir, result.processing_id)

        assert deleted is True
        assert store.get_document(storage_dir, result.processing_id) is None
        assert list(storage_dir.glob(f"{result.processing_id}*")) == []

    def test_delete_nonexistent_document_returns_false(self, tmp_path):
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        assert store.delete_document(storage_dir, "11111111-2222-4333-8444-555555555555") is False

    def test_delete_is_idempotent(self, tmp_path):
        original = tmp_path / "doc.docx"
        original.write_bytes(b"x")
        storage_dir = tmp_path / "storage"
        result = _make_result("11111111-2222-4333-8444-555555555555")
        store.save_processed_document(storage_dir, original, "doc.docx", FormatStyle.APA, result)

        assert store.delete_document(storage_dir, result.processing_id) is True
        assert store.delete_document(storage_dir, result.processing_id) is False


class TestPathTraversalProtection:
    """processing_id llega desde una URL HTTP — debe validarse antes de tocar el filesystem."""

    def test_get_document_rejects_traversal_id(self, tmp_path):
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        assert store.get_document(storage_dir, "../../etc/passwd") is None

    def test_delete_document_rejects_traversal_id(self, tmp_path):
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        # crea un archivo fuera de storage_dir que un ataque de traversal podria intentar borrar
        victim = tmp_path / "victima.txt"
        victim.write_text("no me borres")

        assert store.delete_document(storage_dir, "../victima") is False
        assert victim.exists()

    def test_get_document_rejects_malformed_id(self, tmp_path):
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        assert store.get_document(storage_dir, "no-es-un-uuid") is None

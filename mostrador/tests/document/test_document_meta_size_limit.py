"""
tests/document/test_document_meta_size_limit.py
=================================================
Regresion: DocumentMeta.exceeds_size_limit()/rejection_reason() deben
respetar el limite inyectado via ProcessingConfig.max_file_size_bytes en vez
de la constante de clase DocumentMeta.MAX_FILE_SIZE_BYTES (hardcodeada,
init=False) cuando se les pasa un config (Regla §9.1: toda configuracion
debe fluir a traves de ProcessingConfig, nunca quedar fija dentro de engine/).

Bug historico corregido: DocumentMeta.MAX_FILE_SIZE_BYTES y
ProcessingConfig.max_file_size_bytes eran dos literales `50 * 1024 * 1024`
independientes que solo coincidian por casualidad. Ahora ambos derivan de
la misma constante (models.DEFAULT_MAX_FILE_SIZE_BYTES), por lo que no
pueden divergir si en el futuro se cambia el limite por defecto.
"""

import pytest

from models import DocumentMeta, ProcessingConfig


class TestSizeLimitConsistency:
    def test_default_size_limits_agree(self):
        """Sanity check: con valores default, ambos limites coinciden (50 MB)."""
        meta = DocumentMeta(file_size_bytes=10 * 1024 * 1024)
        config = ProcessingConfig()
        assert meta.MAX_FILE_SIZE_BYTES == config.max_file_size_bytes

    def test_custom_config_limit_is_ignored_by_document_meta(self):
        """
        Si el caller inyecta un limite mas bajo via ProcessingConfig
        (por ejemplo, 5 MB para un plan gratuito), DocumentMeta debe
        respetarlo en vez de usar su propia constante de 50 MB.
        """
        five_mb = 5 * 1024 * 1024
        config = ProcessingConfig(max_file_size_bytes=five_mb)

        # Documento de 8 MB: DEBERIA exceder el limite inyectado (5 MB)
        meta = DocumentMeta(file_size_bytes=8 * 1024 * 1024)

        # Comportamiento deseado (fuente de verdad = ProcessingConfig):
        expected_exceeds = meta.file_size_bytes > config.max_file_size_bytes
        assert expected_exceeds is True  # 8 MB > 5 MB -> deberia rechazarse

        # Comportamiento real de DocumentMeta.exceeds_size_limit() con el config inyectado:
        actual_exceeds = meta.exceeds_size_limit(config)

        assert actual_exceeds == expected_exceeds, (
            f"DocumentMeta.exceeds_size_limit() devolvio {actual_exceeds} "
            f"pero deberia devolver {expected_exceeds} segun el limite "
            f"inyectado en ProcessingConfig ({config.max_file_size_bytes} bytes). "
            f"DocumentMeta esta usando su propia constante hardcodeada "
            f"({meta.MAX_FILE_SIZE_BYTES} bytes) en vez del valor de config."
        )

    def test_rejection_reason_does_not_reflect_injected_limit(self):
        """
        Misma regla, a nivel de rejection_reason(): un documento de 8 MB
        no debe ser aceptado si el plan del usuario limita a 5 MB.
        """
        config = ProcessingConfig(max_file_size_bytes=5 * 1024 * 1024)
        meta = DocumentMeta(file_size_bytes=8 * 1024 * 1024)

        reason = meta.rejection_reason(config)

        assert reason is not None, (
            "rejection_reason() devolvio None (documento aceptado) para un "
            "archivo de 8 MB con un limite de plan de 5 MB. El metodo no "
            "tiene forma de conocer el limite inyectado en ProcessingConfig."
        )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))

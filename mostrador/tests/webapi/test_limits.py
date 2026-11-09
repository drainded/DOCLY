"""
tests/webapi/test_limits.py
=============================
Tests del limite diario de documentos (webapp/api/limits.py y su uso en routes.py).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from engine.document.models import DocumentMeta, ProcessingConfig, ProcessingResult
from webapp.api import limits, routes
from webapp.main import app

_DOCX_BYTES = b"PK\x03\x04 contenido de prueba"
_SID = "11111111-1111-4111-8111-111111111111"


# --- DailyLimiter ------------------------------------------------------------------------

class _Day:
    def __init__(self, value="2026-11-09"):
        self.value = value

    def __call__(self):
        return self.value


def test_limiter_counts_per_ip():
    limiter = limits.DailyLimiter(lambda: 3, today=_Day())

    limiter.record("1.1.1.1")
    limiter.record("1.1.1.1")
    limiter.record("2.2.2.2")

    assert limiter.remaining("1.1.1.1") == 1
    assert limiter.remaining("2.2.2.2") == 2
    assert limiter.remaining("3.3.3.3") == 3


def test_limiter_is_exhausted_exactly_at_the_limit():
    limiter = limits.DailyLimiter(lambda: 2, today=_Day())

    limiter.record("1.1.1.1")
    assert not limiter.is_exhausted("1.1.1.1")
    limiter.record("1.1.1.1")
    assert limiter.is_exhausted("1.1.1.1")
    assert limiter.remaining("1.1.1.1") == 0


def test_limiter_resets_when_the_utc_day_changes():
    day = _Day("2026-11-09")
    limiter = limits.DailyLimiter(lambda: 1, today=day)
    limiter.record("1.1.1.1")
    assert limiter.is_exhausted("1.1.1.1")

    day.value = "2026-11-10"

    assert limiter.remaining("1.1.1.1") == 1


def test_limit_zero_means_unlimited():
    limiter = limits.DailyLimiter(lambda: 0, today=_Day())
    for _ in range(50):
        limiter.record("1.1.1.1")

    assert limiter.remaining("1.1.1.1") is None
    assert not limiter.is_exhausted("1.1.1.1")


# --- IP del visitante --------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, forwarded=None, host="10.0.0.1"):
        self.headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
        self.client = type("Client", (), {"host": host})()


def test_client_ip_ignores_forwarded_header_without_trusted_proxies():
    request = _FakeRequest(forwarded="6.6.6.6", host="10.0.0.1")

    assert limits.client_ip(request, trusted_hops=0) == "10.0.0.1"


def test_client_ip_takes_the_entry_added_by_the_nearest_trusted_proxy():
    # El cliente puede escribir las primeras entradas; la ultima la anade nuestro proxy.
    request = _FakeRequest(forwarded="6.6.6.6, 203.0.113.9")

    assert limits.client_ip(request, trusted_hops=1) == "203.0.113.9"


def test_client_ip_with_two_proxies_skips_the_inner_one():
    request = _FakeRequest(forwarded="6.6.6.6, 203.0.113.9, 172.16.0.5")

    assert limits.client_ip(request, trusted_hops=2) == "203.0.113.9"


def test_client_ip_falls_back_to_the_connection_when_the_header_is_missing_or_short():
    assert limits.client_ip(_FakeRequest(), trusted_hops=1) == "10.0.0.1"
    assert limits.client_ip(_FakeRequest(forwarded="203.0.113.9"), trusted_hops=2) == "10.0.0.1"


def test_auto_mode_takes_the_rightmost_public_ip_skipping_internal_proxies():
    # cliente real, y despues proxies internos con direcciones privadas / de red compartida
    request = _FakeRequest(forwarded="8.8.8.8, 10.20.30.40, 100.64.1.2")

    assert limits.client_ip(request, trusted_hops="auto") == "8.8.8.8"


def test_auto_mode_ignores_what_the_client_wrote_to_the_left():
    request = _FakeRequest(forwarded="9.9.9.9, 8.8.8.8, 10.0.0.2")

    assert limits.client_ip(request, trusted_hops="auto") == "8.8.8.8"


def test_auto_mode_ignores_garbage_and_falls_back_to_the_connection():
    assert limits.client_ip(_FakeRequest(forwarded="no-es-ip, 10.0.0.2"), trusted_hops="auto") == "10.0.0.1"
    assert limits.client_ip(_FakeRequest(), trusted_hops="auto") == "10.0.0.1"


@pytest.mark.parametrize("raw, expected", [("auto", "auto"), (" AUTO ", "auto"), ("2", 2), ("0", 0), ("-3", 0)])
def test_parse_trusted_hops(raw, expected):
    assert limits.parse_trusted_hops(raw) == expected


class _HeaderRequest(_FakeRequest):
    def __init__(self, headers, host="10.0.0.1"):
        super().__init__(host=host)
        self.headers = headers


def test_trusted_header_wins_over_forwarded_for():
    request = _HeaderRequest({"cf-connecting-ip": "8.8.8.8", "x-forwarded-for": "9.9.9.9, 8.8.4.4"})

    assert limits.client_ip(request, trusted_hops="auto", trusted_header="cf-connecting-ip") == "8.8.8.8"


def test_trusted_header_missing_or_invalid_falls_back_to_forwarded_for():
    request = _HeaderRequest({"cf-connecting-ip": "no-es-ip", "x-forwarded-for": "8.8.4.4, 10.0.0.2"})
    assert limits.client_ip(request, trusted_hops="auto", trusted_header="cf-connecting-ip") == "8.8.4.4"

    request = _HeaderRequest({"x-forwarded-for": "8.8.4.4, 10.0.0.2"})
    assert limits.client_ip(request, trusted_hops="auto", trusted_header="cf-connecting-ip") == "8.8.4.4"


def test_header_is_ignored_when_none_is_configured():
    request = _HeaderRequest({"cf-connecting-ip": "8.8.8.8"})

    assert limits.client_ip(request, trusted_hops=0) == "10.0.0.1"


# --- Endpoints ---------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setenv("MOSTRADOR_STORAGE_DIR", str(root))
    monkeypatch.setenv("MOSTRADOR_DAILY_LIMIT", "3")
    monkeypatch.delenv("MOSTRADOR_TRUSTED_PROXY_HOPS", raising=False)
    monkeypatch.setattr(
        routes, "_build_config",
        lambda style, output_dir: ProcessingConfig(gemini_api_key="k", style=style, output_dir=output_dir),
    )
    routes._LIMITER.reset()
    routes._PENDING_OVERWRITES.clear()
    client = TestClient(app)
    client.params = {"sid": _SID}
    yield client
    routes._LIMITER.reset()


def _pipeline(monkeypatch, outcome="ok"):
    """outcome: ok | fail (error tras validar) | conflict (primera pasada)."""
    def run(doc_path, config, *, overwrite_styles=False):
        result = ProcessingResult(processing_id=str(uuid.uuid4()))
        if outcome == "conflict" and not overwrite_styles:
            result.error_code = "CONFLICTING_STYLES"
            return result
        if outcome == "fail":
            result.error_code = "DOCUMENT_CORRUPTED"
            result.error_message = "corrupto"
            return result
        config.output_dir.mkdir(parents=True, exist_ok=True)
        output = config.output_dir / f"{result.processing_id}.docx"
        output.write_bytes(_DOCX_BYTES)
        result.success = True
        result.output_docx_path = output
        result.doc_meta = DocumentMeta(processing_id=result.processing_id)
        return result

    monkeypatch.setattr(routes.pipeline, "run", run)


def _upload(client, headers=None):
    return client.post(
        "/api/upload", data={"style": "apa"}, files={"file": ("a.docx", _DOCX_BYTES)}, headers=headers or {},
    )


def test_fourth_document_of_the_day_is_rejected_with_429(api, monkeypatch):
    _pipeline(monkeypatch)

    assert [_upload(api).status_code for _ in range(3)] == [200, 200, 200]
    blocked = _upload(api)

    assert blocked.status_code == 429
    assert "3 documentos por día" in blocked.json()["detail"]
    assert len(api.get("/api/documents").json()) == 3  # el cuarto no se proceso ni se guardo


def test_limits_endpoint_reports_what_is_left(api, monkeypatch):
    _pipeline(monkeypatch)
    assert api.get("/api/limits").json() == {"daily_limit": 3, "remaining": 3, "max_file_mb": 50.0}

    _upload(api)

    assert api.get("/api/limits").json()["remaining"] == 2


def test_limits_endpoint_without_a_limit(api, monkeypatch):
    monkeypatch.setenv("MOSTRADOR_DAILY_LIMIT", "0")

    body = api.get("/api/limits").json()

    assert body["daily_limit"] is None and body["remaining"] is None


def test_max_file_size_reported_follows_the_environment(api, monkeypatch):
    monkeypatch.setenv("MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024))

    assert api.get("/api/limits").json()["max_file_mb"] == 10.0


def test_failed_documents_do_not_use_up_the_quota(api, monkeypatch):
    _pipeline(monkeypatch, "fail")
    for _ in range(5):
        assert _upload(api).status_code == 200  # el fallo viaja en el cuerpo, no es un 429

    assert api.get("/api/limits").json()["remaining"] == 3


def test_conflict_pause_does_not_count_but_the_confirmed_run_does(api, monkeypatch):
    _pipeline(monkeypatch, "conflict")

    paused = _upload(api).json()
    assert api.get("/api/limits").json()["remaining"] == 3

    confirmed = api.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite").json()

    assert confirmed["success"] is True
    assert api.get("/api/limits").json()["remaining"] == 2


def test_confirm_overwrite_is_also_blocked_when_the_quota_is_used_up(api, monkeypatch):
    _pipeline(monkeypatch, "conflict")
    paused = _upload(api).json()
    for _ in range(3):
        routes._LIMITER.record("testclient")

    response = api.post(f"/api/documents/{paused['pending_id']}/confirm-overwrite")

    assert response.status_code == 429
    assert paused["pending_id"] in routes._PENDING_OVERWRITES  # sigue pendiente


def test_each_ip_has_its_own_quota_behind_a_proxy(api, monkeypatch):
    monkeypatch.setenv("MOSTRADOR_TRUSTED_PROXY_HOPS", "1")
    _pipeline(monkeypatch)
    ana = {"x-forwarded-for": "203.0.113.1"}
    beto = {"x-forwarded-for": "203.0.113.2"}

    for _ in range(3):
        assert _upload(api, ana).status_code == 200

    assert _upload(api, ana).status_code == 429
    assert _upload(api, beto).status_code == 200
    assert api.get("/api/limits", headers=beto).json()["remaining"] == 2


def test_spoofed_forwarded_header_cannot_dodge_the_limit(api, monkeypatch):
    monkeypatch.setenv("MOSTRADOR_TRUSTED_PROXY_HOPS", "1")
    _pipeline(monkeypatch)

    for n in range(3):
        # el cliente escribe una IP distinta cada vez; el proxy anade la verdadera al final
        assert _upload(api, {"x-forwarded-for": f"9.9.9.{n}, 203.0.113.1"}).status_code == 200

    assert _upload(api, {"x-forwarded-for": "9.9.9.99, 203.0.113.1"}).status_code == 429


def test_health_answers_immediately():
    response = TestClient(app).get("/health")

    assert response.status_code == 200 and response.json() == {"status": "ok"}


# 203.0.113.x es un rango de documentacion (no es "global" para Python): el modo auto usa IPs publicas reales.
def test_auto_mode_through_the_endpoint(api, monkeypatch):
    monkeypatch.setenv("MOSTRADOR_TRUSTED_PROXY_HOPS", "auto")
    _pipeline(monkeypatch)
    ana = {"x-forwarded-for": "8.8.8.1, 10.1.1.1"}
    beto = {"x-forwarded-for": "8.8.4.4, 10.1.1.1"}

    for _ in range(3):
        assert _upload(api, ana).status_code == 200

    assert _upload(api, ana).status_code == 429
    assert _upload(api, beto).status_code == 200


def test_trusted_header_through_the_endpoint(api, monkeypatch):
    monkeypatch.setenv("MOSTRADOR_CLIENT_IP_HEADER", "CF-Connecting-IP")  # se normaliza a minusculas
    _pipeline(monkeypatch)
    ana = {"cf-connecting-ip": "8.8.8.1"}
    beto = {"cf-connecting-ip": "8.8.4.4"}

    for _ in range(3):
        assert _upload(api, ana).status_code == 200

    assert _upload(api, ana).status_code == 429
    assert _upload(api, beto).status_code == 200

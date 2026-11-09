"""
tests/webapi/test_sessions.py
===============================
Tests de webapp/api/sessions.py: validacion del id de sesion, borrado y caducidad.
"""

import os
import time

import pytest

from webapp.api import sessions

_SID = "11111111-1111-4111-8111-111111111111"
_OTHER = "22222222-2222-4222-8222-222222222222"


@pytest.mark.parametrize(
    "sid",
    [_SID, "9f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f"],
)
def test_valid_session_ids(sid):
    assert sessions.is_valid_sid(sid)


@pytest.mark.parametrize(
    "sid",
    [
        "",
        "..",
        "../../etc/passwd",
        "11111111-1111-4111-8111-11111111111",  # un caracter menos
        "11111111-1111-1111-8111-111111111111",  # version 1, no 4
        "11111111-1111-4111-1111-111111111111",  # variante invalida
        "11111111-1111-4111-8111-111111111111/..",
        "11111111-1111-4111-8111-11111111111G",
        "11111111-1111-4111-8111-111111111111\n",
    ],
)
def test_invalid_session_ids(sid):
    assert not sessions.is_valid_sid(sid)


def _make_session(root, sid, age_seconds=0):
    directory = sessions.session_dir(root, sid)
    directory.mkdir(parents=True)
    (directory / "doc.docx").write_bytes(b"x")
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(directory, (old, old))
    return directory


def test_delete_session_removes_only_that_session(tmp_path):
    mine = _make_session(tmp_path, _SID)
    other = _make_session(tmp_path, _OTHER)

    assert sessions.delete_session(tmp_path, _SID) is True

    assert not mine.exists() and other.exists()
    assert sessions.delete_session(tmp_path, _SID) is False  # idempotente


def test_delete_session_rejects_invalid_ids_without_touching_anything(tmp_path):
    victim = tmp_path / "importante"
    victim.mkdir()

    assert sessions.delete_session(tmp_path, "importante") is False
    assert sessions.delete_session(tmp_path, "..") is False
    assert victim.exists()


def test_purge_expired_removes_only_idle_sessions(tmp_path):
    fresh = _make_session(tmp_path, _SID, age_seconds=60)
    stale = _make_session(tmp_path, _OTHER, age_seconds=2 * 3600)

    assert sessions.purge_expired(tmp_path, max_age_seconds=3600) == 1

    assert fresh.exists() and not stale.exists()


def test_purge_expired_leaves_foreign_entries_alone(tmp_path):
    """Archivos sueltos del almacenamiento anterior (sin sesiones) y otras carpetas no se tocan."""
    legacy = tmp_path / "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.docx"
    legacy.write_bytes(b"x")
    other_dir = tmp_path / "otra-carpeta"
    other_dir.mkdir()
    old = time.time() - 10 * 3600
    for path in (legacy, other_dir):
        os.utime(path, (old, old))

    assert sessions.purge_expired(tmp_path, max_age_seconds=3600) == 0

    assert legacy.exists() and other_dir.exists()


def test_purge_expired_on_missing_root_is_a_noop(tmp_path):
    assert sessions.purge_expired(tmp_path / "no-existe", max_age_seconds=1) == 0


def test_touch_keeps_a_session_alive(tmp_path):
    directory = _make_session(tmp_path, _SID, age_seconds=2 * 3600)

    sessions.touch(directory)

    assert sessions.purge_expired(tmp_path, max_age_seconds=3600) == 0
    assert directory.exists()


def test_touch_on_a_missing_directory_does_not_raise(tmp_path):
    sessions.touch(tmp_path / "no-existe")

"""
webapp/api/limits.py
======================
Limite diario de documentos por visitante (unico control de uso del despliegue
gratuito: protege la cuota de Gemini sin pedir cuenta ni clave de acceso).

Reglas
------
- Se cuenta por direccion IP, no por sesion: recargar la pagina (sesion nueva) no
  reinicia el contador.
- Solo cuentan los documentos procesados con exito. Un archivo rechazado (corrupto,
  protegido, demasiado grande) o un fallo del servicio no gasta cupo.
- El dia es el dia UTC: el contador se reinicia a las 00:00 UTC.
- El contador vive en memoria. En un hosting gratuito el servidor se duerme y se
  reinicia, y entonces se pierde: es un freno razonable contra el uso accidental o
  descuidado, no una barrera contra alguien decidido (cambiar de IP o esperar a un
  reinicio lo salta). Si hiciera falta algo firme, habria que persistirlo fuera del
  contenedor.
- `MOSTRADOR_DAILY_LIMIT=0` desactiva el limite.

IP real detras de un proxy
---------------------------
Los hostings ponen un proxy delante: `request.client.host` seria siempre el del
proxy y todos los visitantes compartirian un unico contador. Con
`MOSTRADOR_TRUSTED_PROXY_HOPS=N` se toma la IP de la cabecera X-Forwarded-For, contando
N saltos desde el final (la entrada que anadio el proxy mas cercano a nosotros; las
anteriores las puede escribir el cliente y no son de fiar). Con 0, o sin cabecera,
se usa la direccion de la conexion.

Con `MOSTRADOR_TRUSTED_PROXY_HOPS=auto` (para hostings que no documentan cuantos proxies hay,
como Hugging Face Spaces) se toma la entrada MAS A LA DERECHA que sea una IP publica: los
proxies internos suelen tener direcciones privadas o de red compartida y se saltan solos, y
lo que escriba el cliente queda siempre a la izquierda de lo que anaden los proxies. Si un
proxy intermedio tuviera IP publica, el contador se compartiria por proxy (peor, no
explotable): comprobarlo tras el primer despliegue (ver README).

Cabecera de IP de confianza (`MOSTRADOR_CLIENT_IP_HEADER`)
-----------------------------------------------------------
Render pone Cloudflare delante y el cliente puede escribir X-Forwarded-For, que Render no
limpia. Cloudflare SI sobrescribe `CF-Connecting-IP` con la IP real, asi que, si se configura
esa cabecera, tiene prioridad sobre X-Forwarded-For. Solo debe usarse cuando TODO el trafico
pasa por ese proxy: sin el, cualquier cliente podria escribirla. Si la cabecera falta o no
trae una IP valida, se usa X-Forwarded-For como se describio arriba.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import Callable

from fastapi import Request

DEFAULT_DAILY_LIMIT = 3


def _utc_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


class DailyLimiter:
    """Contador de documentos por IP y dia UTC (en memoria, seguro entre hilos)."""

    def __init__(self, limit_provider: Callable[[], int], today: Callable[[], str] = _utc_day) -> None:
        self._limit_provider = limit_provider
        self._today = today
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._day = today()

    @property
    def limit(self) -> int:
        return self._limit_provider()

    def used(self, ip: str) -> int:
        with self._lock:
            self._roll_day()
            return self._counts.get(ip, 0)

    def remaining(self, ip: str) -> int | None:
        """Documentos que le quedan hoy a `ip`; None si no hay limite."""
        limit = self.limit
        if limit <= 0:
            return None
        return max(0, limit - self.used(ip))

    def is_exhausted(self, ip: str) -> bool:
        remaining = self.remaining(ip)
        return remaining is not None and remaining == 0

    def record(self, ip: str) -> None:
        with self._lock:
            self._roll_day()
            self._counts[ip] = self._counts.get(ip, 0) + 1

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._day = self._today()

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._counts.clear()
            self._day = today


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False  # no es una IP (basura de un cliente): no se considera


def parse_trusted_hops(raw: str) -> int | str:
    """Lee MOSTRADOR_TRUSTED_PROXY_HOPS: un entero (>= 0) o "auto"."""
    value = raw.strip().lower()
    if value == "auto":
        return "auto"
    return max(0, int(value))


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def client_ip(request: Request, trusted_hops: int | str, trusted_header: str = "") -> str:
    """IP del visitante (ver el docstring del modulo sobre proxies)."""
    if trusted_header:
        value = request.headers.get(trusted_header, "").strip()
        if value and _valid_ip(value):
            return value
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if trusted_hops == "auto":
        for entry in reversed(forwarded):
            if _is_public_ip(entry):
                return entry
    elif trusted_hops > 0 and len(forwarded) >= trusted_hops:
        return forwarded[-trusted_hops]
    return request.client.host if request.client else "desconocida"

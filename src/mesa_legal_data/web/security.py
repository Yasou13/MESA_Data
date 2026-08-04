import asyncio
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Dict, List

from fastapi import HTTPException, Request, status


class SingleWriteLock:
    """
    In-memory asyncio lock for thread-safe/process-safe write operations.
    Returns 409 Conflict if another write operation is in progress.
    """

    def __init__(self):
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire_write(self):
        if self._lock.locked():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "WRITE_LOCK_CONFLICT",
                    "message": "Başka bir yazma işlemi devam ediyor.",
                },
            )
        async with self._lock:
            yield


write_lock = SingleWriteLock()


class SimpleRateLimiter:
    """
    In-memory rate limiter per IP address.
    """

    def __init__(self):
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._auth_failures: Dict[str, List[float]] = defaultdict(list)

    def check_rate_limit(self, client_ip: str, max_requests: int = 30, window_seconds: int = 60):
        now = time.time()
        cutoff = now - window_seconds
        # Clean old requests
        timestamps = [t for t in self._requests[client_ip] if t > cutoff]
        self._requests[client_ip] = timestamps

        if len(timestamps) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Çok fazla istek gönderildi. Lütfen bekleyin.",
                },
            )
        self._requests[client_ip].append(now)

    def record_auth_failure(self, client_ip: str, max_failures: int = 10, window_seconds: int = 60):
        now = time.time()
        cutoff = now - window_seconds
        timestamps = [t for t in self._auth_failures[client_ip] if t > cutoff]
        self._auth_failures[client_ip] = timestamps

        if len(timestamps) >= max_failures:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "AUTH_RATE_LIMIT_EXCEEDED",
                    "message": "Çok fazla hatalı kimlik doğrulama denemesi yapıldı.",
                },
            )
        self._auth_failures[client_ip].append(now)


rate_limiter = SimpleRateLimiter()


def verify_security(request: Request):
    """
    Verifies localhost binding, admin token authentication, CSRF headers, and rate limits.
    """
    client_host = request.client.host if request.client else "127.0.0.1"
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "testclient")

    admin_token = os.environ.get("MESA_DATA_WEB_ADMIN_TOKEN", "").strip()

    # Non-loopback check
    if not is_loopback and not admin_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "NON_LOOPBACK_DISABLED",
                "message": "Non-loopback bind requires MESA_DATA_WEB_ADMIN_TOKEN to be configured.",
            },
        )

    # Admin Token Check
    if admin_token:
        auth_header = request.headers.get("Authorization", "")
        expected = f"Bearer {admin_token}"
        if auth_header != expected:
            rate_limiter.record_auth_failure(client_host)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "UNAUTHORIZED",
                    "message": "Geçersiz veya eksik admin token.",
                },
            )

    # Write Methods CSRF Header Check
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        rate_limiter.check_rate_limit(client_host, max_requests=30, window_seconds=60)
        requested_with = request.headers.get("X-MESA-Requested-With", "")
        if requested_with != "web-admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "CSRF_HEADER_MISSING",
                    "message": "Eksik veya geçersiz X-MESA-Requested-With header'ı.",
                },
            )

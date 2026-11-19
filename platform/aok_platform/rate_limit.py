"""Limitadores de tentativas compartilhados no banco (ou em memória quando factory=None)."""

from __future__ import annotations

import contextlib
import random
import threading
import time
import weakref
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import StaticPool, delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .auth import hash_token
from .models import RateLimitEntry

MAX_FAILURES = 5
LOCK_SECONDS = 300
HOUR = 3600
DEFAULT_PRUNE_EVERY = 64
_MAX_DB_RETRIES = 32

T = TypeVar("T")

_STATIC_POOL_LOCKS_GUARD = threading.Lock()
_STATIC_POOL_LOCKS: weakref.WeakKeyDictionary[object, threading.Lock] = weakref.WeakKeyDictionary()


def _engine_lock(factory: sessionmaker[Session]) -> contextlib.AbstractContextManager[None]:
    """Serializa acesso em memória quando o engine usa StaticPool (SQLite :memory:)."""
    bind = factory.kw.get("bind")
    if bind is not None and isinstance(getattr(bind, "pool", None), StaticPool):
        with _STATIC_POOL_LOCKS_GUARD:
            lock = _STATIC_POOL_LOCKS.get(bind)
            if lock is None:
                lock = threading.Lock()
                _STATIC_POOL_LOCKS[bind] = lock
        return lock
    return contextlib.nullcontext()


def _is_sqlite_lock_error(s: Session, exc: OperationalError) -> bool:
    dialect = s.get_bind().dialect.name
    msg = str(exc).lower()
    return dialect == "sqlite" and ("locked" in msg or "busy" in msg)


def _begin_immediate_if_sqlite(s: Session) -> None:
    """Adquire trava de escrita logo no início no SQLite para evitar lost update e deadlock."""
    conn = s.connection()
    if conn.dialect.name == "sqlite":
        raw = getattr(conn.connection, "driver_connection", None)
        if raw is None or not getattr(raw, "in_transaction", False):
            conn.exec_driver_sql("BEGIN IMMEDIATE")


def _run_read(factory: sessionmaker[Session], fn: Callable[[Session], T]) -> T:
    for attempt in range(_MAX_DB_RETRIES):
        with _engine_lock(factory), factory() as s:
            try:
                return fn(s)
            except OperationalError as exc:
                s.rollback()
                if _is_sqlite_lock_error(s, exc) and attempt < _MAX_DB_RETRIES - 1:
                    time.sleep(0.002 * (attempt + 1) + random.uniform(0, 0.003))
                    continue
                raise
    raise RuntimeError("esgotadas tentativas de leitura no rate limiter")


def _run_write(factory: sessionmaker[Session], fn: Callable[[Session], T]) -> T:
    for attempt in range(_MAX_DB_RETRIES):
        with _engine_lock(factory), factory() as s:
            try:
                _begin_immediate_if_sqlite(s)
                result = fn(s)
                s.commit()
                return result
            except IntegrityError:
                s.rollback()
                if attempt < _MAX_DB_RETRIES - 1:
                    time.sleep(random.uniform(0, 0.002))
                    continue
                raise
            except OperationalError as exc:
                s.rollback()
                if _is_sqlite_lock_error(s, exc) and attempt < _MAX_DB_RETRIES - 1:
                    time.sleep(0.002 * (attempt + 1) + random.uniform(0, 0.004))
                    continue
                raise
    raise RuntimeError("esgotadas tentativas de escrita no rate limiter")


def _get_row(s: Session, bucket: str, key_hash: str, *, for_update: bool = False) -> RateLimitEntry | None:
    stmt = select(RateLimitEntry).where(
        RateLimitEntry.bucket == bucket,
        RateLimitEntry.key_hash == key_hash,
    )
    if for_update and s.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return s.scalar(stmt)


def _prune_bucket(s: Session, bucket: str, now: float) -> int:
    res = s.execute(
        delete(RateLimitEntry).where(
            RateLimitEntry.bucket == bucket,
            RateLimitEntry.expires_at < now,
        )
    )
    return int(res.rowcount or 0)


class _SharedLimiter:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        factory: sessionmaker[Session] | None = None,
        bucket: str,
        prune_every: int = DEFAULT_PRUNE_EVERY,
    ):
        if not bucket or len(bucket) > 40:
            raise ValueError("bucket inválido (1..40 caracteres)")
        self.clock = clock
        self.factory = factory
        self.bucket = bucket
        self.prune_every = prune_every
        self._lock = threading.Lock()
        self._writes = 0

    def _next_write_should_prune(self) -> bool:
        if self.prune_every <= 0:
            return False
        with self._lock:
            self._writes += 1
            if self._writes >= self.prune_every:
                self._writes = 0
                return True
            return False

    def prune(self) -> int:
        """Remove entradas expiradas deste bucket no banco (retorna 0 em memória)."""
        if self.factory is None:
            return 0
        return _run_write(self.factory, lambda s: _prune_bucket(s, self.bucket, self.clock()))


class LoginThrottle(_SharedLimiter):
    """Falhas por e-mail (banco compartilhado ou memória): 5 falhas travam por 5 minutos."""

    def __init__(
        self,
        max_failures: int = MAX_FAILURES,
        lock_seconds: int = LOCK_SECONDS,
        clock: Callable[[], float] = time.time,
        factory: sessionmaker[Session] | None = None,
        bucket: str = "login",
        prune_every: int = DEFAULT_PRUNE_EVERY,
    ):
        super().__init__(clock=clock, factory=factory, bucket=bucket, prune_every=prune_every)
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._state: dict[str, list[float]] = {}  # email -> [falhas, travado_até]

    def retry_after(self, email: str) -> int:
        if self.factory is None:
            with self._lock:
                st = self._state.get(email)
                left = (st[1] - self.clock()) if st else 0.0
                return int(left) + 1 if left > 0 else 0

        kh = hash_token(email)

        def _read(s: Session) -> int:
            row = _get_row(s, self.bucket, kh)
            if row is None or row.locked_until <= 0:
                return 0
            left = row.locked_until - self.clock()
            return int(left) + 1 if left > 0 else 0

        return _run_read(self.factory, _read)

    def fail(self, email: str) -> None:
        if self.factory is None:
            with self._lock:
                now = self.clock()
                if len(self._state) > 10_000:
                    self._state = {k: v for k, v in self._state.items() if v[1] > now}
                st = self._state.setdefault(email, [0, 0.0])
                if st[1] and st[1] <= now:
                    st[0], st[1] = 0, 0.0
                if st[1] > now:
                    return
                st[0] += 1
                if st[0] >= self.max_failures:
                    st[0], st[1] = 0, now + self.lock_seconds
            return

        kh = hash_token(email)
        should_prune = self._next_write_should_prune()

        def _write(s: Session) -> None:
            now = self.clock()
            row = _get_row(s, self.bucket, kh, for_update=True)
            if row is None:
                count = 1
                locked_until = 0.0
                if count >= self.max_failures:
                    count = 0
                    locked_until = now + self.lock_seconds
                s.add(
                    RateLimitEntry(
                        bucket=self.bucket,
                        key_hash=kh,
                        count=count,
                        window_start=now,
                        locked_until=locked_until,
                        expires_at=now + self.lock_seconds,
                    )
                )
            elif row.locked_until <= now:
                if row.locked_until > 0 or row.expires_at <= now:
                    row.count = 0
                    row.window_start = now
                    row.locked_until = 0.0
                row.count += 1
                if row.count >= self.max_failures:
                    row.count = 0
                    row.locked_until = now + self.lock_seconds
                row.expires_at = now + self.lock_seconds
            if should_prune:
                _prune_bucket(s, self.bucket, now)

        _run_write(self.factory, _write)

    def ok(self, email: str) -> None:
        if self.factory is None:
            with self._lock:
                self._state.pop(email, None)
            return

        kh = hash_token(email)

        def _clear(s: Session) -> None:
            s.execute(
                delete(RateLimitEntry).where(
                    RateLimitEntry.bucket == self.bucket,
                    RateLimitEntry.key_hash == kh,
                )
            )

        _run_write(self.factory, _clear)


class HourlyLimiter(_SharedLimiter):
    """Contador por chave numa janela fixa de 1 hora (banco compartilhado ou memória)."""

    def __init__(
        self,
        maximum: int,
        window: float = HOUR,
        clock: Callable[[], float] = time.time,
        factory: sessionmaker[Session] | None = None,
        bucket: str = "hourly",
        prune_every: int = DEFAULT_PRUNE_EVERY,
    ):
        super().__init__(clock=clock, factory=factory, bucket=bucket, prune_every=prune_every)
        self.maximum = maximum
        self.window = window
        self._state: dict[str, list[float]] = {}  # chave -> [início da janela, contagem]

    def _entry(self, key: str) -> list[float]:
        now = self.clock()
        if len(self._state) > 10_000:
            self._state = {k: v for k, v in self._state.items() if now - v[0] < self.window}
        st = self._state.get(key)
        if st is None or now - st[0] >= self.window:
            st = self._state[key] = [now, 0]
        return st

    def hit(self, key: str) -> bool:
        """Conta mais um pedido; True se ainda está dentro do limite."""
        if self.factory is None:
            with self._lock:
                st = self._entry(key)
                st[1] += 1
                return st[1] <= self.maximum

        kh = hash_token(key)
        should_prune = self._next_write_should_prune()

        def _write(s: Session) -> bool:
            now = self.clock()
            row = _get_row(s, self.bucket, kh, for_update=True)
            if row is None:
                count = 1
                s.add(
                    RateLimitEntry(
                        bucket=self.bucket,
                        key_hash=kh,
                        count=count,
                        window_start=now,
                        locked_until=0.0,
                        expires_at=now + self.window,
                    )
                )
            else:
                if now - row.window_start >= self.window:
                    row.window_start = now
                    row.count = 1
                    row.expires_at = now + self.window
                else:
                    row.count += 1
                count = row.count
            if should_prune:
                _prune_bucket(s, self.bucket, now)
            return count <= self.maximum

        return _run_write(self.factory, _write)

    def exceeded(self, key: str) -> bool:
        if self.factory is None:
            with self._lock:
                return self._entry(key)[1] >= self.maximum

        kh = hash_token(key)

        def _read(s: Session) -> bool:
            now = self.clock()
            row = _get_row(s, self.bucket, kh)
            if row is None or now - row.window_start >= self.window:
                return 0 >= self.maximum
            return row.count >= self.maximum

        return _run_read(self.factory, _read)

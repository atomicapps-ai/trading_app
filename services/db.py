"""db.py — one connection factory for the whole app's SQLite access.

Two modes, chosen by env so nothing changes for local use:

* **Local (default):** ``aiosqlite`` on the local file — exactly as before.
* **Shared cloud:** when ``TURSO_DATABASE_URL`` is set, a libSQL (Turso)
  connection wrapped in an aiosqlite-shaped shim, so BOTH laptops read/write
  one remote database — a single source of truth regardless of which one is
  the host that day. Turso speaks SQLite, so every existing query is unchanged.

Call sites use ``async with db.connect() as conn:`` and the usual
``conn.execute(...) / fetchone / fetchall / commit`` — identical for both
backends.

Design notes for the shim:
* libSQL auto-commits each ``execute`` (Hrana protocol). The app's pattern is
  "single write + commit", so ``commit()``/``rollback()`` are no-ops. The few
  multi-statement sequences (e.g. set_active) are single-user and tolerate the
  microsecond gap.
* A UNIQUE/constraint failure surfaces as ``libsql_client.LibsqlError``; we
  re-raise it as ``sqlite3.IntegrityError`` so existing
  ``except sqlite3.IntegrityError`` handlers (the create_account slug retry)
  keep working.
* Rows support both index (``row[0]``) and name (``row["col"]``) access plus
  ``.keys()`` / ``dict(row)`` — matching ``aiosqlite.Row``.
"""
from __future__ import annotations

import os
import sqlite3

from services.settings_service import LOCAL_DB_PATH


def turso_enabled() -> bool:
    return bool(os.getenv("TURSO_DATABASE_URL", "").strip())


def connect():
    """Return an async connection: aiosqlite locally, libSQL shim for Turso.
    Both are async context managers with the same execute/fetch/commit API."""
    if turso_enabled():
        return _LibsqlConn(
            os.environ["TURSO_DATABASE_URL"].strip(),
            os.getenv("TURSO_AUTH_TOKEN", "").strip() or None,
        )
    import aiosqlite
    return aiosqlite.connect(LOCAL_DB_PATH)


# --------------------------------------------------------------------------- #
# libSQL (Turso) shim shaped like aiosqlite
# --------------------------------------------------------------------------- #


class _Row:
    """aiosqlite.Row-compatible: index + name access, keys(), dict()."""
    __slots__ = ("_cols", "_vals", "_map")

    def __init__(self, cols, vals):
        self._cols = cols
        self._vals = tuple(vals)
        self._map = {c: v for c, v in zip(cols, self._vals)}

    def __getitem__(self, k):
        return self._vals[k] if isinstance(k, int) else self._map[k]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __contains__(self, key):
        return key in self._map


class _Cursor:
    def __init__(self, rs):
        cols = tuple(rs.columns)
        self._rows = [_Row(cols, tuple(r)) for r in rs.rows]
        self.rowcount = rs.rows_affected if rs.rows_affected is not None else -1
        self.lastrowid = rs.last_insert_rowid
        self._i = 0

    async def fetchone(self):
        if self._i < len(self._rows):
            row = self._rows[self._i]
            self._i += 1
            return row
        return None

    async def fetchall(self):
        rest = self._rows[self._i:]
        self._i = len(self._rows)
        return rest

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class _LibsqlConn:
    def __init__(self, url: str, auth_token: str | None):
        import libsql_client
        self._lib = libsql_client
        self._client = (
            libsql_client.create_client(url, auth_token=auth_token)
            if auth_token else libsql_client.create_client(url)
        )
        self.row_factory = None  # accepted + ignored; rows are always _Row

    @staticmethod
    def _args(params):
        if params is None:
            return []
        if isinstance(params, dict):
            return params
        return list(params)

    async def execute(self, sql, params=()):
        try:
            rs = await self._client.execute(sql, self._args(params))
        except self._lib.LibsqlError as e:
            msg = str(e)
            code = getattr(e, "code", "") or ""
            if "constraint" in msg.lower() or "CONSTRAINT" in code or "UNIQUE" in msg:
                raise sqlite3.IntegrityError(msg) from e
            raise
        return _Cursor(rs)

    async def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            await self.execute(sql, params)

    async def commit(self):
        return None  # libSQL auto-commits each execute

    async def rollback(self):
        return None

    async def close(self):
        await self._client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        await self.close()
        return False

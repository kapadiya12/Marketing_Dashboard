"""
Django database backend for Turso (libSQL), built on Django's SQLite backend.

Turso speaks SQLite's SQL dialect, so Django's SQLite backend does almost everything. This module bridges
the differences of Turso's Python driver (``libsql``) from the stdlib ``sqlite3`` module:

* no Python functions on the connection: date/time SQL is native instead (see ``operations.py``);
* only ``?`` placeholders and plain values: parameters are converted and adapted here;
* errors are raised as ``ValueError``: they are re-raised as the DB-API exceptions Django expects;
* the connection always autocommits: ``atomic()`` opens transactions with an explicit BEGIN, as on SQLite.

Configure with ``ENGINE: "config.turso_backend"``, ``NAME`` set to the ``libsql://`` URL (or a local file
path) and ``OPTIONS: {"auth_token": ...}``; other driver arguments (``sync_url``, ``timeout``) also go in OPTIONS.
"""
import datetime
import decimal
import re
import sqlite3
import uuid
from collections.abc import Mapping

import libsql
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.sqlite3 import base as sqlite_base
from django.utils.asyncio import async_unsafe

from .operations import DatabaseOperations


class Database:
    """Module-like namespace: libsql's connect() plus the exception classes Django maps errors from."""

    Warning = sqlite3.Warning
    Error = sqlite3.Error
    InterfaceError = sqlite3.InterfaceError
    DatabaseError = sqlite3.DatabaseError
    DataError = sqlite3.DataError
    OperationalError = sqlite3.OperationalError
    IntegrityError = sqlite3.IntegrityError
    InternalError = sqlite3.InternalError
    ProgrammingError = sqlite3.ProgrammingError
    NotSupportedError = sqlite3.NotSupportedError
    sqlite_version_info = libsql.sqlite_version_info
    connect = staticmethod(libsql.connect)


_DRIVER_ERRORS = (ValueError, libsql.Error)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _DRIVER_ERRORS as exc:
        message = str(exc)
        if "constraint failed" in message:  # UNIQUE / NOT NULL / FOREIGN KEY / CHECK / PRIMARY KEY
            cls = Database.IntegrityError
        elif "parameter" in message.lower():
            cls = Database.InterfaceError
        else:
            cls = Database.OperationalError
        raise cls(message) from exc


_EXACT_INT = 2**53  # the driver passes integers through a float; larger ones go as text (integer affinity restores them)


def adapt(value):
    """A query parameter in a type the driver accepts, stored the way Django's SQLite backend stores it."""
    if value is None or isinstance(value, (str, float, bytes)):
        return value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value if -_EXACT_INT <= value <= _EXACT_INT else str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat(" ")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (memoryview, bytearray)):
        return bytes(value)
    if isinstance(value, uuid.UUID):
        return value.hex
    return value


_FORMAT = re.compile(r"(?<!%)%s")
_PYFORMAT = re.compile(r"(?<!%)%\((\w+)\)s")


def _convert(query, params):
    """Django's "format"/"pyformat" placeholders -> "?" with positional values."""
    if isinstance(params, Mapping):
        names = []
        query = _PYFORMAT.sub(lambda m: names.append(m.group(1)) or "?", query)
        params = [params[name] for name in names]
    else:
        query = _FORMAT.sub("?", query)
    return query.replace("%%", "%"), tuple(adapt(v) for v in params)


class CursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        if params is None:
            _call(self.cursor.execute, query)
        else:
            _call(self.cursor.execute, *_convert(query, params))
        return self

    def executemany(self, query, param_list):
        converted = [_convert(query, params) for params in param_list]
        if converted:
            _call(self.cursor.executemany, converted[0][0], [values for _, values in converted])
        return self

    def __iter__(self):
        return iter(self.cursor.fetchone, None)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return CursorWrapper(_call(self.connection.cursor))

    def execute(self, query, params=None):
        return self.cursor().execute(query, params)

    def commit(self):
        _call(self.connection.commit)

    def rollback(self):
        _call(self.connection.rollback)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class DatabaseWrapper(sqlite_base.DatabaseWrapper):
    # vendor stays "sqlite" so Django keeps generating SQLite SQL (as_sqlite() methods, feature checks).
    display_name = "Turso (libSQL)"
    Database = Database
    ops_class = DatabaseOperations

    def get_connection_params(self):
        settings_dict = self.settings_dict
        if not settings_dict["NAME"]:
            raise ImproperlyConfigured("settings.DATABASES is improperly configured. Please supply the NAME value.")
        options = dict(settings_dict["OPTIONS"])
        mode = options.pop("transaction_mode", None)
        if mode is not None and mode.upper() not in self.transaction_modes:
            raise ImproperlyConfigured(f"Unknown transaction_mode {mode!r}.")
        self.transaction_mode = mode.upper() if mode else None
        self.init_commands = options.pop("init_command", "").split(";")
        return {"database": str(settings_dict["NAME"]), "isolation_level": None, "_check_same_thread": False,
                **options}

    @async_unsafe
    def get_new_connection(self, conn_params):
        conn = Connection(_call(Database.connect, **conn_params))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        for init_command in self.init_commands:
            if init_command := init_command.strip():
                conn.execute(init_command)
        return conn

    def create_cursor(self, name=None):
        return self.connection.cursor()

    def _set_autocommit(self, autocommit):
        """The driver always autocommits; atomic() starts transactions with an explicit BEGIN."""

    def is_usable(self):
        try:
            self.connection.execute("SELECT 1")
        except Database.Error:
            return False
        return True

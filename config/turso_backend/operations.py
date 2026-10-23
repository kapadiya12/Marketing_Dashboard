"""
Date/time SQL for Turso written with native SQLite date functions.

Django's SQLite backend calls Python functions (``django_date_trunc`` etc.) that it registers on each
connection; a Turso server cannot run them. Literal ``%`` is doubled because Django substitutes query
parameters with ``%`` formatting.

Time zones are shifted by the zone's *current* UTC offset. That is exact for fixed-offset zones such as
Asia/Kolkata; in zones with daylight saving time, values from the other half of the year can be an hour off.
"""
import datetime
import zoneinfo

from django.conf import settings
from django.db import NotSupportedError
from django.db.backends.sqlite3.operations import DatabaseOperations as SQLiteOperations
from django.db.backends.utils import split_tzname_delta

# Templates over a date/datetime expression {d}; the Thursday of {d}'s ISO week gives ISO week and year.
_EXTRACT = {
    "year": "CAST(strftime('%%Y', {d}) AS INTEGER)",
    "month": "CAST(strftime('%%m', {d}) AS INTEGER)",
    "day": "CAST(strftime('%%d', {d}) AS INTEGER)",
    "hour": "CAST(strftime('%%H', {d}) AS INTEGER)",
    "minute": "CAST(strftime('%%M', {d}) AS INTEGER)",
    "second": "CAST(strftime('%%S', {d}) AS INTEGER)",
    "week_day": "(CAST(strftime('%%w', {d}) AS INTEGER) + 1)",
    "iso_week_day": "((CAST(strftime('%%w', {d}) AS INTEGER) + 6) %% 7 + 1)",
    "quarter": "((CAST(strftime('%%m', {d}) AS INTEGER) + 2) / 3)",
    "week": "((CAST(strftime('%%j', date({d}, '-3 days', 'weekday 4')) AS INTEGER) - 1) / 7 + 1)",
    "iso_year": "CAST(strftime('%%Y', date({d}, '-3 days', 'weekday 4')) AS INTEGER)",
}
_TRUNC = {  # -> 'YYYY-MM-DD HH:MM:SS', the same text Django's Python functions return
    "year": "strftime('%%Y-01-01 00:00:00', {d})",
    "quarter": "(strftime('%%Y-', {d}) || printf('%%02d', ((CAST(strftime('%%m', {d}) AS INTEGER) - 1) / 3) * 3 + 1)"
               " || '-01 00:00:00')",
    "month": "strftime('%%Y-%%m-01 00:00:00', {d})",
    "week": "strftime('%%Y-%%m-%%d 00:00:00', {d}, printf('-%%d days', (CAST(strftime('%%w', {d}) AS INTEGER) + 6) %% 7))",
    "day": "strftime('%%Y-%%m-%%d 00:00:00', {d})",
    "hour": "strftime('%%Y-%%m-%%d %%H:00:00', {d})",
    "minute": "strftime('%%Y-%%m-%%d %%H:%%M:00', {d})",
    "second": "strftime('%%Y-%%m-%%d %%H:%%M:%%S', {d})",
}
_TIME_TRUNC = {
    "hour": "strftime('%%H:00:00', {d})",
    "minute": "strftime('%%H:%%M:00', {d})",
    "second": "strftime('%%H:%%M:%%S', {d})",
}


def _utc_offset_minutes(tzname):
    if not tzname or tzname.upper() == "UTC":
        return 0
    name, sign, delta = split_tzname_delta(tzname)
    tz = datetime.timezone.utc if name.upper() == "UTC" else zoneinfo.ZoneInfo(name)
    minutes = int(datetime.datetime.now(tz).utcoffset().total_seconds() // 60)
    if delta:
        hours, _, mins = delta.partition(":")
        extra = int(hours) * 60 + int(mins or 0)
        minutes += extra if sign == "+" else -extra
    return minutes


def _render(template, lookup_type, sql, params, kind):
    try:
        template = template[lookup_type.lower()]
    except KeyError:
        raise NotSupportedError(f"{kind} '{lookup_type}' is not supported on Turso.") from None
    return template.replace("{d}", f"({sql})"), tuple(params) * template.count("{d}")


class DatabaseOperations(SQLiteOperations):
    def _local(self, sql, tzname):
        """``sql`` (stored in the connection's zone) as wall-clock text in ``tzname``."""
        if not (tzname and settings.USE_TZ):
            return sql
        minutes = _utc_offset_minutes(tzname) - _utc_offset_minutes(self.connection.timezone_name)
        return f"strftime('%%Y-%%m-%%d %%H:%%M:%%f', {sql}, '{minutes:+d} minutes')" if minutes else sql

    def date_extract_sql(self, lookup_type, sql, params):
        return _render(_EXTRACT, lookup_type, sql, params, "Extract")

    def datetime_extract_sql(self, lookup_type, sql, params, tzname):
        return _render(_EXTRACT, lookup_type, self._local(sql, tzname), params, "Extract")

    def time_extract_sql(self, lookup_type, sql, params):
        if lookup_type.lower() not in ("hour", "minute", "second"):
            raise NotSupportedError(f"Extract '{lookup_type}' from a time is not supported.")
        return _render(_EXTRACT, lookup_type, sql, params, "Extract")

    def date_trunc_sql(self, lookup_type, sql, params, tzname=None):
        sql, params = _render(_TRUNC, lookup_type, self._local(sql, tzname), params, "Trunc")
        return f"date({sql})", params

    def datetime_trunc_sql(self, lookup_type, sql, params, tzname):
        return _render(_TRUNC, lookup_type, self._local(sql, tzname), params, "Trunc")

    def time_trunc_sql(self, lookup_type, sql, params, tzname=None):
        return _render(_TIME_TRUNC, lookup_type, self._local(sql, tzname), params, "Trunc")

    def datetime_cast_date_sql(self, sql, params, tzname):
        return f"date({self._local(sql, tzname)})", params

    def datetime_cast_time_sql(self, sql, params, tzname):
        return f"strftime('%%H:%%M:%%f', {self._local(sql, tzname)})", params

    def combine_duration_expression(self, connector, sub_expressions):
        raise NotSupportedError("Date arithmetic with durations is not supported on Turso.")

    def subtract_temporals(self, internal_type, lhs, rhs):
        raise NotSupportedError("Subtracting dates or times in a query is not supported on Turso.")

    def _quote_params_for_last_executed_query(self, params):
        from .base import adapt

        return super()._quote_params_for_last_executed_query(tuple(adapt(p) for p in params))

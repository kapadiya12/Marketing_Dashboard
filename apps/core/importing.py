"""
Shared import engine (CSV and Excel) used by every import screen.

An ``ImportSpec`` describes the columns and how to build/save a Django form for one
row. Each row is validated with the same form used for manual entry; text values are
mapped to form values (choice labels -> keys, names/usernames/slugs -> related records
within the user's permitted choices, yes/no -> booleans, ``;`` -> multiple values).

Real-world spreadsheets rarely match the configured options exactly, so imports are
*lenient* by default (see ``RowMapper``): missing tags/categories are created, new
statuses are added for users who manage the module, and other unrecognised values fall
back to the default while being preserved in the record's notes. Every adjustment is
reported. Rows that still fail validation stop the import (nothing is saved) and each
problem is reported by spreadsheet row number. Rows marked "SAMPLE ROW" (from the sample
templates) are skipped unless the user chooses to import them as demo data.
"""
import csv
import datetime
import io
from dataclasses import dataclass, field
from typing import Callable, Optional

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

SAMPLE_MARKER = "SAMPLE ROW"
MARKER_TEXT = "SAMPLE ROW - example only - delete or replace before importing"
MAX_ROWS = 5000
IMPORT_EXTENSIONS = {"csv", "txt", "xlsx"}


@dataclass
class ImportSpec:
    key: str  # sample-data key, e.g. a resource key or "users"
    title: str  # e.g. "Customer Meetings"
    columns: list  # template / accepted column names, in order
    form_factory: Callable  # (data: dict | None) -> form
    save: Callable  # (form) -> saved object
    back_url: str
    filename: str
    defaults: dict = field(default_factory=dict)  # column -> value used when the cell is blank
    ignored_columns: set = field(default_factory=set)  # accepted but ignored (e.g. id from exports)
    description: str = ""
    sample_context: dict = field(default_factory=dict)  # e.g. {"product": <Product>}
    on_success: Optional[Callable] = None  # (created_count) -> None
    lenient: bool = True  # handle unknown values instead of failing (see RowMapper)
    creators: dict = field(default_factory=dict)  # field -> fn(text) creating the missing option (or None)
    note_field: Optional[str] = "notes"  # where unrecognised values are preserved
    match_existing: Optional[Callable] = None  # (cleaned row data) -> existing instance to update, or None


# --------------------------------------------------------------------------- reading files

class UploadForm(forms.Form):
    file = forms.FileField(help_text="CSV (UTF-8) or Excel (.xlsx). Download a template below for the exact columns.")
    include_samples = forms.BooleanField(
        required=False, label="Also import rows marked “SAMPLE ROW” (use the template's examples as demo data)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({"class": "form-control", "accept": ".csv,.xlsx,.txt"})
        self.fields["include_samples"].widget.attrs.update({"class": "form-check-input"})

    def clean_file(self):
        from django.conf import settings

        f = self.cleaned_data["file"]
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in IMPORT_EXTENSIONS:
            raise ValidationError("Upload a .csv or .xlsx file.")
        if f.size > settings.MAX_UPLOAD_SIZE:
            raise ValidationError("File too large.")
        if ext == "xlsx":
            head = f.read(4)
            f.seek(0)
            if head != b"PK\x03\x04":
                raise ValidationError("This is not a valid .xlsx file.")
        return f


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime.datetime):
        if value.hour == value.minute == value.second == 0:
            return value.date().isoformat()
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_table(uploaded):
    """Return (headers, rows) where rows is a list of (spreadsheet_row_number, {header: text})."""
    name = uploaded.name.lower()
    raw = uploaded.read()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - corrupt workbook
            raise ValueError(f"Could not read the Excel file: {exc}") from exc
        ws = wb["Data"] if "Data" in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        try:
            headers = [_cell_text(h) for h in next(it)]
        except StopIteration:
            raise ValueError("The sheet is empty.")
        rows = []
        for i, values in enumerate(it, start=2):
            row = {h: _cell_text(v) for h, v in zip(headers, values) if h}
            rows.append((i, row))
        wb.close()
    else:
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("The file is not valid UTF-8 text.")
        reader = csv.reader(io.StringIO(text))
        try:
            headers = [h.strip().lstrip("﻿") for h in next(reader)]
        except StopIteration:
            raise ValueError("The file is empty.")
        rows = [(i, {h: (v or "").strip() for h, v in zip(headers, values) if h})
                for i, values in enumerate(reader, start=2)]
    headers = [h for h in headers if h]
    if not headers:
        raise ValueError("The file has no header row.")
    return headers, rows


def is_sample_row(row):
    return any(isinstance(v, str) and v.upper().startswith(SAMPLE_MARKER) for v in row.values())


def _strip_marker(row):
    return {k: (v.replace(MARKER_TEXT + " | ", "").replace(MARKER_TEXT, "").strip() if isinstance(v, str) else v)
            for k, v in row.items()}


# --------------------------------------------------------------------------- value mapping

LOOKUP_FIELDS = ("slug", "username", "email", "name", "label", "title", "key")


def choice_display(obj):
    """The text a spreadsheet should use to refer to a related record."""
    for attr in ("username", "slug", "name", "label", "title"):
        value = getattr(obj, attr, None)
        if value and isinstance(value, str):
            return value
    return str(obj)


def resolve_model_choice(field_obj, value):
    """Find a record within the field's (permission-scoped) queryset by id, slug, username, email or name."""
    qs = field_obj.queryset
    value = value.strip()
    if not value:
        return ""
    if value.isdigit() and qs.filter(pk=int(value)).exists():
        return value
    model_fields = {f.name for f in qs.model._meta.get_fields()}
    for name in LOOKUP_FIELDS:
        if name in model_fields:
            match = qs.filter(**{f"{name}__iexact": value}).first()
            if match is not None:
                return str(match.pk)
    for obj in qs[:2000]:
        if str(obj).strip().lower() == value.lower():
            return str(obj.pk)
    return value  # unresolved


def _flat_choices(choices):
    out = []
    for key, label in choices:
        if isinstance(label, (list, tuple)):
            out.extend(label)
        else:
            out.append((key, label))
    return out


def resolve_choice(field_obj, value):
    v = value.strip().lower()
    for key, label in _flat_choices(field_obj.choices):
        if v in (str(key).lower(), str(label).lower()):
            return key
    return value.strip()


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
                "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%y")
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p")


def normalise_date(text):
    """Accept common spreadsheet date styles (incl. DD/MM/YYYY and Excel serial numbers) -> YYYY-MM-DD."""
    t = text.strip()
    if not t:
        return t
    if t.replace(".", "", 1).isdigit() and 20000 < float(t) < 80000:  # Excel serial date
        return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(t)))).isoformat()
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return t


def normalise_datetime(text):
    t = text.strip().replace("T", " ")
    if not t:
        return t
    parts = t.split(" ", 1)
    date = normalise_date(parts[0])
    if len(parts) == 1:
        return f"{date} 00:00" if date != parts[0] or "-" in date else t
    time_part = parts[1].strip().upper()
    for fmt in TIME_FORMATS:
        try:
            return f"{date} {datetime.datetime.strptime(time_part, fmt).strftime('%H:%M')}"
        except ValueError:
            continue
    return f"{date} {parts[1].strip()}"


def normalise_number(text):
    """'₹7,50,000', '1,200.50', 'INR 5000' -> plain number text."""
    t = text.strip()
    for token in ("₹", "INR", "Rs.", "Rs", "$", "€", "£", ",", " "):
        t = t.replace(token, "")
    if t.endswith("%"):
        t = t[:-1]
    return t


def _choice_found(field_obj, value):
    return any(str(k) == str(value) for k, _ in _flat_choices(field_obj.choices) if k not in ("", None))


def _model_found(field_obj, value):
    return bool(value) and str(value).isdigit() and field_obj.queryset.filter(pk=int(value)).exists()


class RowMapper:
    """
    Maps one spreadsheet row to form data. With ``spec.lenient`` on, values that do not match
    an existing option are handled instead of failing the whole import:
      * fields with a creator (tags, categories, statuses) get the missing option created;
      * optional references (e.g. an unknown team member) are left blank;
      * other choice fields (e.g. outcome) fall back to their default.
    Unrecognised values are appended to the record's notes so nothing is lost, and every
    adjustment is returned for reporting.
    """

    def __init__(self, spec):
        self.spec = spec

    def map(self, form, row):
        spec = self.spec
        data, kept, adjusted = {}, [], []
        for name, f in form.fields.items():
            raw = (row.get(name) or "").strip()
            if not raw and spec.defaults.get(name) not in (None, ""):
                raw = str(spec.defaults[name])
            if not raw and spec.lenient and not isinstance(f, (forms.BooleanField, forms.ModelMultipleChoiceField)):
                # Missing/blank cell: use the field's normal default (as the manual form would).
                initial = f.initial() if callable(f.initial) else f.initial
                if initial not in (None, "", []):
                    raw = str(getattr(initial, "pk", initial))
            if name == "choices_text":
                raw = raw.replace(";", "\n")
            label = str(f.label or name)
            creator = spec.creators.get(name)
            if isinstance(f, forms.ModelMultipleChoiceField):
                values = []
                for v in [x.strip() for x in raw.split(";") if x.strip()]:
                    pk = resolve_model_choice(f, v)
                    if not _model_found(f, pk) and spec.lenient:
                        obj = creator(v) if creator else None
                        if obj is not None:
                            pk = str(obj.pk)
                            adjusted.append(f"created {label.lower()} “{v}”")
                        else:
                            kept.append(f"{label}: {v}")
                            adjusted.append(f"{label.lower()} “{v}” not found (kept in notes)")
                            continue
                    values.append(pk)
                data[name] = values
            elif isinstance(f, forms.ModelChoiceField):
                pk = resolve_model_choice(f, raw)
                if raw and not _model_found(f, pk) and spec.lenient:
                    obj = creator(raw) if creator else None
                    if obj is not None:
                        pk = str(obj.pk)
                        adjusted.append(f"created {label.lower()} “{raw}”")
                    elif not f.required:
                        pk = ""
                        kept.append(f"{label}: {raw}")
                        adjusted.append(f"{label.lower()} “{raw}” not found (left blank, kept in notes)")
                data[name] = pk
            elif isinstance(f, forms.MultipleChoiceField):
                data[name] = [resolve_choice(f, v) for v in raw.split(";") if v.strip()]
            elif isinstance(f, forms.NullBooleanField):
                low = raw.lower()
                data[name] = "true" if low in ("yes", "true", "1", "y") else "false" if low in ("no", "false", "0", "n") \
                    else "unknown"
            elif isinstance(f, forms.BooleanField):
                data[name] = "on" if raw.lower() in ("yes", "true", "1", "y", "on", "x") else ""
            elif isinstance(f, forms.ChoiceField):
                key = resolve_choice(f, raw) if raw else ""
                if raw and not _choice_found(f, key) and spec.lenient:
                    created_key = creator(raw) if creator else None
                    if created_key:
                        key = created_key
                        adjusted.append(f"added {label.lower()} “{raw}”")
                    else:
                        fallback = f.initial if f.initial not in (None, "") else ""
                        if fallback or not f.required:
                            key = fallback
                            kept.append(f"{label}: {raw}")
                            adjusted.append(f"{label.lower()} “{raw}” is not a standard option (kept in notes)")
                data[name] = key
            elif isinstance(f, forms.DateTimeField):
                data[name] = normalise_datetime(raw)
            elif isinstance(f, forms.DateField):
                data[name] = normalise_date(raw)
            elif isinstance(f, (forms.DecimalField, forms.IntegerField, forms.FloatField)):
                data[name] = normalise_number(raw)
            else:
                data[name] = raw
        if kept and spec.note_field and spec.note_field in data:
            extra = "Imported values: " + "; ".join(kept)
            data[spec.note_field] = (str(data[spec.note_field]) + "\n" + extra).strip()
        return _MultiDict(data), adjusted


def row_to_data(form, row, defaults=None):
    """Strict mapping without creating options (kept for callers that need exact matching)."""
    spec = ImportSpec(key="", title="", columns=[], form_factory=lambda d=None: form, save=lambda f: None,
                      back_url="", filename="", defaults=defaults or {}, lenient=False)
    return RowMapper(spec).map(form, row)[0]


class _MultiDict(dict):
    def getlist(self, key, default=None):
        v = self.get(key, default)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


# --------------------------------------------------------------------------- running imports

class _Rollback(Exception):
    pass


def run_import(spec, headers, rows, include_samples=False, progress=None):
    """``progress(stage, done, total)`` is told how far it got (background imports show it)."""
    progress = progress or (lambda stage, done, total: None)
    rows = list(rows)
    known = set(spec.columns) | set(spec.ignored_columns)
    unknown = [h for h in headers if h not in known]
    if unknown:
        return {"created": 0, "errors": [(1, f"Unknown column(s): {', '.join(unknown)}. Download the template for "
                                             f"the accepted columns.")], "skipped": 0, "total": 0, "adjustments": []}
    errors, valid, skipped, adjustments = [], [], 0, []
    for h in headers:
        if h in spec.ignored_columns and h not in ("id", "created_at", "updated_at"):
            adjustments.append((1, f"column “{h}” is no longer used and was skipped"))
    mapper = RowMapper(spec)
    for checked, (row_no, row) in enumerate(rows, 1):
        progress("Checking rows", checked, len(rows))
        if not any(row.values()):
            continue
        if is_sample_row(row):
            if not include_samples:
                skipped += 1
                continue
            row = _strip_marker(row)
        if len(valid) + len(errors) >= MAX_ROWS:
            errors.append((row_no, f"Too many rows; the limit is {MAX_ROWS} per import."))
            break
        data, adjusted = mapper.map(spec.form_factory(None), row)
        existing = spec.match_existing(data) if spec.match_existing else None
        if existing is not None:
            form = spec.form_factory(data, instance=existing)
            adjusted = adjusted + [f"updated existing record “{existing}”"]
        else:
            form = spec.form_factory(data)
        if form.is_valid():
            valid.append((row_no, form))
            adjustments.extend((row_no, a) for a in adjusted)
        else:
            msgs = []
            for fname, errs in form.errors.items():
                label = "row" if fname == "__all__" else fname
                value = row.get(fname, "")
                shown = f" (value: “{value[:40]}”)" if value and fname != "__all__" else ""
                hint = ""
                f = form.fields.get(fname)
                if f is not None and isinstance(f, forms.ChoiceField) and not isinstance(f, forms.ModelChoiceField):
                    allowed = [str(lab) for k, lab in _flat_choices(f.choices) if k not in ("", None)][:12]
                    hint = f" Allowed: {', '.join(allowed)}." if allowed else ""
                msgs.append(f"{label}{shown}: {'; '.join(errs)}{hint}")
            errors.append((row_no, " | ".join(msgs)))
    base = {"skipped": skipped, "adjustments": adjustments}
    if errors:
        import logging

        log = logging.getLogger("apps.import")
        for row_no, msg in errors[:50]:
            log.warning("Import %s row %s: %s", spec.title, row_no, msg)
        return {"created": 0, "errors": errors, "total": len(valid) + len(errors), **base}
    if getattr(connection, "is_remote", False):
        return _save_rows_separately(spec, valid, base, progress)
    created = 0
    try:
        with transaction.atomic():
            for row_no, form in valid:
                progress("Saving rows", created + 1, len(valid))
                try:
                    with transaction.atomic():
                        spec.save(form)
                        created += 1
                except IntegrityError:
                    errors.append((row_no, "Duplicate: conflicts with another row in this file or an existing "
                                           "record (uniqueness rule)."))
            if errors:
                raise _Rollback
    except _Rollback:
        return {"created": 0, "errors": errors, "total": len(valid), **base}
    return {"created": created, "errors": [], "total": created, **base}


def _save_rows_separately(spec, valid, base, progress=lambda stage, done, total: None):
    """Turso closes a write transaction after a few seconds, and each statement in one is a network round trip,
    so one transaction around a whole file fails part-way. Save each row in its own transaction instead and,
    if a row fails, delete the rows this import added so that still nothing is saved."""
    added, errors = [], []
    for saved, (row_no, form) in enumerate(valid, 1):
        progress("Saving rows", saved, len(valid))
        instance = getattr(form, "instance", None)
        is_new = instance is not None and instance.pk is None
        try:
            with transaction.atomic():
                spec.save(form)
        except IntegrityError:
            errors.append((row_no, "Duplicate: conflicts with another row in this file or an existing "
                                   "record (uniqueness rule)."))
            break
        if is_new:
            added.append(form.instance)
    if errors:
        for obj in reversed(added):
            with transaction.atomic():
                obj.delete()
        return {"created": 0, "errors": errors, "total": len(valid), **base}
    return {"created": len(valid), "errors": [], "total": len(valid), **base}


# --------------------------------------------------------------------------- templates & field guide

def _field_type(f):
    if isinstance(f, forms.ModelMultipleChoiceField):
        return "Multiple references (separate with ;)"
    if isinstance(f, forms.ModelChoiceField):
        return "Reference"
    if isinstance(f, forms.MultipleChoiceField):
        return "Multiple choices (separate with ;)"
    if isinstance(f, forms.NullBooleanField):
        return "Yes / No / blank (unknown)"
    if isinstance(f, forms.BooleanField):
        return "Yes / No"
    if isinstance(f, forms.ChoiceField):
        return "Choice"
    if isinstance(f, forms.DateTimeField):
        return "Date & time (YYYY-MM-DD HH:MM)"
    if isinstance(f, forms.DateField):
        return "Date (YYYY-MM-DD)"
    if isinstance(f, forms.EmailField):
        return "Email"
    if isinstance(f, forms.URLField):
        return "URL (https://…)"
    if isinstance(f, forms.DecimalField):
        return "Amount / decimal number"
    if isinstance(f, (forms.IntegerField, forms.FloatField)):
        return "Whole number"
    if isinstance(f.widget, forms.Textarea):
        return "Long text"
    return "Text"


def allowed_values(f, limit=40):
    """List of allowed spreadsheet values for choice/reference fields (None for free-form fields)."""
    if isinstance(f, forms.ModelChoiceField):
        values = [choice_display(o) for o in f.queryset[: limit + 1]]
    elif isinstance(f, forms.ChoiceField):
        values = [str(label) for key, label in _flat_choices(f.choices) if key not in ("", None)]
    else:
        return None
    return values


def _date_offset(name, i):
    base = 7 * (i + 1)
    if name in ("end_date", "end_at", "period_end"):
        base += 30
    if name in ("baseline_date", "last_measured_date", "last_checked_date", "last_interaction_date",
                "submission_date", "sent_date", "publication_date", "measured_on", "date"):
        base = -base
    return timezone.localdate() + datetime.timedelta(days=base)


def generic_sample(name, f, i, context):
    """A valid example value derived from the form field."""
    product = context.get("product")
    if name == "product":
        if product is not None:
            return product.slug
        first = f.queryset.first()
        return choice_display(first) if first else ""
    if name == "is_active":
        return "yes"
    if name == "assigned_to" and context.get("user") is not None:
        return context["user"].username
    if isinstance(f, forms.ModelMultipleChoiceField):
        return ""
    if isinstance(f, forms.ModelChoiceField):
        if not f.required:
            return ""
        options = list(f.queryset[:i + 1])
        return choice_display(options[min(i, len(options) - 1)]) if options else ""
    if isinstance(f, forms.MultipleChoiceField):
        values = allowed_values(f) or []
        return values[0] if values else ""
    if isinstance(f, forms.NullBooleanField):
        return "yes" if i == 0 else ""
    if isinstance(f, forms.BooleanField):
        return "yes" if i == 0 else "no"
    if isinstance(f, forms.ChoiceField):
        values = allowed_values(f) or []
        if not values:
            return ""
        return values[min(i, len(values) - 1)]
    if isinstance(f, forms.DateTimeField):
        return (_date_offset(name, i)).strftime("%Y-%m-%d") + " 10:30"
    if isinstance(f, forms.DateField):
        return _date_offset(name, i).isoformat()
    if isinstance(f, forms.EmailField):
        return f"contact{i + 1}@example.com"
    if isinstance(f, forms.URLField):
        return f"https://www.example.com/{slugify(name)}-{i + 1}"
    if isinstance(f, forms.DecimalField):
        return str((i + 1) * 25000)
    if isinstance(f, forms.IntegerField):
        return str((i + 1) * 10)
    if isinstance(f, forms.SlugField) or name == "key":
        return f"sample_{slugify(name).replace('-', '_')}_{i + 1}"
    max_len = getattr(f, "max_length", None) or 200
    return f"Example {str(f.label or name).lower()} {i + 1}"[:max_len]


def build_samples(spec, count=2):
    from .samples import SAMPLES

    form = spec.form_factory(None)
    overrides = SAMPLES.get(spec.key, [])
    rows = []
    for i in range(count):
        over = overrides[i] if i < len(overrides) else {}
        row = {}
        for name in spec.columns:
            f = form.fields.get(name)
            if name in over:
                row[name] = over[name]
            elif f is not None:
                row[name] = generic_sample(name, f, i, spec.sample_context)
            else:
                row[name] = ""
        marker_col = next((c for c in ("notes", "description", "help_text", "message", "outcomes", "next_step")
                           if c in spec.columns and c in form.fields and not form.fields[c].required), None)
        if marker_col:
            row[marker_col] = MARKER_TEXT
        else:  # no free-text column: prefix the first text value so the row is still recognisable
            first_text = next((c for c in spec.columns if isinstance(form.fields.get(c), forms.CharField)
                               and not isinstance(form.fields.get(c), (forms.ChoiceField,))), spec.columns[0])
            row[first_text] = f"{MARKER_TEXT} | {row.get(first_text, '')}"
        rows.append(row)
    return rows


def column_guide(spec):
    form = spec.form_factory(None)
    samples = build_samples(spec)
    guide = []
    for name in spec.columns:
        f = form.fields.get(name)
        if f is None:
            continue
        values = allowed_values(f)
        if isinstance(f, forms.ModelChoiceField):
            note = "Use the name exactly as listed" + (" (product slug)" if name in ("product", "shared_products")
                                                        else " (username or email)" if "user" in name
                                                        or name == "assigned_to" else "")
            if name in spec.creators or getattr(f, "creates_missing", False):
                note = "Use an existing name, or type a new one and it will be created"
        elif name in spec.creators:
            note = "Use a listed option, or type a new one and it will be added"
        elif isinstance(f, forms.ChoiceField) and spec.lenient and spec.note_field:
            note = "Other values are accepted: the default is used and your value is kept in notes"
        else:
            note = ""
        example = next((s[name] for s in samples if s.get(name) and not str(s[name]).startswith(SAMPLE_MARKER)), "")
        guide.append({
            "name": name,
            "label": str(f.label or name),
            "required": f.required and name not in spec.defaults,
            "type": _field_type(f),
            "allowed": values,
            "allowed_more": values is not None and isinstance(f, forms.ModelChoiceField) and len(values) > 40,
            "note": note,
            "help": f.help_text,
            "example": example,
            "has_default": name in spec.defaults,
        })
    return guide


def template_response(spec, kind):
    """kind: 'csv' (headers only), 'csv_sample' (with sample rows) or 'xlsx' (sample rows + guide + dropdowns)."""
    stem = f"{spec.filename}-import-template"
    if kind in ("csv", "csv_sample"):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{stem}{"-sample" if kind == "csv_sample" else ""}.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(spec.columns)
        if kind == "csv_sample":
            for row in build_samples(spec):
                writer.writerow([row.get(c, "") for c in spec.columns])
        return response

    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    guide = {g["name"]: g for g in column_guide(spec)}
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(spec.columns)
    head_fill = PatternFill("solid", fgColor="1E293B")
    req_fill = PatternFill("solid", fgColor="4F46E5")
    for idx, name in enumerate(spec.columns, start=1):
        cell = ws.cell(row=1, column=idx)
        g = guide.get(name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = req_fill if g and g["required"] else head_fill
        if g:
            text = f"{g['label']}{' (required)' if g['required'] else ''}\n{g['type']}"
            if g["allowed"]:
                text += "\nAllowed: " + ", ".join(g["allowed"][:15]) + ("…" if len(g["allowed"]) > 15 else "")
            cell.comment = Comment(text, "Template")
        ws.column_dimensions[get_column_letter(idx)].width = max(14, min(40, len(name) + 6))
    sample_fill = PatternFill("solid", fgColor="FEF3C7")
    for row in build_samples(spec):
        ws.append([row.get(c, "") for c in spec.columns])
        for cell in ws[ws.max_row]:
            cell.fill = sample_fill
    ws.freeze_panes = "A2"

    lists = wb.create_sheet("Lists")
    col = 0
    for idx, name in enumerate(spec.columns, start=1):
        g = guide.get(name)
        if not g or not g["allowed"] or "Multiple" in g["type"] or g["allowed_more"]:
            continue
        col += 1
        letter = get_column_letter(col)
        lists.cell(row=1, column=col, value=name)
        for r, value in enumerate(g["allowed"], start=2):
            lists.cell(row=r, column=col, value=value)
        # Dropdown suggests the known options but still allows typing new ones (lenient import).
        dv = DataValidation(type="list", formula1=f"=Lists!${letter}$2:${letter}${len(g['allowed']) + 1}",
                            allow_blank=True, showErrorMessage=False)
        ws.add_data_validation(dv)
        dv.add(f"{get_column_letter(idx)}2:{get_column_letter(idx)}{MAX_ROWS + 1}")
    lists.sheet_state = "hidden"

    gs = wb.create_sheet("Field guide")
    gs.append(["Column", "Label", "Required", "Type", "Allowed values", "Example", "Notes"])
    for cell in gs[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
    for name in spec.columns:
        g = guide.get(name)
        if not g:
            continue
        allowed = ", ".join(g["allowed"]) + (" … (more in the app)" if g["allowed_more"] else "") if g["allowed"] \
            else ""
        notes = "; ".join(x for x in [g["note"], str(g["help"] or ""),
                                      "Filled automatically if blank" if g["has_default"] else ""] if x)
        gs.append([name, g["label"], "Yes" if g["required"] else "No", g["type"], allowed, g["example"], notes])
    for letter, width in zip("ABCDEFG", (22, 26, 10, 30, 60, 30, 40)):
        gs.column_dimensions[letter].width = width
    for row in gs.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    info = wb.create_sheet("How to import", 0)
    for line in [
        [f"Import template — {spec.title}"],
        [""],
        ["1. Fill in the 'Data' sheet: one row per record. Do not rename the header row."],
        ["2. Blue headers are required. Hover over a header for its type and allowed values."],
        ["3. The yellow rows are SAMPLE ROWS: they are skipped unless you tick “Also import sample rows”."],
        ["4. Choice columns have dropdowns. New tags, categories and (for managers) statuses are created "
         "automatically; other unrecognised values are kept in the notes."],
        ["5. Dates: YYYY-MM-DD. Date & time: YYYY-MM-DD HH:MM. Multiple values: separate with ;"],
        ["6. Upload the file on the import page. If a row still has an error, nothing is imported and every "
         "problem is listed by row number."],
    ]:
        info.append(line)
    info["A1"].font = Font(bold=True, size=14)
    info.column_dimensions["A"].width = 110
    wb.active = wb.sheetnames.index("Data")
    buf = io.BytesIO()
    wb.save(buf)
    response = HttpResponse(buf.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{stem}.xlsx"'
    return response


# --------------------------------------------------------------------------- the page

def import_page(request, spec, audit=None, extra_context=None):
    """Handle template downloads (?template=…), uploads (POST) and render the import page."""
    kind = request.GET.get("template")
    if kind in ("csv", "csv_sample", "xlsx"):
        return template_response(spec, kind)
    from . import import_jobs

    result, job = None, None
    in_job = getattr(request, "_import_job", None) is not None
    if request.method == "GET" and request.GET.get("job"):
        job = import_jobs.load(request.GET["job"], request.user)
        if job["status"] == "done":
            if request.headers.get("HX-Request"):  # finished while the page was polling: reload it
                response = HttpResponse(status=204)
                response["HX-Redirect"] = request.get_full_path()
                return response
            if not job.get("delivered"):
                for level, text, tags in job.get("messages", []):
                    messages.add_message(request, level, text, extra_tags=tags)
                job["delivered"] = True
                import_jobs.save(job)
                if job.get("location"):
                    return redirect(job["location"])
            result, job = job.get("result"), None
        elif request.headers.get("HX-Request"):
            return render(request, "imports/_job_progress.html", {"job": job})
    if request.method == "POST":
        upload = UploadForm(request.POST, request.FILES)
        if upload.is_valid() and import_jobs.enabled() and not in_job:
            return redirect(f"{request.path}?job={import_jobs.start(request, upload.cleaned_data['file'])}")
        if upload.is_valid():
            try:
                headers, rows = read_table(upload.cleaned_data["file"])
            except ValueError as exc:
                upload.add_error("file", str(exc))
            else:
                result = run_import(spec, headers, rows,
                                    include_samples=upload.cleaned_data.get("include_samples", False),
                                    progress=getattr(request, "_import_progress", None))
                request._import_result = result
                if result["created"]:
                    if audit:
                        audit(result["created"])
                    if spec.on_success:
                        spec.on_success(result["created"])
                    skipped = f" ({result['skipped']} sample row(s) skipped)" if result["skipped"] else ""
                    messages.success(request, f"Imported {result['created']} record(s){skipped}.")
                    if result["adjustments"]:
                        summary = sorted({a for _, a in result["adjustments"]})
                        shown = "; ".join(summary[:6]) + (f"; +{len(summary) - 6} more" if len(summary) > 6 else "")
                        messages.info(request, f"Adjusted during import: {shown}.")
                    return redirect(spec.back_url)
                if result["errors"]:
                    messages.error(request, f"Import cancelled: {len(result['errors'])} row(s) need attention. "
                                            "Nothing was saved.")
                elif result["skipped"]:
                    messages.warning(request, f"All {result['skipped']} row(s) are marked “SAMPLE ROW”, so they were "
                                              "skipped. Replace them with your own data, or tick “Also import rows "
                                              "marked SAMPLE ROW” to import them as demo data.")
                else:
                    messages.warning(request, "The file contained no data rows.")
    else:
        upload = UploadForm()
    ctx = {"spec": spec, "form": upload, "result": result, "job": job, "guide": column_guide(spec),
           "samples": build_samples(spec)}
    ctx.update(extra_context or {})
    template = "imports/import_admin.html" if ctx.get("base_template") == "admin_panel/_base.html" \
        else "imports/import.html"
    return render(request, template, ctx)

import datetime
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils.html import format_html, format_html_join

from apps.accounts.permissions import accessible_products, is_org_admin, product_ids_for

from .models import Attachment, Category, CustomFieldDefinition, CustomFieldType, CustomFieldValue, Tag
from .statuses import default_status, status_choices

User = get_user_model()

CF_PREFIX = "cf__"


def bootstrapify(form):
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxInput,)):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, (forms.SelectMultiple, forms.CheckboxSelectMultiple)):
            widget.attrs.setdefault("class", "form-select")
            widget.attrs.setdefault("size", min(6, max(3, len(getattr(field, "choices", [])))))
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif isinstance(widget, forms.ClearableFileInput) or isinstance(widget, forms.FileInput):
            widget.attrs.setdefault("class", "form-control")
        else:
            widget.attrs.setdefault("class", "form-control")
        if isinstance(widget, forms.Textarea):
            widget.attrs["rows"] = min(int(widget.attrs.get("rows", 3)), 3)


def https_formfield(db_field, **kwargs):
    """ModelForm formfield_callback: URL fields assume https for scheme-less input (Django 6.0 default)."""
    if isinstance(db_field, models.URLField):
        kwargs.setdefault("assume_scheme", "https")
    return db_field.formfield(**kwargs)


class DatalistInput(forms.TextInput):
    """Free-text box whose browser suggestions are the field's choices."""

    choices = ()

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {})
        list_id = f"{attrs.get('id') or 'id_' + name}_options"
        attrs.update(list=list_id, autocomplete="off")
        options = format_html_join("", '<option value="{}"></option>', ((label,) for _, label in self.choices))
        return super().render(name, value, attrs, renderer) + format_html(
            '<datalist id="{}">{}</datalist>', list_id, options)


class CreatableModelChoiceField(forms.ModelChoiceField):
    """
    A reference typed as text. Matches an existing record by ``lookup`` (case-insensitive, across the whole
    table so inactive records are reused rather than duplicated); an unknown value becomes an unsaved record
    that RecordFormMixin saves only once the rest of the form is valid. Ids are still accepted (CSV import).
    """

    creates_missing = True

    def __init__(self, queryset, lookup="name", **kwargs):
        self.lookup = lookup
        self.max_length = queryset.model._meta.get_field(lookup).max_length
        kwargs.setdefault("widget", DatalistInput(attrs={"maxlength": self.max_length} if self.max_length else {}))
        super().__init__(queryset, empty_label=None, **kwargs)

    def label_from_instance(self, obj):
        return getattr(obj, self.lookup)

    def prepare_value(self, value):
        if isinstance(value, models.Model):
            return getattr(value, self.lookup)
        if isinstance(value, int):  # initial value from the instance
            obj = self.queryset.model.objects.filter(pk=value).first()
            return getattr(obj, self.lookup) if obj else value
        return value

    def to_python(self, value):
        value = str(value).strip() if value not in self.empty_values else ""
        if not value:
            return None
        model = self.queryset.model
        obj = model.objects.filter(**{f"{self.lookup}__iexact": value}).first()
        if obj is None and value.isdigit():
            obj = self.queryset.filter(pk=int(value)).first()
        if obj is None:
            if self.max_length and len(value) > self.max_length:
                raise ValidationError(f"Use at most {self.max_length} characters.")
            obj = model(**{self.lookup: value})
        return obj


class _DiscardNew(Exception):
    pass


def _date_widgets(model, fields):
    widgets = {}
    for name in fields:
        try:
            f = model._meta.get_field(name)
        except Exception:
            continue
        if isinstance(f, models.DateTimeField):
            widgets[name] = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
        elif isinstance(f, models.DateField):
            widgets[name] = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    return widgets


def assignable_users(user, product_ids=None):
    qs = User.objects.filter(is_active=True)
    if is_org_admin(user) and product_ids is None:
        return qs.order_by("first_name", "username")
    ids = product_ids if product_ids is not None else list(accessible_products(user).values_list("pk", flat=True))
    admins = Q(is_superuser=True) | Q(profile__org_role="org_admin")
    return qs.filter(Q(memberships__product_id__in=ids, memberships__is_active=True) | admins).distinct().order_by(
        "first_name", "username"
    )


def custom_field_definitions(resource_key, product=None):
    qs = CustomFieldDefinition.objects.filter(resource=resource_key, is_active=True)
    if product is not None:
        qs = qs.filter(Q(product__isnull=True) | Q(product=product))
    return qs.order_by("order", "label")


def build_custom_form_field(definition):
    kwargs = {"label": definition.label, "required": definition.required, "help_text": definition.help_text}
    t = definition.field_type
    choices = [(c, c) for c in (definition.choices or [])]
    if t == CustomFieldType.LONG_TEXT:
        return forms.CharField(widget=forms.Textarea, max_length=5000, **kwargs)
    if t == CustomFieldType.NUMBER:
        return forms.DecimalField(max_digits=18, decimal_places=4, **kwargs)
    if t == CustomFieldType.CURRENCY:
        return forms.DecimalField(max_digits=16, decimal_places=2, **kwargs)
    if t == CustomFieldType.DATE:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **kwargs)
    if t == CustomFieldType.URL:
        return forms.URLField(max_length=500, assume_scheme="https", **kwargs)
    if t == CustomFieldType.BOOLEAN:
        kwargs["required"] = False
        return forms.BooleanField(**kwargs)
    if t == CustomFieldType.SINGLE_SELECT:
        return forms.ChoiceField(choices=[("", "—")] + choices, **kwargs)
    if t == CustomFieldType.MULTI_SELECT:
        return forms.MultipleChoiceField(choices=choices, **kwargs)
    return forms.CharField(max_length=500, **kwargs)


def to_json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def from_json_value(definition, value):
    if value in (None, ""):
        return None
    try:
        if definition.field_type in (CustomFieldType.NUMBER, CustomFieldType.CURRENCY):
            return Decimal(str(value))
        if definition.field_type == CustomFieldType.DATE:
            return datetime.date.fromisoformat(str(value))
    except (InvalidOperation, ValueError):
        return None
    return value


class RecordFormMixin:
    """Applied to generated ModelForms: scopes choices to the user's permitted products."""

    def setup(self, user, resource, product=None):
        self.user = user
        self.resource = resource
        self.fixed_product = product
        model = resource.model
        writable_ids = product_ids_for(user, resource.module, "write")

        if "product" in self.fields:
            self.fields["product"].queryset = self.fields["product"].queryset.model.objects.filter(pk__in=writable_ids)
            self.fields["product"].empty_label = None if len(writable_ids) == 1 else "Select product…"
            if product is not None and not self.instance.pk:
                self.fields["product"].initial = product.pk
        if "shared_products" in self.fields:
            self.fields["shared_products"].queryset = accessible_products(user)
            self.fields["shared_products"].required = False
            self.fields["shared_products"].help_text = "Also show this record on these product dashboards."
        if "status" in self.fields or "status" in resource.form_fields:
            self.fields["status"] = forms.ChoiceField(choices=status_choices(resource.key), label="Status")
            current = self.instance.status if self.instance.pk else default_status(resource.key)
            if self.instance.pk and current and current not in dict(self.fields["status"].choices):
                self.fields["status"].choices = [(current, current)] + list(self.fields["status"].choices)
            self.fields["status"].initial = current
        if "assigned_to" in self.fields:
            self.fields["assigned_to"].queryset = assignable_users(user)
            self.fields["assigned_to"].label_from_instance = lambda u: u.get_full_name() or u.username
        if "category" in self.fields:
            qs = Category.objects.filter(is_active=True).filter(Q(resource="") | Q(resource=resource.key))
            if product is not None:
                qs = qs.filter(Q(product__isnull=True) | Q(product=product))
            self.fields["category"].queryset = qs
        if "tags" in self.fields:
            self.fields["tags"].queryset = Tag.objects.all()
            self.fields["tags"].required = False
        if "related_module" in self.fields:
            from .registry import registry

            self.fields["related_module"] = forms.ChoiceField(
                choices=[("", "—")] + [(mod.key, mod.label) for mod in registry.modules()],
                required=False, label="Related module",
            )
        # Scope FK choices to records the user can see (e.g. campaigns of permitted products).
        for name, field in self.fields.items():
            if not isinstance(field, forms.ModelChoiceField) or name in (
                    "product", "shared_products", "assigned_to", "category", "tags"):
                continue
            rel_model = field.queryset.model
            if hasattr(rel_model, "RESOURCE_KEY") and rel_model.RESOURCE_KEY:
                field.queryset = rel_model.objects.filter(product_id__in=writable_ids, is_archived=False)
            elif hasattr(rel_model, "is_active"):
                current_id = getattr(self.instance, f"{name}_id", None)
                field.queryset = rel_model.objects.filter(Q(is_active=True) | Q(pk=current_id))
        for name, lookup in resource.creatable_fks.items():
            old = self.fields.get(name)
            if old is not None:
                self.fields[name] = CreatableModelChoiceField(
                    old.queryset, lookup=lookup, required=old.required, label=old.label,
                    help_text=old.help_text or "Pick from the list or type a new name; it is added when you save.")

        # Custom fields
        target_product = product or (self.instance.product if self.instance.pk else None)
        self.custom_definitions = list(custom_field_definitions(resource.key, target_product))
        existing = {}
        if self.instance.pk:
            existing = {cv.definition_id: cv.value for cv in CustomFieldValue.objects.filter(
                content_type=ContentType.objects.get_for_model(model), object_id=self.instance.pk)}
        for d in self.custom_definitions:
            fname = CF_PREFIX + d.key
            self.fields[fname] = build_custom_form_field(d)
            if d.id in existing:
                self.fields[fname].initial = from_json_value(d, existing[d.id])
        bootstrapify(self)

    def clean(self):
        data = super().clean()
        product = data.get("product") or getattr(self.instance, "product", None)
        if product is not None and "product" in self.fields:
            from apps.accounts.permissions import has_level

            if not has_level(self.user, product, self.resource.module, "write"):
                self.add_error("product", "You do not have write access to this product.")
        for name in ("end_date", "end_at"):
            start_name = "start_date" if name == "end_date" else "start_at"
            if data.get(name) and data.get(start_name) and data[name] < data[start_name]:
                self.add_error(name, "End must be on or after the start.")
        if self.resource.clean:
            self.resource.clean(self, data)
        return data

    def _post_clean(self):
        # Save typed-in new references only if the whole form validates, so a failed submit adds nothing.
        new = [obj for name, obj in getattr(self, "cleaned_data", {}).items()
               if isinstance(self.fields.get(name), CreatableModelChoiceField) and obj is not None and obj.pk is None]
        if not new:
            return super()._post_clean()
        try:
            with transaction.atomic():
                for obj in new:
                    obj.save()
                super()._post_clean()
                if self._errors:
                    raise _DiscardNew
        except _DiscardNew:
            for obj in new:
                obj.pk = None
                obj._state.adding = True

    def save_custom_fields(self, instance):
        ct = ContentType.objects.get_for_model(instance.__class__)
        for d in self.custom_definitions:
            value = self.cleaned_data.get(CF_PREFIX + d.key)
            if value in (None, "", []):
                CustomFieldValue.objects.filter(definition=d, content_type=ct, object_id=instance.pk).delete()
            else:
                CustomFieldValue.objects.update_or_create(
                    definition=d, content_type=ct, object_id=instance.pk, defaults={"value": to_json_value(value)}
                )

    @property
    def standard_fields(self):
        return [self[n] for n in self.fields if not n.startswith(CF_PREFIX)]

    @property
    def custom_fields(self):
        return [self[n] for n in self.fields if n.startswith(CF_PREFIX)]


_form_cache = {}


def record_form_class(resource):
    if resource.key in _form_cache:
        return _form_cache[resource.key]
    model = resource.model
    fields = list(resource.form_fields)
    meta = type("Meta", (), {"model": model, "fields": fields, "widgets": _date_widgets(model, fields),
                             "formfield_callback": https_formfield})
    form_cls = type(f"{model.__name__}Form", (RecordFormMixin, forms.ModelForm), {"Meta": meta})
    _form_cache[resource.key] = form_cls
    return form_cls


def make_record_form(resource, user, data=None, files=None, instance=None, product=None, initial=None):
    cls = record_form_class(resource)
    form = cls(data=data, files=files, instance=instance, initial=initial)
    form.setup(user, resource, product=product)
    return form


def child_form_class(child):
    model = child.model
    meta = type("Meta", (), {"model": model, "fields": child.fields, "widgets": _date_widgets(model, child.fields),
                             "formfield_callback": https_formfield})
    return type(f"{model.__name__}Form", (forms.ModelForm,), {"Meta": meta})


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file", "description"]
        widgets = {"description": forms.TextInput(attrs={"placeholder": "Description (optional)"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class CSVImportForm(forms.Form):
    file = forms.FileField(help_text="UTF-8 encoded CSV. Download the template for the expected columns.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)

    def clean_file(self):
        from .validators import validate_csv_upload

        f = self.cleaned_data["file"]
        validate_csv_upload(f)
        return f

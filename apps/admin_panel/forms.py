import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import OrgRole
from apps.analytics.targets import METRIC_CHOICES
from apps.core.forms import bootstrapify, https_formfield
from apps.core.models import Category, CustomFieldDefinition, CustomFieldType, StatusOption, Tag, Target
from apps.core.registry import registry
from apps.investors.models import InvestorCategory
from apps.listings.models import ListingPlatform
from apps.products.models import AccessLevel, Product, ProductMembership, ProductRole

User = get_user_model()

COLOR_CHOICES = [(c, c.title()) for c in
                 ["secondary", "primary", "info", "success", "warning", "danger", "dark", "light", "indigo",
                  "purple", "teal", "orange", "pink"]]


def resource_choices(blank=False):
    choices = [(r.key, f"{registry.module(r.module).label} — {r.label_plural}") for r in registry.resources()]
    return ([("", "All modules")] if blank else []) + sorted(choices, key=lambda c: c[1])


class BootstrapModelForm(forms.ModelForm):
    def __init_subclass__(cls, **kwargs):
        # Django reads formfield_callback only from each form's own Meta; runs before the metaclass does.
        super().__init_subclass__(**kwargs)
        meta = cls.__dict__.get("Meta")
        if meta is not None and not hasattr(meta, "formfield_callback"):
            meta.formfield_callback = https_formfield

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        bootstrapify(self)


class ProductForm(BootstrapModelForm):
    class Meta:
        model = Product
        fields = ["name", "slug", "tagline", "description", "logo", "brand_color", "website", "is_active",
                  "display_order"]
        widgets = {"brand_color": forms.TextInput(attrs={"type": "color"})}

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        reserved = {"new", "records", "admin", "api"}
        if slug in reserved:
            raise forms.ValidationError("This slug is reserved.")
        return slug


class StatusOptionForm(BootstrapModelForm):
    resource = forms.ChoiceField(choices=resource_choices)
    color = forms.ChoiceField(choices=COLOR_CHOICES)

    class Meta:
        model = StatusOption
        fields = ["resource", "key", "label", "state", "color", "order", "is_active"]


class CategoryForm(BootstrapModelForm):
    resource = forms.ChoiceField(choices=lambda: resource_choices(blank=True), required=False)

    class Meta:
        model = Category
        fields = ["name", "resource", "product", "color", "is_active"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class TagForm(BootstrapModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class CustomFieldForm(BootstrapModelForm):
    resource = forms.ChoiceField(choices=resource_choices)
    choices_text = forms.CharField(
        label="Options", required=False, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="For single/multi-select fields: one option per line.",
    )

    class Meta:
        model = CustomFieldDefinition
        fields = ["resource", "product", "label", "key", "field_type", "required", "help_text", "order",
                  "show_in_list", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["choices_text"].initial = "\n".join(self.instance.choices or [])
            self.fields["key"].disabled = True
            self.fields["resource"].disabled = True

    def clean_key(self):
        key = self.cleaned_data["key"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", key or ""):
            raise forms.ValidationError("Use lowercase letters, numbers and underscores, starting with a letter.")
        return key

    def clean(self):
        data = super().clean()
        options = [o.strip() for o in (data.get("choices_text") or "").splitlines() if o.strip()]
        if data.get("field_type") in (CustomFieldType.SINGLE_SELECT, CustomFieldType.MULTI_SELECT) and not options:
            self.add_error("choices_text", "Add at least one option for select fields.")
        if len(options) > 100:
            self.add_error("choices_text", "At most 100 options.")
        self.instance.choices = [o[:100] for o in options]
        return data


class TargetForm(BootstrapModelForm):
    metric = forms.ChoiceField(choices=METRIC_CHOICES)

    class Meta:
        model = Target
        fields = ["product", "metric", "label", "target_value", "period_start", "period_end", "notes"]
        widgets = {"period_start": forms.DateInput(attrs={"type": "date"}),
                   "period_end": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user is not None:
            from apps.accounts.permissions import can_manage_product

            self.fields["product"].queryset = Product.objects.filter(
                pk__in=[p.pk for p in Product.objects.all() if can_manage_product(self.user, p)])

    def clean(self):
        data = super().clean()
        if data.get("period_start") and data.get("period_end") and data["period_end"] < data["period_start"]:
            self.add_error("period_end", "End must be on or after start.")
        return data


class ListingPlatformForm(BootstrapModelForm):
    class Meta:
        model = ListingPlatform
        fields = ["name", "website_url", "kind", "description", "is_active", "display_order"]


class InvestorCategoryForm(BootstrapModelForm):
    class Meta:
        model = InvestorCategory
        fields = ["name", "description", "is_active", "display_order"]


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)
    org_role = forms.ChoiceField(choices=OrgRole.choices, required=False, label="Organization role")
    job_title = forms.CharField(required=False, max_length=100)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        self.acting_user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        bootstrapify(self)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        elif p1:
            try:
                validate_password(p1, self.instance)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data


class UserEditForm(UserCreateForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].required = False
        self.fields["password2"].required = False
        self.fields["password1"].help_text = "Leave blank to keep the current password."
        profile = getattr(self.instance, "profile", None)
        if profile:
            self.fields["org_role"].initial = profile.org_role
            self.fields["job_title"].initial = profile.job_title
        if self.instance.is_superuser:
            self.fields["org_role"].disabled = True
            self.fields["org_role"].help_text = "Super Admin (managed with createsuperuser / Django admin)."


class UserImportForm(BootstrapModelForm):
    """Bulk user creation. Imported users get no password and set one via “Forgot password”."""

    org_role = forms.ChoiceField(choices=OrgRole.choices, required=False, label="Organization role")
    job_title = forms.CharField(required=False, max_length=100)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["is_active"].initial = True

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class ProductImportForm(ProductForm):
    class Meta(ProductForm.Meta):
        fields = ["name", "slug", "tagline", "description", "brand_color", "website", "is_active", "display_order"]


class MembershipForm(BootstrapModelForm):
    class Meta:
        model = ProductMembership
        fields = ["user", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        self.product = kwargs.pop("product", None)
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by("username")
        self.fields["user"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.email})"
        if self.instance.pk:
            self.fields["user"].disabled = True

    def clean_user(self):
        user = self.cleaned_data["user"]
        if not self.instance.pk and ProductMembership.objects.filter(user=user, product=self.product).exists():
            raise forms.ValidationError("This user is already a member of this product.")
        return user


class ModulePermissionsForm(forms.Form):
    """One select per module: role default or an explicit override."""

    def __init__(self, membership, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.membership = membership
        overrides = {p.module: p.level for p in membership.module_permissions.all()}
        from apps.accounts.permissions import ROLE_DEFAULTS

        for module in registry.modules(include_tasks=True):
            default = ROLE_DEFAULTS[membership.role](module.key)
            self.fields[module.key] = forms.ChoiceField(
                label=module.label,
                choices=[("", f"Role default ({dict(AccessLevel.choices)[default]})")] + list(AccessLevel.choices),
                required=False, initial=overrides.get(module.key, ""),
            )
        bootstrapify(self)


class BroadcastForm(forms.Form):
    title = forms.CharField(max_length=200)
    message = forms.CharField(widget=forms.Textarea, required=False, max_length=2000)
    url = forms.CharField(max_length=300, required=False, help_text="Optional internal link, e.g. /tasks/")
    product = forms.ModelChoiceField(queryset=Product.objects.all(), required=False,
                                     empty_label="All active users", label="Recipients")
    level = forms.ChoiceField(choices=[("info", "Info"), ("success", "Success"), ("warning", "Warning"),
                                       ("danger", "Urgent")])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        bootstrapify(self)

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        if url and not url.startswith("/"):
            raise forms.ValidationError("Use an internal path starting with /.")
        if url.startswith("//"):
            raise forms.ValidationError("Use an internal path.")
        return url


ROLE_CHOICES = ProductRole.choices

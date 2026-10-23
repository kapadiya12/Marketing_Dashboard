import os

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .validators import validate_attachment_upload


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class RecordQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_archived=False)

    def archived(self):
        return self.filter(is_archived=True)


class BaseRecord(TimeStampedModel):
    """
    Common fields for every activity record across the nine modules (and tasks).

    ``RESOURCE_KEY`` links the model to its entry in ``apps.core.registry``.
    ``status`` values are configurable per resource through ``StatusOption``.
    """

    RESOURCE_KEY = None

    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT, related_name="%(app_label)s_%(class)s_records"
    )
    shared_products = models.ManyToManyField(
        "products.Product",
        blank=True,
        related_name="%(app_label)s_%(class)s_shared",
        help_text="Other products this record is also relevant to.",
    )
    status = models.CharField(max_length=40, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_assigned",
        verbose_name="Assigned to",
    )
    category = models.ForeignKey(
        "core.Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="%(app_label)s_%(class)s_set"
    )
    tags = models.ManyToManyField("core.Tag", blank=True, related_name="%(app_label)s_%(class)s_set")
    notes = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False
    )
    attachments = GenericRelation("core.Attachment")
    custom_values = GenericRelation("core.CustomFieldValue")

    objects = RecordQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @property
    def resource(self):
        from .registry import registry

        return registry.get(self.RESOURCE_KEY)

    def get_absolute_url(self):
        return reverse("records:detail", kwargs={"resource": self.RESOURCE_KEY, "pk": self.pk})

    def status_option(self):
        from .statuses import get_status

        return get_status(self.RESOURCE_KEY, self.status)

    def archive(self, user=None):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.updated_by = user
        self.save(update_fields=["is_archived", "archived_at", "updated_by", "updated_at"])

    def restore(self, user=None):
        self.is_archived = False
        self.archived_at = None
        self.updated_by = user
        self.save(update_fields=["is_archived", "archived_at", "updated_by", "updated_at"])

    def custom_field_map(self):
        """Return {definition_key: value} for this record's custom field values."""
        return {cv.definition.key: cv.value for cv in self.custom_values.select_related("definition")}


class StatusState(models.TextChoices):
    OPEN = "open", "Open / pending"
    COMPLETED = "completed", "Completed (success)"
    CLOSED = "closed", "Closed (not successful)"


class StatusOption(models.Model):
    """Configurable status values for a resource (e.g. listing approval states)."""

    resource = models.CharField(max_length=40, db_index=True)
    key = models.SlugField(max_length=40)
    label = models.CharField(max_length=60)
    state = models.CharField(max_length=10, choices=StatusState.choices, default=StatusState.OPEN)
    color = models.CharField(max_length=20, default="secondary", help_text="Bootstrap colour name.")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["resource", "order", "label"]
        constraints = [models.UniqueConstraint(fields=["resource", "key"], name="unique_status_per_resource")]

    def __str__(self):
        return f"{self.resource}: {self.label}"


class Category(TimeStampedModel):
    resource = models.CharField(max_length=40, blank=True, help_text="Leave blank to use for all modules.")
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank for all products."
    )
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=90, blank=True)
    color = models.CharField(max_length=7, default="#64748B")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["resource", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:90]
        super().save(*args, **kwargs)


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default="#6366F1")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def attachment_upload_path(instance, filename):
    base, ext = os.path.splitext(filename)
    safe = slugify(base)[:60] or "file"
    return f"attachments/{timezone.now():%Y/%m}/{safe}{ext.lower()}"


class Attachment(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, null=True, blank=True)
    file = models.FileField(upload_to=attachment_upload_path, validators=[validate_attachment_upload])
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"], name="attachment_target_idx")]

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        return os.path.splitext(self.original_name)[1].lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class CustomFieldType(models.TextChoices):
    TEXT = "text", "Text"
    LONG_TEXT = "long_text", "Long text"
    NUMBER = "number", "Number"
    CURRENCY = "currency", "Currency"
    DATE = "date", "Date"
    URL = "url", "URL"
    BOOLEAN = "boolean", "Yes / No"
    SINGLE_SELECT = "single_select", "Single select"
    MULTI_SELECT = "multi_select", "Multi-select"


class CustomFieldDefinition(TimeStampedModel):
    resource = models.CharField(max_length=40, db_index=True)
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Leave blank to show this field for every product.",
    )
    key = models.SlugField(max_length=50, help_text="Internal identifier (letters, numbers, underscores).")
    label = models.CharField(max_length=80)
    field_type = models.CharField(max_length=20, choices=CustomFieldType.choices, default=CustomFieldType.TEXT)
    choices = models.JSONField(default=list, blank=True, help_text="Options for select fields.")
    required = models.BooleanField(default=False)
    help_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)
    show_in_list = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["resource", "order", "label"]
        constraints = [models.UniqueConstraint(fields=["resource", "key"], name="unique_custom_field_key")]

    def __str__(self):
        return f"{self.resource}: {self.label}"


class CustomFieldValue(models.Model):
    definition = models.ForeignKey(CustomFieldDefinition, on_delete=models.CASCADE, related_name="values")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    value = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["definition", "content_type", "object_id"], name="unique_custom_value")
        ]
        indexes = [models.Index(fields=["content_type", "object_id"], name="custom_value_target_idx")]


class Notification(models.Model):
    LEVELS = [("info", "Info"), ("success", "Success"), ("warning", "Warning"), ("danger", "Urgent")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=500, blank=True)
    level = models.CharField(max_length=10, choices=LEVELS, default="info")
    is_read = models.BooleanField(default=False, db_index=True)
    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Target(TimeStampedModel):
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="targets")
    metric = models.CharField(max_length=50)
    label = models.CharField(max_length=120, blank=True)
    target_value = models.DecimalField(max_digits=14, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["product", "period_start", "metric"]
        constraints = [
            models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="target_period_valid"),
            models.CheckConstraint(condition=models.Q(target_value__gte=0), name="target_value_non_negative"),
        ]

    def __str__(self):
        return f"{self.product} · {self.label or self.metric}"


class DashboardItem(models.Model):
    """Ordering and visibility of dashboard sections / KPI cards (org default when product is blank)."""

    SECTION = "section"
    KPI = "kpi"
    TYPES = [(SECTION, "Section"), (KPI, "KPI card")]

    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, null=True, blank=True)
    item_type = models.CharField(max_length=10, choices=TYPES)
    key = models.CharField(max_length=50)
    order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ["item_type", "order"]

    def __str__(self):
        return f"{self.product or 'Organization'} · {self.item_type}:{self.key}"


class ModuleSetting(models.Model):
    """Per-resource table configuration."""

    resource = models.CharField(max_length=40, unique=True)
    list_columns = models.JSONField(default=list, blank=True)
    page_size = models.PositiveIntegerField(default=25)

    def __str__(self):
        return f"Settings: {self.resource}"

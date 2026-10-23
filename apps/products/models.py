from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_upload

hex_color_validator = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Enter a hex colour such as #4F46E5.")


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Product(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="product_logos/", blank=True, validators=[validate_image_upload])
    brand_color = models.CharField(max_length=7, default="#4F46E5", validators=[hex_color_validator])
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)
    assigned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ProductMembership", related_name="products", blank=True
    )

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:60]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:dashboard", kwargs={"slug": self.slug})

    @property
    def initials(self):
        parts = [p for p in self.name.replace("-", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.name[:2].upper()

    def enabled_module_keys(self):
        """Module keys enabled for this product (modules without a config row are enabled)."""
        from apps.core.registry import registry

        disabled = set(self.module_configs.filter(is_enabled=False).values_list("module", flat=True))
        return [m.key for m in registry.modules() if m.key not in disabled]


class ProductRole(models.TextChoices):
    PRODUCT_MANAGER = "product_manager", "Product Manager"
    MARKETING_MANAGER = "marketing_manager", "Marketing Manager"
    SALES_BD = "sales_bd", "Sales / Business Development"
    TEAM_MEMBER = "team_member", "Team Member"
    VIEWER = "viewer", "Viewer"


class ProductMembership(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=30, choices=ProductRole.choices, default=ProductRole.TEAM_MEMBER)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product__display_order", "user__username"]
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="unique_product_membership")]

    def __str__(self):
        return f"{self.user} @ {self.product} ({self.get_role_display()})"


class AccessLevel(models.TextChoices):
    NONE = "none", "No access"
    READ = "read", "Read only"
    WRITE = "write", "Read & write"
    MANAGE = "manage", "Manage"


class MembershipModulePermission(models.Model):
    """Overrides the role default access level for one module within a membership."""

    membership = models.ForeignKey(ProductMembership, on_delete=models.CASCADE, related_name="module_permissions")
    module = models.CharField(max_length=40)
    level = models.CharField(max_length=10, choices=AccessLevel.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "module"], name="unique_membership_module_permission")
        ]

    def __str__(self):
        return f"{self.membership} · {self.module}: {self.level}"


class ProductModuleConfiguration(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="module_configs")
    module = models.CharField(max_length=40)
    is_enabled = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    display_name = models.CharField(max_length=80, blank=True, help_text="Optional label override.")

    class Meta:
        ordering = ["product", "display_order", "module"]
        constraints = [models.UniqueConstraint(fields=["product", "module"], name="unique_product_module_config")]

    def __str__(self):
        return f"{self.product} · {self.module} ({'on' if self.is_enabled else 'off'})"

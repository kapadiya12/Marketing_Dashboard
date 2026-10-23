from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class OrgRole(models.TextChoices):
    NONE = "", "Product-level roles only"
    ORG_ADMIN = "org_admin", "Organization Admin"


class UserProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    org_role = models.CharField(max_length=20, choices=OrgRole.choices, blank=True, default="")
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    default_product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Profile: {self.user}"

    @property
    def role_label(self):
        if self.user.is_superuser:
            return "Super Admin"
        if self.org_role == OrgRole.ORG_ADMIN:
            return "Organization Admin"
        return "Member"

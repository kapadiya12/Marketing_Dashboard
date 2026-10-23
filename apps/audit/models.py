from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        ARCHIVE = "archive", "Archived"
        RESTORE = "restore", "Restored"
        STATUS = "status", "Status changed"
        IMPORT = "import", "Imported"
        EXPORT = "export", "Exported"
        ATTACH = "attach", "Attachment added"
        DETACH = "detach", "Attachment removed"
        CONFIG = "config", "Configuration changed"
        LOGIN = "login", "Logged in"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOGOUT = "logout", "Logged out"
        PERMISSION = "permission", "Permissions changed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    resource = models.CharField(max_length=40, blank=True, db_index=True)
    product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    message = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"], name="audit_target_idx")]

    def __str__(self):
        return f"{self.get_action_display()} · {self.object_repr}"

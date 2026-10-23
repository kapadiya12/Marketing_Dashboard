"""
REST API generated from the resource registry. Every endpoint uses the same
permission-scoped querysets as the HTML views:

    GET/POST        /api/v1/records/<resource>/
    GET/PATCH/DEL   /api/v1/records/<resource>/<id>/
    GET             /api/v1/dashboard/metrics/?product=<slug>&period=30d
    GET             /api/v1/products/
"""
from django.http import Http404
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import accessible_products, has_level, product_ids_for, scoped_queryset
from apps.analytics.services import DashboardData
from apps.audit.models import AuditLog
from apps.audit.services import diff_instances, log_action, snapshot
from apps.core.filtering import apply_filters
from apps.core.periods import resolve_period
from apps.core.registry import registry
from apps.core.statuses import status_choices


_serializer_cache = {}


def serializer_for(resource):
    if resource.key in _serializer_cache:
        return _serializer_cache[resource.key]
    model = resource.model
    fields = ["id"] + list(resource.form_fields) + ["is_archived", "created_at", "updated_at"]

    def validate_status(self, value):
        if value not in dict(status_choices(resource.key)):
            raise serializers.ValidationError("Invalid status for this module.")
        return value

    def validate_product(self, value):
        request = self.context["request"]
        if not has_level(request.user, value, resource.module, "write"):
            raise serializers.ValidationError("You do not have write access to this product.")
        return value

    meta = type("Meta", (), {"model": model, "fields": fields,
                             "read_only_fields": ["is_archived", "created_at", "updated_at"]})
    cls = type(f"{model.__name__}Serializer", (serializers.ModelSerializer,), {
        "Meta": meta, "validate_status": validate_status, "validate_product": validate_product,
        "product_slug": serializers.SlugRelatedField(source="product", slug_field="slug", read_only=True),
    })
    cls.Meta.fields = fields + ["product_slug"]
    _serializer_cache[resource.key] = cls
    return cls


class ResourceViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.resource = registry.get(kwargs.get("resource"))
        if self.resource is None:
            raise Http404
        if not product_ids_for(request.user, self.resource.module, "read"):
            raise PermissionDenied("No access to this module.")
        self.ordering_fields = list(self.resource.sort_fields) + ["created_at", "updated_at"]

    def get_serializer_class(self):
        return serializer_for(self.resource)

    def get_queryset(self):
        level = "read" if self.request.method in permissions.SAFE_METHODS else "write"
        if self.request.method == "DELETE":
            level = "manage"
        qs = scoped_queryset(self.request.user, self.resource, level).select_related("product", "assigned_to")
        products = {p.slug: p for p in accessible_products(self.request.user)}
        return apply_filters(qs, self.resource, self.request.query_params, products)

    def get_object(self):
        obj = scoped_queryset(self.request.user, self.resource, "read").filter(pk=self.kwargs["pk"]).first()
        if obj is None:
            raise Http404
        if self.request.method not in permissions.SAFE_METHODS:
            level = "manage" if self.request.method == "DELETE" else "write"
            if not has_level(self.request.user, obj.product_id, self.resource.module, level):
                raise PermissionDenied("Insufficient permission for this record.")
        return obj

    def perform_create(self, serializer):
        if not product_ids_for(self.request.user, self.resource.module, "write"):
            raise PermissionDenied
        if self.resource.clean:
            class _Shim:
                instance = serializer.Meta.model()
                errors = {}

                def add_error(self, field, msg):
                    self.errors.setdefault(field, []).append(msg)
            shim = _Shim()
            self.resource.clean(shim, serializer.validated_data)
            if shim.errors:
                raise ValidationError(shim.errors)
        obj = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        log_action(AuditLog.Action.CREATE, obj, self.request.user, message="Created via API")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        obj = serializer.save(updated_by=self.request.user)
        log_action(AuditLog.Action.UPDATE, obj, self.request.user, changes=diff_instances(before, snapshot(obj)),
                   message="Updated via API")

    def perform_destroy(self, instance):
        log_action(AuditLog.Action.DELETE, instance, self.request.user, message="Deleted via API")
        instance.delete()


@api_view(["GET"])
def dashboard_metrics(request):
    products = accessible_products(request.user).filter(is_active=True)
    slug = request.query_params.get("product")
    product = products.filter(slug=slug).first() if slug else None
    if slug and product is None:
        return Response({"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND)
    data = DashboardData(request.user, [product] if product else list(products), resolve_period(request.query_params),
                         product=product)
    k = data.kpis()
    return Response({key: (float(v) if hasattr(v, "quantize") else v) for key, v in k.items()})


@api_view(["GET"])
def product_list(request):
    return Response([
        {"id": p.id, "name": p.name, "slug": p.slug, "description": p.description, "brand_color": p.brand_color,
         "is_active": p.is_active, "enabled_modules": p.enabled_module_keys()}
        for p in accessible_products(request.user)
    ])


@api_view(["GET"])
def resource_list(request):
    return Response([
        {"key": r.key, "module": r.module, "label": r.label_plural,
         "url": request.build_absolute_uri(f"/api/v1/records/{r.key}/")}
        for r in registry.resources() if product_ids_for(request.user, r.module, "read")
    ])

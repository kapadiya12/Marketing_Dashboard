from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import is_org_admin
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.forms import bootstrapify

from .models import IntegrationConfiguration
from .providers import PROVIDERS, get_provider


def _require_admin(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not is_org_admin(request.user):
        raise PermissionDenied("Only organization administrators can manage integrations.")


def integration_list(request):
    _require_admin(request)
    configs = {c.provider: c for c in IntegrationConfiguration.objects.filter(product__isnull=True)}
    rows = []
    for key, provider in PROVIDERS.items():
        cfg = configs.get(key)
        rows.append({"provider": provider, "config": cfg,
                     "status": cfg.get_status_display() if cfg else "Not Configured",
                     "status_key": cfg.status if cfg else "not_configured"})
    return render(request, "integrations/list.html", {"rows": rows})


class CredentialForm(forms.Form):
    is_enabled = forms.BooleanField(required=False, label="Enabled")

    def __init__(self, provider, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.provider = provider
        settings = config.settings if config else {}
        for name, label, secret in provider.credential_fields:
            if secret:
                self.fields[name] = forms.CharField(
                    label=label, required=False, widget=forms.PasswordInput(render_value=False),
                    help_text="Stored encrypted. Leave blank to keep the current value." if config and
                    config.secrets.get(name) else "Stored encrypted.",
                )
            else:
                self.fields[name] = forms.CharField(label=label, required=False, initial=settings.get(name, ""),
                                                    max_length=300)
        self.fields["is_enabled"].initial = config.is_enabled if config else False
        bootstrapify(self)


def integration_edit(request, provider):
    _require_admin(request)
    prov = get_provider(provider)
    if prov is None:
        raise PermissionDenied
    config = IntegrationConfiguration.objects.filter(provider=provider, product__isnull=True).first()
    if request.method == "POST":
        form = CredentialForm(prov, config, request.POST)
        if form.is_valid():
            config = config or IntegrationConfiguration(provider=provider, display_name=prov.label)
            secrets = config.secrets
            settings = dict(config.settings or {})
            for name, _label, secret in prov.credential_fields:
                value = form.cleaned_data.get(name, "").strip()
                if secret:
                    if value:
                        secrets[name] = value
                else:
                    settings[name] = value
            config.settings = settings
            config.set_secrets(secrets)
            config.is_enabled = form.cleaned_data["is_enabled"]
            # Saving credentials never marks a connection as live; it must be tested.
            config.status = IntegrationConfiguration.Status.NOT_CONFIGURED
            config.save()
            log_action(AuditLog.Action.CONFIG, config, request.user, message=f"Updated {prov.label} credentials")
            messages.success(request, f"{prov.label} settings saved. Run “Test connection” to verify.")
            return redirect("integrations:list")
    else:
        form = CredentialForm(prov, config)
    return render(request, "integrations/edit.html", {"provider": prov, "config": config, "form": form})


@require_POST
def integration_test(request, provider):
    _require_admin(request)
    prov = get_provider(provider)
    config = get_object_or_404(IntegrationConfiguration, provider=provider, product__isnull=True)
    result = prov.test_connection(config)
    config.status = result.status
    config.last_tested_at = timezone.now()
    config.last_error = "" if result.status == "connected" else result.message
    config.save()
    log_action(AuditLog.Action.CONFIG, config, request.user, message=f"Tested {prov.label}: {result.status}")
    level = messages.SUCCESS if result.status == "connected" else messages.WARNING
    messages.add_message(request, level, f"{prov.label}: {config.get_status_display()} — {result.message}")
    return redirect("integrations:list")


@require_POST
def integration_disconnect(request, provider):
    _require_admin(request)
    config = get_object_or_404(IntegrationConfiguration, provider=provider, product__isnull=True)
    config.set_secrets({})
    config.is_enabled = False
    config.status = IntegrationConfiguration.Status.NOT_CONFIGURED
    config.token_expires_at = None
    config.save()
    log_action(AuditLog.Action.CONFIG, config, request.user, message="Credentials removed")
    messages.success(request, "Stored credentials removed.")
    return redirect("integrations:list")

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse_lazy

from apps.core.forms import bootstrapify

from .forms import ThrottledAuthenticationForm
from .permissions import accessible_products, module_levels_for_user


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = ThrottledAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        from apps.products.models import Product

        ctx = super().get_context_data(**kwargs)
        ctx["login_products"] = Product.objects.filter(is_active=True).only("name", "brand_color")[:10]
        return ctx


class BootstrapFormMixin:
    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        bootstrapify(form)
        return form


class PasswordChangeView(BootstrapFormMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Your password was changed.")
        return super().form_valid(form)


class PasswordResetView(BootstrapFormMixin, auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetConfirmView(BootstrapFormMixin, auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


@login_required
def profile(request):
    rows = []
    for p in accessible_products(request.user):
        rows.append({"product": p, "levels": module_levels_for_user(request.user, p)})
    from apps.core.registry import registry

    return render(request, "accounts/profile.html", {"rows": rows, "modules": registry.modules(include_tasks=True)})

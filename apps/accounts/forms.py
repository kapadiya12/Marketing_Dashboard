from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.audit.middleware import client_ip

from . import throttle


class ThrottledAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": "Too many failed sign-in attempts. Please wait a few minutes and try again.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "form-control form-control-lg", "autofocus": True,
                                                     "placeholder": "Username"})
        self.fields["password"].widget.attrs.update({"class": "form-control form-control-lg",
                                                     "placeholder": "Password"})

    def clean(self):
        username = self.cleaned_data.get("username")
        ip = client_ip(self.request)
        if throttle.is_locked(username, ip):
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            data = super().clean()
        except forms.ValidationError:
            throttle.register_failure(username, ip)
            raise
        throttle.reset(username, ip)
        return data

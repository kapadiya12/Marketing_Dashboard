"""Test settings: production-like (DEBUG=False) but without HTTPS redirects or the static manifest."""
import os
import tempfile

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-production-0123456789abcdef")
os.environ.setdefault("DJANGO_DEBUG", "False")

from .settings import *  # noqa: E402,F401,F403
from .settings import DATABASES, STORAGES  # noqa: E402

# Never run tests against the live Turso database: exercise the same backend on a local libSQL file.
if DATABASES["default"]["ENGINE"] == "config.turso_backend" or os.environ.get("TEST_WITH_TURSO_BACKEND"):
    _test_db = os.path.join(tempfile.mkdtemp(prefix="bizdev-test-db-"), "test.db")
    DATABASES = {"default": {"ENGINE": "config.turso_backend", "NAME": _test_db, "TEST": {"NAME": _test_db}}}

SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
STORAGES = {**STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="bizdev-test-media-")
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
STATIC_ROOT = tempfile.mkdtemp(prefix="bizdev-test-static-")

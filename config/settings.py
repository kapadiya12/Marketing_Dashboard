"""
Django settings for the multi-product business development dashboard.

All environment-specific values come from environment variables (optionally a
local ``.env`` file). The database is Turso when ``TURSO_DATABASE_URL`` is set,
otherwise PostgreSQL via ``DATABASE_URL``; when neither is set, a local SQLite
file is used for development only.
"""
import tempfile
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_SECURE_SSL_REDIRECT=(bool, True),
    DJANGO_SECURE_HSTS_SECONDS=(int, 31536000),
    MAX_UPLOAD_SIZE_MB=(int, 15),
    LOGIN_MAX_ATTEMPTS=(int, 5),
    LOGIN_LOCKOUT_MINUTES=(int, 15),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DJANGO_DEBUG")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-development-only-key-do-not-use-in-production"
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=False")

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("DJANGO_CSRF_TRUSTED_ORIGINS")

# Render (https://render.com) provides the public hostname automatically.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third party
    "rest_framework",
    "django_filters",
    # Platform
    "apps.core",
    "apps.accounts",
    "apps.products",
    "apps.audit",
    "apps.tasks",
    "apps.analytics",
    "apps.integrations",
    "apps.email_marketing",
    "apps.admin_panel",
    "apps.api",
    # Nine activity modules
    "apps.listings",
    "apps.community_marketing",
    "apps.seo_optimization",
    "apps.advertising",
    "apps.events",
    "apps.outreach",
    "apps.meetings",
    "apps.consultants",
    "apps.investors",
    "apps.social_media",
    "apps.cold_calls",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.RequestContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database: Turso via TURSO_DATABASE_URL + TURSO_AUTH_TOKEN, else PostgreSQL via DATABASE_URL.
# SQLite fallback for local development only.
if env("TURSO_DATABASE_URL", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "config.turso_backend",
            "NAME": env("TURSO_DATABASE_URL"),
            # TURSO_REPLICA_DIR: keep embedded replicas there (local reads; strongly recommended when deployed).
            "OPTIONS": {"auth_token": env("TURSO_AUTH_TOKEN", default=""),
                        "replica_dir": env("TURSO_REPLICA_DIR", default="")},
            "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
            "ATOMIC_REQUESTS": False,
        }
    }
elif env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
    DATABASES["default"]["ATOMIC_REQUESTS"] = False
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

MAX_UPLOAD_SIZE = env("MAX_UPLOAD_SIZE_MB") * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = [
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "csv", "txt", "key", "odt", "ods", "odp", "zip",
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "analytics:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"
LOGIN_MAX_ATTEMPTS = env("LOGIN_MAX_ATTEMPTS")
LOGIN_LOCKOUT_SECONDS = env("LOGIN_LOCKOUT_MINUTES") * 60

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "business-dashboard",
    }
}
if env("REDIS_URL", default=""):
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="dashboard@localhost")

INTEGRATION_ENCRYPTION_KEY = env("INTEGRATION_ENCRYPTION_KEY", default="")

# Email marketing system (Outreach Console): one-click sign-in from Cold Email and the main dashboard's
# "Email marketing" box. The secret must equal DASHBOARD_LINK_SECRET there (32+ characters).
EMAIL_MARKETING_URL = env("EMAIL_MARKETING_URL", default="").rstrip("/")
EMAIL_MARKETING_SECRET = env("EMAIL_MARKETING_SECRET", default="")
EMAIL_MARKETING_TIMEOUT = env.int("EMAIL_MARKETING_TIMEOUT", default=12)
# Dashboard product slug -> email system product name, only where the names differ.
EMAIL_MARKETING_PRODUCTS = {"rcsl": "RCSL"}

# Imports run in a separate process (apps/core/import_jobs.py): on by default with Turso, where a long
# import inside a web request freezes that web worker. Jobs (upload + status) are kept in IMPORT_JOB_DIR.
IMPORT_IN_BACKGROUND = env.bool("IMPORT_IN_BACKGROUND", default=bool(env("TURSO_DATABASE_URL", default="")))
IMPORT_JOB_DIR = env("IMPORT_JOB_DIR", default=str(Path(tempfile.gettempdir()) / "bizdev-import-jobs"))

CURRENCY_SYMBOL = env("CURRENCY_SYMBOL", default="₹")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "2000/hour"},
}

# Security
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # HTMX reads the token from the cookie-free meta tag; keep default
SESSION_COOKIE_AGE = 60 * 60 * 12
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT")
    SECURE_HSTS_SECONDS = env("DJANGO_SECURE_HSTS_SECONDS")
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

# BizDev Hub — Multi-Product Marketing & Business Development Dashboard

A Django 5.2 application for managing marketing, sales, business development, online visibility, customer
relationships and investor outreach across six product workspaces (ProcEaze, ShiftEaze, RicRoot, RCSL,
PayEaze, Veracity) and nine activity modules.

- **Backend:** Django 5.2, Django REST Framework, django-filter, Turso (via `TURSO_DATABASE_URL`) or
  PostgreSQL (via `DATABASE_URL`)
- **Frontend:** Django templates, Bootstrap 5.3, Bootstrap Icons, Chart.js 4, HTMX 1.9
- **Deployment:** Gunicorn + WhiteNoise, environment-based configuration

---

## 1. Quick start (local development)

Requires Python 3.11+ (3.12 recommended).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # Windows: copy .env.example .env
python manage.py migrate
python manage.py seed_initial        # six products, module configs, statuses, 70+ listing platforms
python manage.py createsuperuser     # create your Super Admin interactively
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in.

Optional sample data (clearly labelled `[DEMO]`, fictional, never use in production):

```bash
python manage.py seed_demo           # create
python manage.py seed_demo --clear   # remove
```

The application starts and works on an empty business database; demo data is not required.

## 2. Database setup (Turso or PostgreSQL)

Turso is used when `TURSO_DATABASE_URL` is set, otherwise PostgreSQL when `DATABASE_URL` is set. When
neither is set, a local SQLite file is used for development and tests only.

### Turso

```env
TURSO_DATABASE_URL=libsql://your-database-your-org.turso.io   # turso db show <name> --url
TURSO_AUTH_TOKEN=...                                          # turso db tokens create <name>
```

The backend is `config/turso_backend`: Django's SQLite backend on Turso's `libsql` driver. Turso cannot run
the Python functions Django's SQLite backend registers, so date grouping and filtering (`TruncMonth`,
`__date`, `__year`, ...) are written as native SQLite date functions. Time zones use the zone's current
UTC offset, which is exact for fixed-offset zones such as `Asia/Kolkata`. Date arithmetic with durations in a
query (`F("end") - F("start")`) is not supported.

Without a replica every query costs several round trips to Turso. Set `TURSO_REPLICA_DIR` (as `render.yaml`
does) to keep an embedded replica per process and thread: reads are local, writes are forwarded to Turso, and
each request starts by syncing so changes from other processes are visible. Turso rejects
`PRAGMA legacy_alter_table`, so the backend sends it only for local files.

### PostgreSQL

```sql
CREATE DATABASE business_dashboard;
CREATE USER dashboard_user WITH PASSWORD 'choose-a-strong-password';
ALTER DATABASE business_dashboard OWNER TO dashboard_user;
```

```env
DATABASE_URL=postgres://dashboard_user:choose-a-strong-password@localhost:5432/business_dashboard
```

Then run `python manage.py migrate` and `python manage.py seed_initial`.

## 3. Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DJANGO_DEBUG` | `True` for development only | `False` |
| `DJANGO_SECRET_KEY` | Required when `DEBUG=False` | dev-only key when DEBUG |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | e.g. `https://dashboard.example.com` | — |
| `TURSO_DATABASE_URL` | Turso database URL (`libsql://…`); takes precedence over `DATABASE_URL` | — |
| `TURSO_AUTH_TOKEN` | Turso database token | — |
| `DATABASE_URL` | PostgreSQL connection URL | SQLite (dev) |
| `DB_CONN_MAX_AGE` | Persistent DB connections (seconds) | `60` |
| `REDIS_URL` | Optional shared cache (needed for login throttling across multiple workers) | local memory |
| `DJANGO_SECURE_SSL_REDIRECT` | Redirect HTTP→HTTPS in production | `True` |
| `DJANGO_SECURE_HSTS_SECONDS` | HSTS max-age | `31536000` |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Password reset email | console backend |
| `INTEGRATION_ENCRYPTION_KEY` | Fernet key used to encrypt stored integration credentials | derived from `SECRET_KEY` |
| `MAX_UPLOAD_SIZE_MB` | Attachment size limit | `15` |
| `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` | Login throttling | `5`, `15` |
| `CURRENCY_SYMBOL` | Money display | `₹` |
| `DJANGO_TIME_ZONE` | Time zone | `Asia/Kolkata` |

Never commit `.env` (it is in `.gitignore`). Generate keys:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"                               # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # INTEGRATION_ENCRYPTION_KEY
```

Set `INTEGRATION_ENCRYPTION_KEY` before storing any integration credentials. If it is unset, the key is derived
from `SECRET_KEY`, and rotating the secret key would make stored credentials unreadable.

## 4. Administrator accounts and roles

Create the first Super Admin with `python manage.py createsuperuser`. No credentials are hard-coded.

| Role | Where set | Access |
|---|---|---|
| Super Admin | `createsuperuser` | Everything, including Django admin `/admin/` |
| Organization Admin | Admin panel → Users | Every product and module, plus the full admin panel |
| Product Manager | Product membership | *Manage* on all modules of that product; product settings, members and targets |
| Marketing Manager | Product membership | Write: listings, community, SEO, ads, events, email, tasks. Read: the rest |
| Sales / Business Development | Product membership | Write: email, meetings, consultants, investors, events, tasks. Read: the rest |
| Team Member | Product membership | Write on all modules |
| Viewer | Product membership | Read only |

Access levels are none < read < write < manage. *Manage* adds permanent delete. Per-module overrides can be set
per membership (Admin panel → Products → Permissions). Every view, export, report, search result and API
endpoint is filtered server-side through `apps/accounts/permissions.py`. A user who changes a URL or ID only
ever gets a 404.

## 5. Features

- **Organization dashboard** (`/dashboard/`): live KPIs, product and date filters (Today, 7 days, 30 days,
  quarter, month, custom), charts, product-wise comparison, deadlines, team workload and recent activity.
  Content refreshes over HTMX when filters change, after inline status edits, and every 2 minutes.
- **Product dashboards** (`/products/<slug>/`): product KPIs, nine module cards, charts, targets vs actual,
  pending deadlines, upcoming meetings, recent activity, quick-add buttons and report shortcuts.
- **Nine modules plus Tasks.** Every module page has KPI cards, charts, search, filters (product, status,
  assignee, module-specific fields, date range, pending/completed, overdue, archived), sorting, pagination,
  add/edit/view, archive/restore, permanent delete (manage only), bulk actions (status, assign, archive,
  restore, delete), inline HTMX status change, CSV import, CSV/Excel export, attachments, activity history and
  linked follow-up tasks. Calendar views cover Demo Days, Meetings, Investors and Tasks. Investors also have a
  pipeline board, Consultants a directory view, and Listings a platform × product completion report.
- **Admin panel** (`/admin-panel/`): products, module enablement and ordering, members and per-module
  permissions, users and org roles, statuses, custom fields (text, long text, number, currency, date, URL,
  yes/no, single and multi-select), categories, tags, targets, dashboard sections and KPI-card layout, table
  columns and page size, listing platform catalog, investor categories, broadcast notifications, attachments
  and audit log. Configuration is data only; it cannot execute code, SQL or templates.
- **Reports** (`/reports/`): product-wise performance, module activity by product, overdue items and targets
  vs actual. Available as HTML, CSV, Excel and PDF, for this or last month, this or last quarter, 30 days, all
  time or a custom range.
- **REST API** (`/api/v1/`): see section 7.
- **Notifications:** in-app notifications on assignment, membership changes and admin broadcasts, plus
  scheduled reminders via `send_reminders`.

### Module record types

| # | Module | Record types (resource key) |
|---|---|---|
| 1 | Online Listings | Listing (`listings`), plus the platform catalog in the admin panel |
| 2 | Reddit, Quora & Q&A | Post (`community`) |
| 3 | SEO, GEO & AEO | Search query (`seo`) with measurement history |
| 4 | Meta & LinkedIn Ads | Campaign (`advertising`) with computed CTR, CPC and cost per lead |
| 5 | Demo Days | Event (`events`) |
| 6 | Cold Email Marketing | Outreach email (`outreach`), Email campaign (`email_campaigns`), Lead (`leads`) |
| 7 | Customer Meetings | Meeting (`meetings`) |
| 8 | Expert Consultants | Consultant (`consultants`) with interaction history |
| 9 | Investor Meetings | Investor (`investors`) with interaction history and the 10-stage pipeline |
| — | Tasks | Task (`tasks`), optionally linked to any record |

Data-integrity rules:

- **Cold email:** contacts who have unsubscribed are suppressed. New outreach to them is blocked, and
  duplicates within a campaign are rejected.
- **Investors:** categories are prospective only. *Committed* counts only records explicitly set to that stage.
- **Integrations:** a connection never shows *Connected* without a successful live test.
- **Listing platforms:** catalog entries only. No submissions are pre-created.

## 6. Routes

| URL | Purpose |
|---|---|
| `/dashboard/` | Organization dashboard |
| `/products/` · `/products/<slug>/` | Product list and product dashboard |
| `/products/<slug>/records/<resource>/` | Product-scoped module page (also `/new/`, `/export/`, `/import/`) |
| `/records/<resource>/` | Cross-product module page |
| `/records/<resource>/new/`, `/<id>/`, `/<id>/edit/`, `/<id>/delete/` | CRUD |
| `/records/<resource>/<id>/archive/`, `/restore/`, `/status/`, `/attachments/` | State changes and uploads |
| `/records/<resource>/export/?format=csv\|xlsx`, `/import/`, `/import/template/`, `/bulk/` | Data exchange |
| `/records/module/<module>/` | Redirect to a module's main page |
| `/listings/platform-report/` | Platform-wise completion report |
| `/tasks/` | My day: tasks, follow-ups, meetings, demo days, investor follow-ups |
| `/search/?q=` | Global search |
| `/reports/` | Reports |
| `/notifications/` | Notification center |
| `/admin-panel/` | Custom admin panel |
| `/integrations/` | Integration settings (organization admins) |
| `/accounts/login/`, `/logout/`, `/password/change/`, `/password/reset/`, `/profile/` | Authentication |
| `/api/v1/` | REST API |
| `/admin/` | Django admin (maintenance) |

## 7. REST API

Session-authenticated and CSRF-protected, with the same permission scoping as the UI.

```
GET  /api/v1/                                  # resources available to you
GET  /api/v1/products/
GET  /api/v1/dashboard/metrics/?product=<slug>&period=30d
GET  /api/v1/records/<resource>/?q=&status=&product=&period=&ordering=-created_at
POST /api/v1/records/<resource>/
GET|PUT|PATCH|DELETE /api/v1/records/<resource>/<id>/
```

## 8. Commands

| Command | Purpose |
|---|---|
| `python manage.py migrate` | Create or upgrade the schema |
| `python manage.py seed_initial` | Products, module configs, statuses, categories, investor categories, platform catalog (idempotent) |
| `python manage.py seed_demo [--clear]` | Optional labelled demo data |
| `python manage.py send_reminders` | Create in-app reminders for task reminder dates, items due today and overdue items. Schedule it daily (cron or Windows Task Scheduler). It is idempotent per day. |
| `python manage.py createsuperuser` | Create a Super Admin |
| `python manage.py check --deploy` | Production configuration check (run with production env vars) |

## 9. Tests

```bash
pip install -r requirements-dev.txt
pytest                          # pytest-django; uses config.settings_test (SQLite unless DATABASE_URL is set)
TEST_WITH_TURSO_BACKEND=1 pytest  # the same suite on the Turso backend and libsql driver, against a local file
```

Tests never touch a live Turso database: when `TURSO_DATABASE_URL` is set they run the Turso backend on a
temporary local file.

Coverage includes:

- Full CRUD for every resource, form validation, list, board, calendar and card views, search, filtering,
  sorting, pagination and bulk actions.
- Product isolation by URL, forms, exports, search, attachments and the API. Role defaults, module overrides,
  disabled modules and read-only viewers.
- Live KPI aggregation, dashboard updates after adding a record, product and period filters, the dashboard
  layout configuration, and targets vs actual.
- CSV import (valid rows, all-or-nothing invalid rows, unknown columns, export round-trip), formula-injection
  protection, cold-email duplicate and unsubscribe rules, custom fields and statuses.
- Login throttling, CSRF, integration credential encryption and honest integration status, the seed and
  reminder commands, and reports in every format.

Browser end-to-end tests with Playwright are optional: install `pytest-playwright`, then run
`playwright install chromium`.

## 10. Deployment

1. Provision the database and set the environment variables (`DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY`,
   `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` or
   `DATABASE_URL`, `INTEGRATION_ENCRYPTION_KEY`, email settings, and ideally `REDIS_URL`).
2. Install and prepare:
   ```bash
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py seed_initial
   python manage.py check --deploy
   ```
3. Run behind HTTPS (nginx or a platform load balancer):
   ```bash
   gunicorn config.wsgi:application -c gunicorn.conf.py
   ```
4. Schedule `python manage.py send_reminders` daily.
5. **Media files:** attachments are always downloaded through a permission-checked view
   (`/records/attachments/<id>/download/`). Do **not** serve `MEDIA_ROOT` publicly. Back up `MEDIA_ROOT` along
   with the database.

Security settings applied when `DEBUG=False`: secure and HttpOnly session cookies, secure CSRF cookie, HSTS,
SSL redirect, `X-Frame-Options: DENY`, nosniff and a same-origin referrer policy. Uploads are checked for
extension, size and file signature. Exports neutralise spreadsheet formulas. Login attempts are throttled.
Audit logs record important actions.

## 11. Integration status

Manual entry and CSV import/export work without any external service. A service layer is in place in
`apps/integrations/providers.py`, with encrypted credential storage, an admin settings page, and the
statuses Not Configured, Connected, Connection Error and Authorization Expired. The following integrations
need API clients and server-side OAuth flows before they can sync:

- Meta Marketing API: ad accounts, campaign insights, leads
- LinkedIn Marketing API: campaign analytics
- Google Analytics 4 Data API
- Google Search Console API
- An authorized email provider (delivery, reply and unsubscribe webhooks)
- Google Calendar and Microsoft Graph (Outlook) calendars
- S3-compatible file storage (for example `django-storages`)

Each one requires real developer credentials, app review and approval by the provider. Until then, *Test
connection* honestly reports that the client is not implemented.

## 12. Project structure

```
config/                 settings, urls, wsgi/asgi
apps/
  core/                 BaseRecord, registry, generic views/forms, filters, CSV/XLSX, statuses,
                        custom fields, categories, tags, attachments, notifications, targets,
                        dashboard layout, seed commands, template tags
  accounts/             user profile, org roles, permissions service, throttled login
  products/             Product, ProductMembership, module permissions, module configuration
  audit/                AuditLog, request middleware, login signals
  tasks/                Task model, "My day" overview, send_reminders
  analytics/            dashboard aggregation, targets, layout, reports (CSV/XLSX/PDF)
  integrations/         provider service layer, encrypted credentials
  admin_panel/          /admin-panel/ views and forms
  api/                  DRF endpoints generated from the registry
  listings/ community_marketing/ seo_optimization/ advertising/ events/
  outreach/ meetings/ consultants/ investors/       the nine module apps (models + resources.py)
templates/              base layout, components, records, dashboards, admin panel
static/                 css/app.css, js/app.js
tests/                  pytest-django suite
```

To add a module field: add it to the model, run `makemigrations`, and list it in the app's `resources.py`
(`form_fields` / `list_columns`). Forms, tables, exports, imports, the API and the detail page pick it up
automatically.

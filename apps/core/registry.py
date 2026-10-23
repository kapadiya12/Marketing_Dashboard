"""
Module & resource registry.

A *module* is one of the nine business activity areas (plus Tasks). A module
owns one or more *resources* (Django models that subclass ``BaseRecord``).
Each module app declares its resources in ``resources.py``; they are
auto-discovered when Django starts. Generic views, forms, exports, imports,
API endpoints, search and analytics are all driven from these definitions.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

from django.apps import apps


@dataclass
class ChildSpec:
    """An inline child model shown on a record's detail page (e.g. measurements, interactions)."""

    key: str
    model_path: str
    fk_name: str
    fields: list
    label: str
    list_fields: list = field(default_factory=list)

    @property
    def model(self):
        return apps.get_model(self.model_path)


@dataclass
class Resource:
    key: str
    module: str
    model_path: str
    label: str
    label_plural: str
    icon: str
    form_fields: list
    list_columns: list
    search_fields: list
    sort_fields: list = field(default_factory=list)
    filter_fields: list = field(default_factory=list)  # extra choice/FK filters shown on the list page
    default_statuses: list = field(default_factory=list)  # (key, label, state, color)
    date_field: str = "created_at"  # used for date-range filtering & trends
    due_field: Optional[str] = None  # follow-up / deadline field used for overdue detection
    calendar_field: Optional[str] = None
    board: bool = False
    card_view: bool = False
    primary: bool = False
    importable: bool = True
    children: list = field(default_factory=list)
    kpis: Optional[Callable] = None  # fn(queryset, helpers) -> list[dict]
    charts: Optional[Callable] = None  # fn(queryset, helpers) -> list[dict]
    column_labels: dict = field(default_factory=dict)
    import_lookups: dict = field(default_factory=dict)  # fk field -> lookup field for CSV import
    # fk field -> lookup field; typed as free text with suggestions, an unknown value creates the related record
    creatable_fks: dict = field(default_factory=dict)
    clean: Optional[Callable] = None  # extra form validation fn(form, cleaned_data)
    presets: dict = field(default_factory=dict)  # name -> (label, fn(queryset) -> queryset); used by KPI links
    description: str = ""

    @property
    def model(self):
        return apps.get_model(self.model_path)

    @property
    def allowed_columns(self):
        """Every column that may be displayed or exported (validated against admin config)."""
        model = self.model
        names = ["id"] + [f for f in self.form_fields] + ["created_at", "updated_at", "created_by"]
        names += [c for c in self.list_columns if c not in names]
        out = []
        for n in names:
            if n in out:
                continue
            out.append(n)
        return [n for n in out if _has_attr(model, n)]

    def column_label(self, name):
        if name in self.column_labels:
            return self.column_labels[name]
        if name.startswith("cf:"):
            return name[3:].replace("_", " ").title()
        try:
            return self.model._meta.get_field(name).verbose_name.capitalize()
        except Exception:
            return name.replace("_", " ").capitalize()


def _has_attr(model, name):
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return hasattr(model, name)


@dataclass
class Module:
    key: str
    number: int
    label: str
    short_label: str
    icon: str
    description: str
    resources: list = field(default_factory=list)  # resource keys, primary first
    is_activity_module: bool = True

    @property
    def primary_resource(self):
        return registry.get(self.resources[0]) if self.resources else None


class Registry:
    def __init__(self):
        self._modules = {}
        self._resources = {}

    def register_module(self, module: Module):
        self._modules[module.key] = module

    def register(self, resource: Resource):
        self._resources[resource.key] = resource
        module = self._modules.get(resource.module)
        if module and resource.key not in module.resources:
            if resource.primary:
                module.resources.insert(0, resource.key)
            else:
                module.resources.append(resource.key)

    def get(self, key) -> Resource:
        return self._resources.get(key)

    def resources(self):
        return list(self._resources.values())

    def module(self, key) -> Module:
        return self._modules.get(key)

    def modules(self, include_tasks=False):
        mods = sorted(self._modules.values(), key=lambda m: m.number)
        return [m for m in mods if include_tasks or m.is_activity_module]

    def module_keys(self, include_tasks=False):
        return [m.key for m in self.modules(include_tasks)]

    def activity_resources(self):
        return [r for r in self._resources.values() if r.module != "tasks"]

    def resource_for_model(self, model):
        label = f"{model._meta.app_label}.{model.__name__}"
        for r in self._resources.values():
            if r.model_path == label:
                return r
        return None


registry = Registry()

# The nine activity modules plus Tasks. Resources attach themselves in each app's resources.py.
for _m in [
    Module("listings", 1, "Online Listings", "Listings", "bi-globe2",
           "Track submissions to 70+ directories, marketplaces and review platforms."),
    Module("community", 2, "Reddit, Quora & Q&A", "Community", "bi-chat-square-text",
           "Answers, threads and discussions on community and Q&A platforms."),
    Module("seo", 3, "SEO, GEO & AEO", "SEO / GEO / AEO", "bi-graph-up-arrow",
           "Search rankings, generative-engine visibility and AI answer citations."),
    Module("advertising", 4, "Meta & LinkedIn Ads", "Ads", "bi-megaphone",
           "Paid campaigns, budgets, spend, leads and conversions."),
    Module("events", 5, "Demo Days", "Demo Days", "bi-easel2",
           "Demo days, pitch events and exhibitions."),
    Module("outreach", 6, "Cold Email Marketing", "Cold Email", "bi-envelope-paper",
           "Email campaigns, contacts, replies and booked meetings."),
    Module("meetings", 7, "Customer Meetings", "Meetings", "bi-people",
           "Online and offline meetings with customers and prospects."),
    Module("consultants", 8, "Expert Consultants", "Consultants", "bi-person-badge",
           "Directory of advisors and domain experts and their engagement."),
    Module("investors", 9, "Investor Meetings", "Investors", "bi-bank",
           "Prospective investor research, outreach and fundraising pipeline."),
    Module("social", 10, "Digital Marketing Posts", "Digital Marketing", "bi-share",
           "Posts on LinkedIn, Instagram, X (Twitter), Facebook, YouTube and other social platforms."),
    Module("tasks", 11, "Tasks & Follow-ups", "Tasks", "bi-check2-square",
           "Unified tasks, reminders and follow-ups.", is_activity_module=False),
]:
    registry.register_module(_m)



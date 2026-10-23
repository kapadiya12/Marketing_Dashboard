from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.accounts.permissions import accessible_products, is_org_admin, product_ids_for, scoped_queryset
from apps.core import csvio
from apps.core.registry import registry
from apps.core.statuses import get_status, keys_in_state

from .models import ListingPlatform


@login_required
def platform_report(request):
    """Platform × product matrix of listing status, with per-platform completion."""
    resource = registry.get("listings")
    ids = product_ids_for(request.user, "listings", "read")
    if not ids and not is_org_admin(request.user):
        raise PermissionDenied
    products = list(accessible_products(request.user).filter(pk__in=ids, is_active=True))
    kind = request.GET.get("kind", "")
    platforms = ListingPlatform.objects.filter(is_active=True)
    if kind:
        platforms = platforms.filter(kind=kind)
    records = scoped_queryset(request.user, resource, "read").filter(is_archived=False, product__in=products)
    by_key = {(r.platform_id, r.product_id): r for r in records}
    done = set(keys_in_state("listings", "completed"))
    rows = []
    for platform in platforms:
        cells = []
        approved = 0
        for p in products:
            rec = by_key.get((platform.pk, p.pk))
            if rec and rec.status in done:
                approved += 1
            cells.append({"product": p, "record": rec, "status": get_status("listings", rec.status) if rec else None})
        rows.append({"platform": platform, "cells": cells, "approved": approved,
                     "pct": round(approved * 100 / len(products)) if products else 0})
    totals = []
    for i, p in enumerate(products):
        approved = sum(1 for r in rows if r["cells"][i]["record"] and r["cells"][i]["record"].status in done)
        totals.append({"product": p, "approved": approved,
                       "pct": round(approved * 100 / len(rows)) if rows else 0})
    if request.GET.get("format") in ("csv", "xlsx"):
        table = [["Platform", "Type"] + [p.name for p in products] + ["Approved", "Completion %"]]
        for r in rows:
            table.append([r["platform"].name, r["platform"].get_kind_display()]
                         + [c["status"].label if c["status"] else "Not started" for c in r["cells"]]
                         + [r["approved"], r["pct"]])
        if request.GET["format"] == "xlsx":
            return csvio.xlsx_response([("Platform report", table)], "listing-platform-report.xlsx")
        import csv

        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="listing-platform-report.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        for row in table:
            writer.writerow([csvio._safe_cell(v) for v in row])
        return response
    return render(request, "listings/platform_report.html", {
        "rows": rows, "products": products, "totals": totals, "kinds": ListingPlatform.Kind.choices,
        "kind": kind, "resource": resource, "module": registry.module("listings"),
    })

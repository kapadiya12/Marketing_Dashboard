"""
Write the shareable investor pipeline HTML file:

    python manage.py export_investors_html                       # all products -> investor-pipeline.html
    python manage.py export_investors_html --product proceaze --output proceaze-investors.html
    python manage.py export_investors_html --private             # include contact emails and internal notes
"""
from django.core.management.base import BaseCommand, CommandError

from apps.investors.models import Investor
from apps.investors.snapshot import build_snapshot
from apps.products.models import Product


class Command(BaseCommand):
    help = "Export a standalone, shareable HTML page of the investor pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--product", help="Product slug (default: all products)")
        parser.add_argument("--output", default="investor-pipeline.html")
        parser.add_argument("--private", action="store_true", help="Include contact emails and internal notes")
        parser.add_argument("--include-archived", action="store_true")

    def handle(self, *args, **opts):
        qs = Investor.objects.all()
        scope = "All products"
        if not opts["include_archived"]:
            qs = qs.filter(is_archived=False)
        if opts["product"]:
            product = Product.objects.filter(slug=opts["product"]).first()
            if product is None:
                raise CommandError(f"No product with slug '{opts['product']}'.")
            qs = qs.filter(product=product)
            scope = product.name
        html = build_snapshot(qs, scope=scope, include_private=opts["private"])
        with open(opts["output"], "w", encoding="utf-8") as fh:
            fh.write(html)
        self.stdout.write(self.style.SUCCESS(f"Wrote {qs.count()} investors to {opts['output']}"))

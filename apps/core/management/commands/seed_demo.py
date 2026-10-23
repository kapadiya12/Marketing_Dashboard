"""
Optional, clearly labelled demo records for trying the application:

    python manage.py seed_demo          # create demo records (prefixed "[DEMO]" and tagged "demo")
    python manage.py seed_demo --clear  # remove all demo records

Demo records are fictional sample data, not real business activity. Do not use in production.
"""
import datetime
import random
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.models import Tag
from apps.core.registry import registry
from apps.products.models import Product

P = "[DEMO] "


class Command(BaseCommand):
    help = "Create (or --clear) clearly labelled demo records across all modules."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete all records tagged 'demo'.")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--product", help="Only create demo records for this product slug")

    def handle(self, *args, **options):
        tag, _ = Tag.objects.get_or_create(name="demo", defaults={"color": "#F97316"})
        if options["clear"]:
            total = 0
            for res in registry.resources():
                qs = res.model.objects.filter(tags=tag)
                for obj in qs:
                    obj.attachments.all().delete()
                    obj.custom_values.all().delete()
                n = qs.count()
                qs.delete()
                total += n
            self.stdout.write(self.style.SUCCESS(f"Removed {total} demo record(s)."))
            return
        if not Product.objects.exists():
            call_command("seed_initial")
        random.seed(options["seed"])
        with transaction.atomic():
            count = self._create(tag, options.get("product"))
        self.stdout.write(self.style.WARNING(
            f"Created {count} DEMO records (fictional sample data, prefixed '[DEMO]'). "
            "Remove them with: python manage.py seed_demo --clear"))

    def _create(self, tag, product_slug=None):
        from apps.advertising.models import AdCampaign
        from apps.community_marketing.models import CommunityPost
        from apps.consultants.models import Consultant, ConsultantInteraction
        from apps.events.models import DemoEvent
        from apps.investors.models import Investor, InvestorCategory, InvestorInteraction
        from apps.listings.models import ListingPlatform, ListingRecord
        from apps.meetings.models import CustomerMeeting
        from apps.outreach.models import EmailActivity, EmailCampaign
        from apps.seo_optimization.models import SEOMeasurement, SEOTrackingRecord
        from apps.social_media.models import SocialPost
        from apps.tasks.models import Task

        today = timezone.localdate()
        objs = []

        def d(offset):
            return today + datetime.timedelta(days=offset)

        def add(obj):
            obj.save()
            obj.tags.add(tag)
            objs.append(obj)
            return obj

        platforms = list(ListingPlatform.objects.all()[:12])
        categories = list(InvestorCategory.objects.all())
        products = Product.objects.filter(is_active=True)
        if product_slug:
            products = products.filter(slug=product_slug)
        for p in products:
            for plat in random.sample(platforms, k=min(6, len(platforms))):
                if ListingRecord.objects.filter(platform=plat, product=p).exists():
                    continue
                add(ListingRecord(product=p, platform=plat, status=random.choice(
                    ["not_started", "in_progress", "submitted", "approved", "needs_update"]),
                    submission_date=d(-random.randint(5, 90)), next_verification_date=d(random.randint(-10, 30)),
                    notes=P + "Sample listing record"))
            for i in range(3):
                add(CommunityPost(product=p, platform=random.choice(["reddit", "quora", "stack_exchange"]),
                                  community="r/procurement" if i == 0 else "Business software",
                                  topic=f"{P}How do teams evaluate {p.tagline.lower()} tools? #{i + 1}",
                                  status=random.choice(["drafting", "published", "pending_approval"]),
                                  answer_summary=("Start by mapping the current process, pick 2-3 must-have "
                                                  f"features, and run a short pilot. {p.name} teams usually see "
                                                  "results within the first month."),
                                  views=random.randint(50, 2500),
                                  upvotes=random.randint(0, 40), comments_count=random.randint(0, 12),
                                  publication_date=d(-random.randint(1, 60)), follow_up_date=d(random.randint(-5, 20))))
            for i, kw in enumerate([f"{p.name.lower()} software", f"best {p.tagline.split()[0].lower()} tool"]):
                rec = add(SEOTrackingRecord(product=p, keyword=P + kw, optimization_type=["seo", "aeo"][i],
                                            search_platform=["google", "chatgpt"][i], target_ranking=5,
                                            status="in_progress", target_date=d(60)))
                for w in range(3):
                    SEOMeasurement.objects.create(record=rec, measured_on=d(-30 + w * 10),
                                                  ranking=random.randint(8, 40) - w * 3, source="Demo data")
            budget = Decimal(random.randint(20, 120) * 1000)
            add(AdCampaign(product=p, name=f"{P}{p.name} lead gen", channel=random.choice(["meta", "linkedin"]),
                           status="active", start_date=d(-20), end_date=d(10), budget=budget,
                           actual_spend=budget * Decimal("0.6"), impressions=random.randint(20000, 90000),
                           reach=random.randint(10000, 50000), clicks=random.randint(300, 1500),
                           leads=random.randint(10, 60), conversions=random.randint(1, 10)))
            add(DemoEvent(product=p, name=f"{P}Startup demo day — {p.name}", organizer="Demo organizer",
                          event_mode="offline", location="Mumbai", status="registered",
                          registration_deadline=d(7), event_date=d(21), leads_collected=0))
            camp = add(EmailCampaign(product=p, name=f"{P}{p.name} intro sequence", status="active", start_date=d(-14)))
            for i in range(4):
                add(EmailActivity(product=p, campaign=camp, company=f"Example Co {i + 1}",
                                  contact_name=f"Contact {i + 1}", email=f"contact{i + 1}.{p.slug}@example.com",
                                  status=random.choice(["sent", "follow_up", "replied"]), sent_date=d(-random.randint(1, 14)),
                                  delivery_status="delivered", reply_status=random.choice(["no_reply", "positive"]),
                                  follow_up_date=d(random.randint(-3, 7)), meeting_booked=i == 0))
            for act in EmailActivity.objects.filter(campaign=camp).select_related("lead"):
                if act.lead:
                    act.lead.tags.add(tag)
            add(CustomerMeeting(product=p, title=f"{P}Discovery call", customer_company="Example Industries",
                                contact_person="Demo Contact", meeting_type="online", status="scheduled",
                                start_at=timezone.now() + datetime.timedelta(days=random.randint(1, 10)),
                                follow_up_date=d(12), opportunity_value=Decimal(random.randint(1, 9) * 100000)))
            c = add(Consultant(product=p, name=f"{P}Sample Advisor ({p.name})", organization="Example Advisory",
                               expertise=p.tagline, status="in_discussion", follow_up_date=d(5)))
            ConsultantInteraction.objects.create(consultant=c, date=d(-7), interaction_type="call",
                                                 summary="Demo interaction")
            inv = add(Investor(product=p, name=f"{P}Sample Fund for {p.name}",
                               investor_category=random.choice(categories) if categories else None,
                               status=random.choice(["researching", "contacted", "meeting_scheduled"]),
                               follow_up_date=d(random.randint(-2, 14))))
            InvestorInteraction.objects.create(investor=inv, date=d(-3), interaction_type="email",
                                               summary="Demo outreach email")
            for i, (plat, kind) in enumerate([("linkedin", "article"), ("instagram", "image"), ("twitter", "post")]):
                add(SocialPost(product=p, platform=plat, post_type=kind,
                               title=f"{P}{p.name} — {['Customer story', 'Product tip', 'Launch update'][i]}",
                               status=["published", "published", "scheduled"][i], post_date=d(-10 + i * 6),
                               likes=random.randint(10, 300) if i < 2 else 0, comments=random.randint(0, 40) if i < 2 else 0,
                               shares=random.randint(0, 30) if i < 2 else 0,
                               reach=random.randint(500, 9000) if i < 2 else 0))
            for i in range(3):
                add(Task(product=p, title=f"{P}Follow-up task {i + 1}", priority=["low", "medium", "high"][i],
                         status=random.choice(["todo", "in_progress", "done"]), due_date=d(random.randint(-4, 10))))
        return len(objs)

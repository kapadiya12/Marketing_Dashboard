"""
Seed configuration data (idempotent; safe to run repeatedly):

    python manage.py seed_initial

Creates the six products, module configurations for each product, default
statuses, starter categories, prospective investor categories and the listing
platform catalog (70+ platform slots — catalog entries only, no submissions).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Category, StatusOption
from apps.core.registry import registry
from apps.investors.models import InvestorCategory
from apps.listings.models import ListingPlatform
from apps.products.models import Product, ProductModuleConfiguration

PRODUCTS = [
    ("ProcEaze", "proceaze", "Procurement and sourcing platform", "#4F46E5"),
    ("ShiftEaze", "shifteaze", "AI-powered workforce and shift management", "#0EA5E9"),
    ("RicRoot", "ricroot", "Recruitment and talent management", "#16A34A"),
    ("RCSL Procurement", "rcsl", "Riddhi Corporate Service Ltd", "#D97706"),
    ("PayEaze", "payeaze", "Payroll and employee payment management", "#8B5CF6"),
    ("Veracity", "veracity", "Supply chain and business operations", "#0F766E"),
    ("NextEdge", "nextedge", "NextEdge product workspace", "#DB2777"),
]

INVESTOR_CATEGORIES = [
    ("Y Combinator", "Accelerator programme — prospective application target."),
    ("Info Edge", "Prospective strategic / venture investor category."),
    ("Poonawalla Group", "Prospective investor category."),
    ("B2B SaaS investors", "Funds with a stated B2B SaaS focus (to be researched and verified)."),
    ("Angel investors", "Individual angels and angel networks."),
    ("Venture capital firms", "Institutional VC funds."),
    ("Strategic investors", "Corporates investing for strategic fit."),
]

K = ListingPlatform.Kind
PLATFORMS = [
    # Software directories & review sites
    ("G2", "https://www.g2.com", K.REVIEW_SITE),
    ("Capterra", "https://www.capterra.com", K.REVIEW_SITE),
    ("GetApp", "https://www.getapp.com", K.REVIEW_SITE),
    ("Software Advice", "https://www.softwareadvice.com", K.REVIEW_SITE),
    ("TrustRadius", "https://www.trustradius.com", K.REVIEW_SITE),
    ("Gartner Peer Insights", "https://www.gartner.com/peer-insights", K.REVIEW_SITE),
    ("PeerSpot", "https://www.peerspot.com", K.REVIEW_SITE),
    ("Trustpilot", "https://www.trustpilot.com", K.REVIEW_SITE),
    ("SoftwareSuggest", "https://www.softwaresuggest.com", K.SOFTWARE_DIRECTORY),
    ("Techjockey", "https://www.techjockey.com", K.SOFTWARE_DIRECTORY),
    ("SaaSworthy", "https://www.saasworthy.com", K.SOFTWARE_DIRECTORY),
    ("SourceForge", "https://sourceforge.net", K.SOFTWARE_DIRECTORY),
    ("Slashdot", "https://slashdot.org", K.SOFTWARE_DIRECTORY),
    ("AlternativeTo", "https://alternativeto.net", K.SOFTWARE_DIRECTORY),
    ("SaaSHub", "https://www.saashub.com", K.SOFTWARE_DIRECTORY),
    ("Crozdesk", "https://crozdesk.com", K.SOFTWARE_DIRECTORY),
    ("FinancesOnline", "https://financesonline.com", K.SOFTWARE_DIRECTORY),
    ("GoodFirms", "https://www.goodfirms.co", K.SOFTWARE_DIRECTORY),
    ("Clutch", "https://clutch.co", K.SOFTWARE_DIRECTORY),
    ("Futurepedia", "https://www.futurepedia.io", K.SOFTWARE_DIRECTORY),
    ("There's An AI For That", "https://theresanaiforthat.com", K.SOFTWARE_DIRECTORY),
    ("Toolify", "https://www.toolify.ai", K.SOFTWARE_DIRECTORY),
    # Startup directories & launch platforms
    ("Product Hunt", "https://www.producthunt.com", K.STARTUP_DIRECTORY),
    ("BetaList", "https://betalist.com", K.STARTUP_DIRECTORY),
    ("Crunchbase", "https://www.crunchbase.com", K.STARTUP_DIRECTORY),
    ("Wellfound", "https://wellfound.com", K.STARTUP_DIRECTORY),
    ("F6S", "https://www.f6s.com", K.STARTUP_DIRECTORY),
    ("Tracxn", "https://tracxn.com", K.STARTUP_DIRECTORY),
    ("Startup India", "https://www.startupindia.gov.in", K.STARTUP_DIRECTORY),
    ("YourStory", "https://yourstory.com", K.STARTUP_DIRECTORY),
    ("Indie Hackers", "https://www.indiehackers.com", K.STARTUP_DIRECTORY),
    ("Hacker News (Show HN)", "https://news.ycombinator.com", K.STARTUP_DIRECTORY),
    ("Launching Next", "https://www.launchingnext.com", K.STARTUP_DIRECTORY),
    ("Startup Stash", "https://startupstash.com", K.STARTUP_DIRECTORY),
    ("Owler", "https://www.owler.com", K.STARTUP_DIRECTORY),
    ("ZoomInfo", "https://www.zoominfo.com", K.STARTUP_DIRECTORY),
    ("Dun & Bradstreet", "https://www.dnb.com", K.STARTUP_DIRECTORY),
    # Marketplaces
    ("Microsoft AppSource", "https://appsource.microsoft.com", K.MARKETPLACE),
    ("Salesforce AppExchange", "https://appexchange.salesforce.com", K.MARKETPLACE),
    ("Google Workspace Marketplace", "https://workspace.google.com/marketplace", K.MARKETPLACE),
    ("Zoho Marketplace", "https://marketplace.zoho.com", K.MARKETPLACE),
    ("HubSpot App Marketplace", "https://ecosystem.hubspot.com/marketplace/apps", K.MARKETPLACE),
    ("Slack Marketplace", "https://slack.com/apps", K.MARKETPLACE),
    ("Zapier App Directory", "https://zapier.com/apps", K.MARKETPLACE),
    ("AWS Marketplace", "https://aws.amazon.com/marketplace", K.MARKETPLACE),
    ("Atlassian Marketplace", "https://marketplace.atlassian.com", K.MARKETPLACE),
    ("AppSumo", "https://appsumo.com", K.MARKETPLACE),
    ("Government e-Marketplace (GeM)", "https://gem.gov.in", K.MARKETPLACE),
    ("IndiaMART", "https://www.indiamart.com", K.MARKETPLACE),
    ("TradeIndia", "https://www.tradeindia.com", K.MARKETPLACE),
    ("ExportersIndia", "https://www.exportersindia.com", K.MARKETPLACE),
    ("Alibaba", "https://www.alibaba.com", K.MARKETPLACE),
    # Business listings
    ("Google Business Profile", "https://business.google.com", K.BUSINESS_LISTING),
    ("Bing Places", "https://www.bingplaces.com", K.BUSINESS_LISTING),
    ("Apple Business Connect", "https://businessconnect.apple.com", K.BUSINESS_LISTING),
    ("Justdial", "https://www.justdial.com", K.BUSINESS_LISTING),
    ("Sulekha", "https://www.sulekha.com", K.BUSINESS_LISTING),
    ("Yelp", "https://www.yelp.com", K.BUSINESS_LISTING),
    ("Hotfrog", "https://www.hotfrog.com", K.BUSINESS_LISTING),
    ("Foursquare", "https://foursquare.com", K.BUSINESS_LISTING),
    ("Kompass", "https://www.kompass.com", K.BUSINESS_LISTING),
    ("Thomasnet", "https://www.thomasnet.com", K.BUSINESS_LISTING),
    ("Europages", "https://www.europages.co.uk", K.BUSINESS_LISTING),
    # Company & social profiles
    ("LinkedIn Company Page", "https://www.linkedin.com", K.SOCIAL_PROFILE),
    ("Facebook Page", "https://www.facebook.com", K.SOCIAL_PROFILE),
    ("Instagram", "https://www.instagram.com", K.SOCIAL_PROFILE),
    ("X (Twitter)", "https://x.com", K.SOCIAL_PROFILE),
    ("YouTube Channel", "https://www.youtube.com", K.SOCIAL_PROFILE),
    ("Medium", "https://medium.com", K.SOCIAL_PROFILE),
    ("GitHub Organization", "https://github.com", K.SOCIAL_PROFILE),
    ("Glassdoor", "https://www.glassdoor.com", K.SOCIAL_PROFILE),
    ("AmbitionBox", "https://www.ambitionbox.com", K.SOCIAL_PROFILE),
    ("Indeed Company Page", "https://www.indeed.com", K.SOCIAL_PROFILE),
    ("Naukri Employer Profile", "https://www.naukri.com", K.SOCIAL_PROFILE),
]

CATEGORIES = [
    ("", "High priority", "#DC2626"),
    ("", "Brand awareness", "#6366F1"),
    ("", "Lead generation", "#16A34A"),
    ("", "Partnerships", "#0EA5E9"),
    ("investors", "Warm introduction", "#8B5CF6"),
    ("meetings", "Product demo", "#0EA5E9"),
    ("meetings", "Requirement discovery", "#D97706"),
    ("events", "Pitch competition", "#F97316"),
    ("events", "Exhibition / expo", "#14B8A6"),
]


class Command(BaseCommand):
    help = "Seed products, module configurations, statuses, categories, investor categories and listing platforms."

    @transaction.atomic
    def handle(self, *args, **options):
        created = {"products": 0, "modules": 0, "statuses": 0, "categories": 0, "investor_categories": 0,
                   "platforms": 0}
        for order, (name, slug, description, color) in enumerate(PRODUCTS):
            product, was_created = Product.objects.get_or_create(
                slug=slug, defaults={"name": name, "tagline": description, "description": description,
                                     "brand_color": color, "display_order": order})
            created["products"] += was_created
            for i, module in enumerate(registry.modules()):
                _, c = ProductModuleConfiguration.objects.get_or_create(
                    product=product, module=module.key, defaults={"is_enabled": True, "display_order": i})
                created["modules"] += c

        for res in registry.resources():
            for i, (key, label, state, color) in enumerate(res.default_statuses):
                _, c = StatusOption.objects.get_or_create(
                    resource=res.key, key=key, defaults={"label": label, "state": state, "color": color, "order": i})
                created["statuses"] += c

        for resource, name, color in CATEGORIES:
            _, c = Category.objects.get_or_create(resource=resource, name=name, product=None,
                                                  defaults={"color": color})
            created["categories"] += c

        for i, (name, description) in enumerate(INVESTOR_CATEGORIES):
            _, c = InvestorCategory.objects.get_or_create(name=name, defaults={"description": description,
                                                                              "display_order": i})
            created["investor_categories"] += c

        for i, (name, url, kind) in enumerate(PLATFORMS):
            _, c = ListingPlatform.objects.get_or_create(name=name, defaults={"website_url": url, "kind": kind,
                                                                             "display_order": i})
            created["platforms"] += c

        summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in created.items())
        self.stdout.write(self.style.SUCCESS(f"Seed complete. Created: {summary}. "
                                             f"Platform catalog size: {ListingPlatform.objects.count()}."))

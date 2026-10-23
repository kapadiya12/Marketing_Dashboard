import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.listings.models import ListingPlatform
from apps.products.models import Product, ProductMembership

User = get_user_model()
PASSWORD = "Test-Passw0rd!x"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def products(db):
    a = Product.objects.create(name="ProcEaze", slug="proceaze", description="Procurement", brand_color="#4F46E5")
    b = Product.objects.create(name="ShiftEaze", slug="shifteaze", description="Workforce", brand_color="#0EA5E9")
    return a, b


@pytest.fixture
def platform(db):
    return ListingPlatform.objects.create(name="G2", website_url="https://www.g2.com")


def make_user(username, product=None, role=None, **extra):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password=PASSWORD, **extra)
    if product is not None:
        ProductMembership.objects.create(user=user, product=product, role=role or "team_member")
    return user


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser("admin", "admin@example.com", PASSWORD)


@pytest.fixture
def users(products):
    a, b = products
    return {
        "pm_a": make_user("pm_a", a, "product_manager"),
        "member_a": make_user("member_a", a, "team_member"),
        "viewer_a": make_user("viewer_a", a, "viewer"),
        "marketing_a": make_user("marketing_a", a, "marketing_manager"),
        "member_b": make_user("member_b", b, "team_member"),
        "nobody": make_user("nobody"),
    }


@pytest.fixture
def login(client):
    def _login(user):
        client.force_login(user)
        return client
    return _login

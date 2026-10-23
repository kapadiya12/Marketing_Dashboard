"""
Integration service layer.

Each provider describes the credentials it needs and implements
``test_connection`` / ``sync``. No external API client is implemented yet, so
``test_connection`` never reports "Connected": it reports *Not Configured* when
credentials are missing, and a *Connection Error* explaining that the API client
is pending otherwise. Manual entry and CSV import work without any integration.

To implement a provider: subclass ``BaseProvider``, implement ``authorization_url``
/ ``exchange_code`` for the server-side OAuth flow, ``test_connection`` with a real
API call, and ``sync`` to upsert records (e.g. AdCampaign by external_campaign_id).
"""
from dataclasses import dataclass, field

from django.utils import timezone


@dataclass
class ConnectionResult:
    status: str
    message: str


@dataclass
class BaseProvider:
    key: str
    label: str
    description: str
    credential_fields: list = field(default_factory=list)  # (name, label, secret: bool)
    feeds: str = ""
    oauth: bool = True
    implemented: bool = False

    def missing_credentials(self, config):
        secrets = config.secrets
        settings = config.settings or {}
        return [label for name, label, secret in self.credential_fields
                if not (secrets.get(name) if secret else settings.get(name))]

    def test_connection(self, config):
        missing = self.missing_credentials(config)
        if missing:
            return ConnectionResult("not_configured", f"Missing: {', '.join(missing)}.")
        if config.token_expires_at and config.token_expires_at < timezone.now():
            return ConnectionResult("expired", "The stored authorization has expired. Re-authorize the connection.")
        if not self.implemented:
            return ConnectionResult(
                "error",
                f"Credentials are stored, but the {self.label} API client has not been implemented yet, so the "
                "connection could not be verified. Continue using manual entry and CSV import.",
            )
        return ConnectionResult("error", "Not verified.")

    def sync(self, config):
        raise NotImplementedError(f"{self.label} sync is not implemented yet.")


PROVIDERS = {p.key: p for p in [
    BaseProvider("meta_ads", "Meta Ads", "Import campaign spend, reach, clicks and leads from Meta Marketing API.",
                 [("ad_account_id", "Ad account ID", False), ("app_id", "App ID", False),
                  ("app_secret", "App secret", True), ("access_token", "Access token", True)],
                 feeds="Meta & LinkedIn Ads module"),
    BaseProvider("linkedin_ads", "LinkedIn Ads", "Import LinkedIn Campaign Manager performance data.",
                 [("ad_account_id", "Ad account ID", False), ("client_id", "Client ID", False),
                  ("client_secret", "Client secret", True), ("access_token", "Access token", True)],
                 feeds="Meta & LinkedIn Ads module"),
    BaseProvider("google_analytics", "Google Analytics", "Landing-page traffic and conversions (GA4 Data API).",
                 [("property_id", "GA4 property ID", False), ("client_id", "OAuth client ID", False),
                  ("client_secret", "OAuth client secret", True), ("refresh_token", "Refresh token", True)],
                 feeds="SEO module & ads landing pages"),
    BaseProvider("search_console", "Google Search Console", "Search queries, positions and clicks.",
                 [("site_url", "Site URL", False), ("client_id", "OAuth client ID", False),
                  ("client_secret", "OAuth client secret", True), ("refresh_token", "Refresh token", True)],
                 feeds="SEO, GEO & AEO module"),
    BaseProvider("email_provider", "Email provider", "Delivery, reply and unsubscribe events from an authorized "
                 "email platform.",
                 [("provider_name", "Provider name", False), ("api_key", "API key", True)],
                 feeds="Cold Email module", oauth=False),
    BaseProvider("google_calendar", "Google Calendar", "Sync customer and investor meetings.",
                 [("calendar_id", "Calendar ID", False), ("client_id", "OAuth client ID", False),
                  ("client_secret", "OAuth client secret", True), ("refresh_token", "Refresh token", True)],
                 feeds="Meetings & Investors modules"),
    BaseProvider("outlook_calendar", "Microsoft Outlook Calendar", "Sync meetings via Microsoft Graph.",
                 [("tenant_id", "Tenant ID", False), ("client_id", "Client ID", False),
                  ("client_secret", "Client secret", True), ("refresh_token", "Refresh token", True)],
                 feeds="Meetings & Investors modules"),
    BaseProvider("file_storage", "File storage", "Store attachments in S3-compatible object storage.",
                 [("bucket", "Bucket", False), ("endpoint_url", "Endpoint URL", False),
                  ("access_key", "Access key", True), ("secret_key", "Secret key", True)],
                 feeds="Attachments", oauth=False),
]}


def get_provider(key):
    return PROVIDERS.get(key)

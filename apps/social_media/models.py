from django.db import models

from apps.core.models import BaseRecord


class SocialPost(BaseRecord):
    """A digital-marketing post on a social platform (LinkedIn, Instagram, X/Twitter, …)."""

    RESOURCE_KEY = "social"

    class Platform(models.TextChoices):
        LINKEDIN = "linkedin", "LinkedIn"
        INSTAGRAM = "instagram", "Instagram"
        TWITTER = "twitter", "X (Twitter)"
        FACEBOOK = "facebook", "Facebook"
        YOUTUBE = "youtube", "YouTube"
        THREADS = "threads", "Threads"
        PINTEREST = "pinterest", "Pinterest"
        WHATSAPP = "whatsapp", "WhatsApp Channel"
        OTHER = "other", "Other"

    class PostType(models.TextChoices):
        POST = "post", "Post"
        IMAGE = "image", "Image / carousel"
        VIDEO = "video", "Video / reel"
        ARTICLE = "article", "Article / blog"
        STORY = "story", "Story"
        EVENT = "event", "Event / live"

    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.LINKEDIN)
    post_type = models.CharField("Type", max_length=10, choices=PostType.choices, default=PostType.POST)
    title = models.CharField("Post title / caption", max_length=255)
    post_url = models.URLField("Post link", blank=True)
    post_date = models.DateField("Post date", null=True, blank=True)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    reach = models.PositiveIntegerField("Reach / views", default=0)

    class Meta(BaseRecord.Meta):
        verbose_name = "social post"

    def __str__(self):
        return self.title[:120]

    @property
    def engagement(self):
        return self.likes + self.comments + self.shares

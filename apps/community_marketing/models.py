from django.db import models

from apps.core.models import BaseRecord


class CommunityPost(BaseRecord):
    RESOURCE_KEY = "community"

    class Platform(models.TextChoices):
        REDDIT = "reddit", "Reddit"
        QUORA = "quora", "Quora"
        STACK_OVERFLOW = "stack_overflow", "Stack Overflow"
        STACK_EXCHANGE = "stack_exchange", "Stack Exchange"
        HACKER_NEWS = "hacker_news", "Hacker News"
        INDIE_HACKERS = "indie_hackers", "Indie Hackers"
        LINKEDIN = "linkedin", "LinkedIn groups"
        OTHER = "other", "Other forum / Q&A"

    class Approval(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        CHANGES = "changes", "Changes requested"

    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.REDDIT)
    community = models.CharField("Community / subreddit", max_length=150, blank=True)
    topic = models.CharField("Question", max_length=300)
    answer_summary = models.TextField("Answer", blank=True)
    published_url = models.URLField("Published URL", blank=True)
    publication_date = models.DateField(null=True, blank=True)
    upvotes = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField("Comments", default=0)
    views = models.PositiveIntegerField("Views", default=0)
    content_approval = models.CharField(max_length=20, choices=Approval.choices, default=Approval.PENDING)
    follow_up_date = models.DateField(null=True, blank=True)

    class Meta(BaseRecord.Meta):
        verbose_name = "community post"

    def __str__(self):
        return self.topic[:120]

    @property
    def engagement(self):
        return self.upvotes + self.comments_count

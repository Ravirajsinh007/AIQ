import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.accounts.models import Institute, User
from apps.exams.models import ExamSchedule


class EmailDeliveryStatus(models.TextChoices):
    NOT_CONFIGURED = 'not_configured', 'Not Configured'
    SENT = 'sent', 'Sent'
    FAILED = 'failed', 'Failed'


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(
        Institute, on_delete=models.CASCADE, related_name='notifications'
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    sender = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sent_notifications',
    )
    exam = models.ForeignKey(
        ExamSchedule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications',
    )
    subject = models.CharField(max_length=200)
    message = models.TextField(max_length=10000)
    event_key = models.CharField(max_length=200, null=True, blank=True)
    email_status = models.CharField(
        max_length=20, choices=EmailDeliveryStatus.choices,
        default=EmailDeliveryStatus.NOT_CONFIGURED,
    )
    email_error = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'notifications_notification'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['recipient', 'event_key'],
                name='unique_notification_recipient_event',
                condition=models.Q(event_key__isnull=False),
            ),
        ]
        indexes = [models.Index(fields=['recipient', 'read_at', 'created_at'])]

    def clean(self):
        if self.exam_id and self.exam.institute_id != self.institute_id:
            raise ValidationError({'exam': 'Exam must belong to the notification institute.'})
        if self.sender_id and not self.sender.memberships.filter(
            institute_id=self.institute_id, status='active'
        ).exists() and not self.sender.is_platform_admin:
            raise ValidationError({'sender': 'Sender must be authorized for this institute.'})
        if self.recipient_id and not self.recipient.memberships.filter(
            institute_id=self.institute_id, status='active'
        ).exists():
            raise ValidationError({'recipient': 'Recipient must be an active institute member.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

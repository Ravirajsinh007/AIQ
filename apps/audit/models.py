import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.accounts.models import Institute, User


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    outcome = models.CharField(max_length=20, default='success', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_event'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['institute', '-created_at']),
            models.Index(fields=['resource_type', 'resource_id']),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Audit events are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Audit events cannot be deleted.')

    def __str__(self):
        return f'{self.action} {self.resource_type}:{self.resource_id} ({self.outcome})'

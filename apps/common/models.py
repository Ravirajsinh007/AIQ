import uuid
from django.db import models

class UUIDTimestampedModel(models.Model):
    """
    Abstract base model providing:
    - UUID primary key for secure, non-sequential entity identification
    - created_at and updated_at UTC timestamps
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

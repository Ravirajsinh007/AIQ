from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source='actor.email', read_only=True, allow_null=True)
    institute_code = serializers.CharField(source='institute.code', read_only=True, allow_null=True)

    class Meta:
        model = AuditEvent
        fields = [
            'id', 'institute', 'institute_code', 'actor', 'actor_email',
            'action', 'resource_type', 'resource_id', 'outcome', 'metadata',
            'created_at',
        ]
        read_only_fields = fields

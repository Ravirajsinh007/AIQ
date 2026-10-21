from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import EnforcePasswordChange

from .models import AuditEvent
from .permissions import CanReadAuditEvents
from .serializers import AuditEventSerializer


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanReadAuditEvents]
    serializer_class = AuditEventSerializer
    filterset_fields = ['action', 'resource_type', 'outcome']
    ordering_fields = ['created_at', 'action']

    def get_queryset(self):
        user = self.request.user
        events = AuditEvent.objects.select_related('actor', 'institute')
        if getattr(self, 'swagger_fake_view', False) or not user or not user.is_authenticated:
            return events.none()
        if user.is_platform_admin:
            return events
        institute_ids = user.memberships.filter(
            role__in=['institute_admin', 'exam_staff'],
            status='active',
        ).values_list('institute_id', flat=True)
        return events.filter(institute_id__in=institute_ids)

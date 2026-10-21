from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import EnforcePasswordChange

from .models import Notification
from .serializers import (
    NotificationCreateSerializer,
    NotificationSerializer,
)
from .services import create_notification


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, EnforcePasswordChange]
    serializer_class = NotificationSerializer
    queryset = Notification.objects.none()

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Notification.objects.none()
        return Notification.objects.filter(
            recipient=self.request.user
        ).select_related('institute', 'exam')

    def create(self, request, *args, **kwargs):
        serializer = NotificationCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        notification, created = create_notification(
            institute=data['institute'],
            recipient=data['recipient'],
            sender=request.user,
            exam=data.get('exam'),
            subject=data['subject'],
            message=data['message'],
            event_key=data.get('event_key'),
        )
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(
            NotificationSerializer(notification).data, status=response_status
        )

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])
        return Response(NotificationSerializer(notification).data)

    @action(detail=True, methods=['post'], url_path='unread')
    def mark_unread(self, request, pk=None):
        notification = self.get_object()
        if notification.read_at is not None:
            notification.read_at = None
            notification.save(update_fields=['read_at'])
        return Response(NotificationSerializer(notification).data)

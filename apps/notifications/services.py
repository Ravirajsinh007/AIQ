import smtplib
import socket

from django.conf import settings
from django.core.mail import send_mail
from rest_framework.exceptions import ValidationError

from apps.audit.services import record_audit_event

from .models import EmailDeliveryStatus, Notification


def deliver_notification_email(notification):
    if not (
        getattr(settings, 'EMAIL_HOST', '')
        and getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    ):
        notification.email_status = EmailDeliveryStatus.NOT_CONFIGURED
        notification.email_error = 'SMTP EMAIL_HOST and DEFAULT_FROM_EMAIL are required.'
    else:
        try:
            sent_count = send_mail(
                subject=notification.subject,
                message=notification.message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notification.recipient.email],
                fail_silently=False,
            )
        except (smtplib.SMTPException, socket.error, OSError) as exc:
            notification.email_status = EmailDeliveryStatus.FAILED
            notification.email_error = f'Email delivery failed ({type(exc).__name__}).'
        else:
            if sent_count == 1:
                notification.email_status = EmailDeliveryStatus.SENT
                notification.email_error = ''
            else:
                notification.email_status = EmailDeliveryStatus.FAILED
                notification.email_error = 'Email backend did not confirm delivery.'
    notification.save(update_fields=['email_status', 'email_error'])
    return notification


def create_notification(*, institute, recipient, sender, exam, subject, message, event_key=None):
    defaults = {
        'institute': institute,
        'sender': sender,
        'exam': exam,
        'subject': subject,
        'message': message,
    }
    if event_key:
        notification, created = Notification.objects.get_or_create(
            recipient=recipient, event_key=event_key, defaults=defaults
        )
    else:
        notification = Notification.objects.create(
            recipient=recipient, event_key=None, **defaults
        )
        created = True
    if not created:
        if notification.institute_id != institute.pk:
            raise ValidationError({
                'event_key': 'This idempotency key is already used for another institute recipient context.'
            })
        return notification, False
    deliver_notification_email(notification)
    record_audit_event(
        action='notification.created',
        resource_type='notification',
        resource_id=notification.pk,
        actor=sender,
        institute=institute,
        metadata={'outcome': notification.email_status},
    )
    return notification, True

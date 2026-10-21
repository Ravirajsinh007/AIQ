from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    recipient_email = serializers.EmailField(source='recipient.email', read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'institute', 'recipient_email', 'exam', 'subject', 'message',
            'email_status', 'email_error', 'created_at', 'read_at',
        ]
        read_only_fields = fields


class NotificationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['institute', 'recipient', 'exam', 'subject', 'message', 'event_key']
        validators = []
        extra_kwargs = {
            'event_key': {'required': False, 'allow_null': True, 'allow_blank': False},
            'exam': {'required': False, 'allow_null': True},
        }

    def validate(self, attrs):
        user = self.context['request'].user
        institute = attrs['institute']
        if not is_notification_manager(user, institute.pk):
            raise serializers.ValidationError({
                'institute': 'Notification management permission is required for this institute.'
            })
        recipient = attrs['recipient']
        if not recipient.memberships.filter(
            institute=institute, status='active'
        ).exists():
            raise serializers.ValidationError({
                'recipient': 'Recipient must be an active member of this institute.'
            })
        exam = attrs.get('exam')
        if exam:
            if exam.institute_id != institute.pk:
                raise serializers.ValidationError({'exam': 'Exam must belong to this institute.'})
            from apps.exams.services import eligible_placements

            if not eligible_placements(exam, recipient).exists():
                raise serializers.ValidationError({
                    'recipient': 'Recipient is not eligible for this exam cohort.'
                })
        return attrs


def is_notification_manager(user, institute_id):
    if user.is_platform_admin:
        return True
    from apps.accounts.models import MembershipStatus, RoleChoices

    memberships = user.memberships.filter(
        institute_id=institute_id,
        status=MembershipStatus.ACTIVE,
        role__in=(RoleChoices.INSTITUTE_ADMIN, RoleChoices.EXAM_STAFF),
    )
    return any(
        membership.role == RoleChoices.INSTITUTE_ADMIN
        or {'controller', 'exam_admin', 'exam_manager'} & set(membership.exam_permissions or [])
        for membership in memberships
    )

from datetime import datetime, timezone as datetime_timezone

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Institute, User, UserInstituteMembership, RoleChoices, MembershipStatus


class PlatformDashboardApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='platform@example.test',
            password='Secure-Platform-Password-92!A',
        )
        self.url = reverse('platform-dashboard-overview')

    @staticmethod
    def month_start(month_offset):
        today = timezone.localdate()
        year, month = today.year, today.month
        for _ in range(abs(month_offset)):
            if month_offset < 0:
                if month == 1:
                    year, month = year - 1, 12
                else:
                    month -= 1
            elif month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        return datetime(year, month, 1, 12, tzinfo=datetime_timezone.utc)

    def test_platform_admin_gets_correct_totals_and_real_cumulative_growth(self):
        self.client.force_authenticate(user=self.admin)
        earlier_institute = Institute.objects.create(code='EARLIER', name='Earlier Institute')
        current_institute = Institute.objects.create(code='CURRENT', name='Current Institute')
        Institute.objects.filter(pk=earlier_institute.pk).update(created_at=self.month_start(-2))
        Institute.objects.filter(pk=current_institute.pk).update(
            created_at=self.month_start(0),
            status='inactive',
        )
        active_user = User.objects.create_user(
            email='active@example.test',
            password='Secure-User-Password-92!B',
        )
        inactive_user = User.objects.create_user(
            email='inactive@example.test',
            password='Secure-User-Password-92!C',
            is_active=False,
        )
        User.objects.filter(pk=self.admin.pk).update(created_at=self.month_start(-1))
        User.objects.filter(pk=active_user.pk).update(created_at=self.month_start(0))
        User.objects.filter(pk=inactive_user.pk).update(created_at=self.month_start(-2))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_institutes'], 2)
        self.assertEqual(response.data['active_institutes'], 1)
        self.assertEqual(response.data['total_users'], 3)
        self.assertEqual(response.data['active_users'], 2)
        self.assertEqual(
            response.data['growth'],
            [
                {'month': self.month_start(-2).strftime('%Y-%m'), 'institutes': 1, 'users': 1},
                {'month': self.month_start(-1).strftime('%Y-%m'), 'institutes': 1, 'users': 2},
                {'month': self.month_start(0).strftime('%Y-%m'), 'institutes': 2, 'users': 3},
            ],
        )

    def test_non_platform_admin_cannot_read_platform_aggregates(self):
        institute = Institute.objects.create(code='LOCAL', name='Local Institute')
        user = User.objects.create_user(
            email='institute-admin@example.test',
            password='Secure-User-Password-92!D',
        )
        UserInstituteMembership.objects.create(
            user=user,
            institute=institute,
            role=RoleChoices.INSTITUTE_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_platform_aggregates(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_required_password_change_blocks_platform_management_actions(self):
        self.admin.must_change_password = True
        self.admin.save(update_fields=['must_change_password'])
        self.client.force_authenticate(user=self.admin)

        overview = self.client.get(self.url)
        create = self.client.post(reverse('institute-list-create'), {
            'code': 'BLOCKED',
            'name': 'Blocked Institute',
        })

        self.assertEqual(overview.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Institute.objects.filter(code='BLOCKED').exists())

    def test_platform_admin_institute_list_supports_search_and_status(self):
        self.client.force_authenticate(user=self.admin)
        Institute.objects.create(code='NORTH', name='North Campus', status='active')
        Institute.objects.create(code='SOUTH', name='South Campus', status='inactive')

        response = self.client.get(reverse('institute-list-create'), {'search': 'north', 'status': 'active'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['code'], 'NORTH')

    def test_platform_admin_can_order_institutes_by_recent_creation(self):
        self.client.force_authenticate(user=self.admin)
        earlier = Institute.objects.create(code='EARLY', name='Earlier')
        latest = Institute.objects.create(code='LATEST', name='Latest')
        Institute.objects.filter(pk=earlier.pk).update(created_at=self.month_start(-1))
        Institute.objects.filter(pk=latest.pk).update(created_at=self.month_start(0))

        response = self.client.get(reverse('institute-list-create'), {'ordering': '-created_at'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'][0]['code'], 'LATEST')

    def test_duplicate_institute_code_returns_field_validation_error(self):
        self.client.force_authenticate(user=self.admin)
        Institute.objects.create(code='UNIQUE', name='Existing Institute')

        response = self.client.post(reverse('institute-list-create'), {
            'code': ' unique ',
            'name': 'Duplicate Institute',
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data['error']['details'])
        self.assertEqual(Institute.objects.count(), 1)

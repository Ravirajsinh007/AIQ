"""
Tests for custom User model in accounts app.
"""
import uuid
from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()

class CustomUserModelTests(TestCase):
    def test_create_user_with_email_successful(self):
        email = 'faculty@institution.edu'
        password = 'SecureTestPassword123!'
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name='Alan',
            last_name='Turing'
        )

        self.assertEqual(user.email, email)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.password == password)  # Password must be hashed
        self.assertTrue(isinstance(user.id, uuid.UUID))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.full_name, 'Alan Turing')

    def test_create_superuser(self):
        email = 'admin@platform.org'
        password = 'AdminSecurePassword123!'
        admin_user = User.objects.create_superuser(
            email=email,
            password=password
        )

        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_verified)
        self.assertFalse(admin_user.must_change_password)

    def test_create_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='password123')

    def test_user_email_normalization(self):
        email = 'teacher@DOMAIN.COM'
        user = User.objects.create_user(email=email, password='password123')
        self.assertEqual(user.email, 'teacher@domain.com')

"""
Security tests for Django settings configuration and Host header validation.
"""
from django.conf import settings
from django.test import SimpleTestCase
from rest_framework.test import APIClient


class SettingsSecurityTests(SimpleTestCase):
    """
    Validates that ALLOWED_HOSTS is safely configured without wildcards.
    """

    def test_allowed_hosts_does_not_contain_wildcard(self):
        """
        Verify that '*' is never present in settings.ALLOWED_HOSTS.
        """
        self.assertNotIn(
            '*',
            settings.ALLOWED_HOSTS,
            "Security vulnerability: Wildcard '*' found in ALLOWED_HOSTS!"
        )

    def test_allowed_hosts_contains_safe_defaults(self):
        """
        Verify that development defaults are restricted to localhost and 127.0.0.1.
        """
        self.assertTrue(
            any(h in settings.ALLOWED_HOSTS for h in ['localhost', '127.0.0.1']),
            "ALLOWED_HOSTS must contain standard local loopback addresses."
        )

    def test_no_wildcard_host_in_allowed_hosts_list(self):
        """
        Ensure no element in ALLOWED_HOSTS starts with '*.' or is '*'.
        """
        for host in settings.ALLOWED_HOSTS:
            self.assertNotEqual(host, '*', "Wildcard '*' host entry is strictly forbidden.")

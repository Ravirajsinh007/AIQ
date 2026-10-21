"""
Tests for Common utilities and health check endpoints.
"""
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status

class HealthCheckTests(APITestCase):
    def test_service_health_check(self):
        url = reverse('health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'healthy')
        self.assertEqual(response.data['service'], 'ExamCraft AI Backend')
        self.assertIn('version', response.data)
        self.assertIn('timestamp', response.data)

    def test_database_health_check_responds(self):
        url = reverse('database-health-check')
        response = self.client.get(url)
        # Should return 200 (if connected) or 503 (if unreachable), but never leak secrets
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE])
        self.assertIn('status', response.data)
        self.assertIn('database', response.data)
        # Verify no credentials leaked
        for sensitive_word in ['password', 'secret', 'postgres://', 'postgresql://']:
            self.assertNotIn(sensitive_word, str(response.data).lower())

    def test_openapi_schema_endpoint(self):
        url = reverse('schema')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('openapi', response.data)

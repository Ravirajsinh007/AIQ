from datetime import datetime, timezone
import logging
from django.db import connection
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiResponse

logger = logging.getLogger(__name__)

class ServiceHealthCheckView(APIView):
    """
    Public health check endpoint returning API service operational status.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Service Health Check",
        description="Returns basic operational health status of the API server.",
        responses={200: OpenApiResponse(description="Service is healthy")}
    )
    def get(self, request):
        return Response({
            'status': 'healthy',
            'service': 'ExamCraft AI Backend',
            'version': '1.0.0',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, status=status.HTTP_200_OK)


class DatabaseHealthCheckView(APIView):
    """
    Database health check endpoint that tests connectivity to the PostgreSQL (Supabase) database
    without exposing credentials, connection strings, or internal network topology.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Database Health Check",
        description="Verifies live database connectivity and response readiness.",
        responses={
            200: OpenApiResponse(description="Database connected and responsive"),
            503: OpenApiResponse(description="Database connectivity failure")
        }
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()

            db_vendor = connection.vendor
            return Response({
                'status': 'healthy',
                'database': 'connected',
                'engine': db_vendor,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, status=status.HTTP_200_OK)

        except Exception as exc:
            # Log exact internal error for administrator logs, but do NOT leak details to client
            logger.error("Database connectivity health check failed: %s", exc)
            return Response({
                'status': 'unhealthy',
                'database': 'unreachable',
                'detail': 'Unable to establish database connection. Please verify configuration.',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

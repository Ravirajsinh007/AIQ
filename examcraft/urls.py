from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    # Admin Interface
    path('admin/', admin.site.urls),

    # Common & Health Check Endpoints (/api/v1/health/, /api/v1/health/database/)
    path('api/v1/', include('apps.common.urls')),

    # M1 User & Access Management Endpoints
    path('api/v1/', include('apps.accounts.urls')),

    # M2 Academic Structure & Syllabus Management Endpoints
    path('api/v1/', include('apps.academics.urls')),

    # M3 Question Bank Management Endpoints
    path('api/v1/', include('apps.questions.urls')),

    # M4 AI Question Generation Engine Endpoints
    path('api/v1/', include('apps.ai_generation.urls')),

    # M5 Question Verification & Review Endpoints
    path('api/v1/', include('apps.reviews.urls')),

    # M6 Blueprint Paper Generation Endpoints
    path('api/v1/', include('apps.blueprints.urls')),

    # M9 Online Exam Delivery & M10 Integrity Monitoring
    path('api/v1/', include('apps.exams.urls')),

    # M8 Audit & Traceability
    path('api/v1/', include('apps.audit.urls')),
    # M18 In-app notifications and configured SMTP delivery.
    path('api/v1/', include('apps.notifications.urls')),

    # OpenAPI 3 Schema & Interactive Documentation
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/v1/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

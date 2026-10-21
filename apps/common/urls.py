from django.urls import path
from .views import ServiceHealthCheckView, DatabaseHealthCheckView

urlpatterns = [
    path('health/', ServiceHealthCheckView.as_view(), name='health-check'),
    path('health/database/', DatabaseHealthCheckView.as_view(), name='database-health-check'),
]

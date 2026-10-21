"""
Django settings for ExamCraft AI Backend.

Configured for multi-tenant examination platform with Supabase PostgreSQL,
Django REST Framework, Simple JWT, drf-spectacular, and Google Gemini integration.
"""
from datetime import timedelta
import os
from pathlib import Path
import sys
from dotenv import load_dotenv
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Add apps folder to Python module lookup
sys.path.insert(0, str(BASE_DIR / 'apps'))

# Load environment variables from .env file if available
load_dotenv(BASE_DIR / '.env')

# Security settings
DEBUG = os.getenv('DJANGO_DEBUG', 'False').lower() in ('true', '1', 'yes')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be configured when DEBUG is disabled.')
    SECRET_KEY = 'insecure-local-development-key-change-before-deployment'

ALLOWED_HOSTS_STR = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_STR.split(',') if h.strip()]

# Application definition
INSTALLED_APPS = [
    # Django Core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-Party Packages
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',

    # Local Domain Applications (M1 - M6 & Common)
    'apps.common.apps.CommonConfig',
    'apps.accounts.apps.AccountsConfig',
    'apps.academics.apps.AcademicsConfig',
    'apps.questions.apps.QuestionsConfig',
    'apps.ai_generation.apps.AiGenerationConfig',
    'apps.reviews.apps.ReviewsConfig',
    'apps.blueprints.apps.BlueprintsConfig',
    'apps.exams.apps.ExamsConfig',
    'apps.audit.apps.AuditConfig',
    'apps.notifications.apps.NotificationsConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'examcraft.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'examcraft.wsgi.application'
ASGI_APPLICATION = 'examcraft.asgi.application'

# ==============================================================================
# Database Configuration — PostgreSQL hosted by Supabase
# ==============================================================================
DATABASE_URL = os.getenv('DATABASE_URL')
IS_TESTING = 'test' in sys.argv or 'pytest' in sys.modules or os.getenv('PYTEST_CURRENT_TEST')
FORCE_REMOTE_DB_FOR_TESTS = os.getenv('USE_REMOTE_DB_FOR_TESTS', '').lower() in ('true', '1', 'yes')

if IS_TESTING and not FORCE_REMOTE_DB_FOR_TESTS:
    # SQLite runner strictly for offline automated test suite execution in sandbox.
    # Keep the production Supabase connection for local or deployment runs.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'test_db.sqlite3',
        }
    }
elif DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=int(os.getenv('DB_CONN_MAX_AGE', '600')),
            conn_health_checks=True,
            ssl_require=os.getenv('DB_SSL_REQUIRE', 'True').lower() in ('true', '1', 'yes'),
        )
    }
else:
    # Individual connection parameters fallback
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER')
    db_password = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_port = os.getenv('DB_PORT', '5432')
    db_sslmode = os.getenv('DB_SSLMODE', 'require')

    if db_name and db_host:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': db_name,
                'USER': db_user,
                'PASSWORD': db_password,
                'HOST': db_host,
                'PORT': db_port,
                'OPTIONS': {
                    'sslmode': db_sslmode,
                },
                'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '600')),
                'CONN_HEALTH_CHECKS': True,
            }
        }
    else:
        # Default placeholder pointing to PostgreSQL Supabase configuration
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': 'postgres',
                'USER': 'postgres',
                'PASSWORD': '',
                'HOST': 'db.supabase.co',
                'PORT': '5432',
                'OPTIONS': {
                    'sslmode': 'require',
                },
            }
        }

# ==============================================================================
# Custom User Model (M1 User & Access Management)
# ==============================================================================
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

if IS_TESTING:
    PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.MD5PasswordHasher',
    ]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static and media files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
PRIVATE_MEDIA_ROOT = Path(os.getenv('PRIVATE_MEDIA_ROOT', BASE_DIR / 'private_media'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==============================================================================
# Django REST Framework Configuration
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'apps.common.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'apps.common.exceptions.custom_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '300/minute',
        'ai_generation': '10/minute',
        'auth_attempts': '10/minute',
    },
}

# ==============================================================================
# Simple JWT Configuration
# ==============================================================================
ACCESS_LIFETIME = int(os.getenv('ACCESS_TOKEN_LIFETIME_MINUTES', '60'))
REFRESH_LIFETIME = int(os.getenv('REFRESH_TOKEN_LIFETIME_DAYS', '7'))

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=ACCESS_LIFETIME),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=REFRESH_LIFETIME),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ==============================================================================
# OpenAPI / Swagger Specification (drf-spectacular)
# ==============================================================================
SPECTACULAR_SETTINGS = {
    'TITLE': 'ExamCraft AI Backend API',
    'DESCRIPTION': (
        'Multi-tenant REST API for AI-powered question paper generation, '
        'academic structure, and assessment management.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/v[0-9]+',
}

# ==============================================================================
# CORS Configuration
# ==============================================================================
CORS_ALLOWED_ORIGINS_STR = os.getenv('CORS_ALLOWED_ORIGINS', '')
if CORS_ALLOWED_ORIGINS_STR:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in CORS_ALLOWED_ORIGINS_STR.split(',') if o.strip()]
else:
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:5173',
    ]

CORS_ALLOW_CREDENTIALS = True

# ==============================================================================
# Google Gemini API Settings (M4 Backend Integration)
# ==============================================================================
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

# M18 SMTP delivery configuration. The application records notifications in-app
# even when email delivery has not been configured.
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 'yes')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', '')
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# M11 isolated execution-provider integration (submitted code never runs in Django).
CODE_EXECUTION_PROVIDER_URL = os.getenv('CODE_EXECUTION_PROVIDER_URL', '')
CODE_EXECUTION_PROVIDER_TOKEN = os.getenv('CODE_EXECUTION_PROVIDER_TOKEN', '')
CODE_EXECUTION_PROVIDER_TIMEOUT_SECONDS = int(os.getenv('CODE_EXECUTION_PROVIDER_TIMEOUT_SECONDS', '20'))

# M13 OCR-provider integration; OCR is not simulated when these are missing.
OCR_PROVIDER_URL = os.getenv('OCR_PROVIDER_URL', '')
OCR_PROVIDER_TOKEN = os.getenv('OCR_PROVIDER_TOKEN', '')
OCR_PROVIDER_TIMEOUT_SECONDS = int(os.getenv('OCR_PROVIDER_TIMEOUT_SECONDS', '30'))

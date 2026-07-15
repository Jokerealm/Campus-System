"""Django settings for the P3 resource-student service."""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

load_dotenv(REPO_DIR / ".env")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # A per-process development key avoids publishing a forgeable default.
        # Docker Compose requires an explicit stable key in .env.
        SECRET_KEY = secrets.token_urlsafe(50)
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be configured")
if not DEBUG and SECRET_KEY in {"change-me", "django-insecure-dev-only-change-me"}:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must not use a known placeholder")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "core",
    "resources",
    "students",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "p3_resource_student"),
        "USER": os.getenv("POSTGRES_USER", "p3"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "p3_password"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

WRONG_QUESTION_MAX_FILE_SIZE = int(
    os.getenv("WRONG_QUESTION_MAX_FILE_SIZE", str(10 * 1024 * 1024))
)
WRONG_QUESTION_ALLOWED_CONTENT_TYPES = [
    item.strip()
    for item in os.getenv(
        "WRONG_QUESTION_ALLOWED_CONTENT_TYPES",
        "image/jpeg,image/png,image/webp",
    ).split(",")
    if item.strip()
]

P1_CLIENT_MODE = os.getenv("P1_CLIENT_MODE", "mock")
P1_BASE_URL = os.getenv("P1_BASE_URL", "http://p1-ai-core:8101/api/ai/v1")
P1_TIMEOUT_SECONDS = float(os.getenv("P1_TIMEOUT_SECONDS", "10"))
P1_SERVICE_ID = os.getenv("P1_SERVICE_ID", "p3-service")
P1_AUTH_TOKEN = os.getenv("P1_AUTH_TOKEN", "")
P1_FILE_BASE_URL = os.getenv("P1_FILE_BASE_URL", "").rstrip("/")
P1_FILE_URL_TTL_SECONDS = int(os.getenv("P1_FILE_URL_TTL_SECONDS", "3600"))
P1_RECOGNITION_START_GRACE_SECONDS = int(
    os.getenv("P1_RECOGNITION_START_GRACE_SECONDS", "30")
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "P3 Resource Student API",
    "DESCRIPTION": "Question bank and student training APIs for the education system.",
    "VERSION": "0.1.0",
    "ENUM_NAME_OVERRIDES": {
        "QuestionSourceEnum": [
            ("school_bank", "School bank"),
            ("exam_history", "Exam history"),
            ("middle_exam_real", "Middle exam real"),
            ("external_import", "External import"),
            ("ai_generated", "AI generated"),
        ],
        "QuestionAuditStatusEnum": [
            ("draft", "Draft"),
            ("pending_review", "Pending review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("archived", "Archived"),
        ],
        "GeneratedQuestionAuditStatusEnum": [
            ("pending_review", "Pending review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    },
}

"""
Django settings for config project.
"""

import os
import sys
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def _load_local_env_file(env_path: Path) -> None:
    """
    Lightweight .env loader (no external dependency).

    Loads KEY=VALUE pairs into process environment only when the key is not
    already defined, so explicit OS env vars still win.
    """
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                os.environ.setdefault(key, value)
    except Exception:
        # Startup should not fail because of malformed local .env content.
        pass


_load_local_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-%guzx%8oun1^^b*h+05ig*blhk*$9&szs22_^b1x!n*%-q)f72",
)

DEBUG = os.getenv("DEBUG", "True").lower() == "true"

ALLOWED_HOSTS = ['*', 'testserver', 'localhost', '127.0.0.1']

AUTH_USER_MODEL = "users.User"


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'drf_spectacular',

    'users',
    'stores',
    'categories',
    'products',
    'orders',
    'themes',
    'seo',
    'AI_Store_Creation_Service',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'users.middleware.JWTTenantMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Custom middleware for error handling and request context
    'utils.middleware.RequestContextMiddleware',
    'utils.middleware.ExceptionHandlerMiddleware',
]


ROOT_URLCONF = 'config.urls'


TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'config.wsgi.application'


def _database_config_from_url(database_url: str):
    parsed = urlparse(database_url)
    scheme = (parsed.scheme or "").lower()

    if scheme in ("postgres", "postgresql"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (parsed.path or "").lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }

    if scheme in ("sqlite", "sqlite3"):
        db_path = (parsed.path or "").lstrip("/") or "db.sqlite3"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / db_path),
        }

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme}")


DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": _database_config_from_url(DATABASE_URL)
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
            "NAME": os.getenv("DB_NAME", "ai_store_db"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", "1234"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5433"),
        }
    }


CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "False").lower() == "true"
if not CORS_ALLOW_ALL_ORIGINS:
    _cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    CORS_ALLOWED_ORIGINS = [
        origin.strip() for origin in _cors_origins.split(",") if origin.strip()
    ]
CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "True").lower() == "true"


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# drf-spectacular Configuration
SPECTACULAR_SETTINGS = {
    "TITLE": "AI Store Backend API",
    "DESCRIPTION": """
    Multi-Tenant E-commerce Backend API with AI-Powered Features
    
    **Authentication:**
    - JWT Bearer Token (SimplJWT)
    - Email/Password login
    - Email activation required
    
    **Features:**
    - Multi-tenant isolation (tenant_id per user)
    - Store management (CRUD, domains, settings)
    - Product catalog with categories
    - Inventory management
    - Image gallery
    
    **API Endpoints:**
    - `/api/auth/` - User authentication
    - `/api/auth/me/` - Protected current-user identity endpoint (Bearer token required)
    - `/api/auth/register/` - Public self-registration endpoint (no authentication required)
    - `/api/stores/` - Store management
    - `/api/` - Products and Categories
    - `/api/docs/` - Swagger UI (this page)
    - `/api/redoc/` - ReDoc documentation
    - `/api/schema/` - OpenAPI schema (JSON)
    """,
    "VERSION": "1.0.0",
    "CONTACT": {
        "name": "Support Team",
        "email": "support@example.com",
    },
    "LICENSE": {
        "name": "MIT",
    },
    "SERVERS": [
        {
            "url": "http://localhost:8000",
            "description": "Development Server",
        },
        {
            "url": "https://api.example.com",
            "description": "Production Server",
        },
    ],
    "SCHEMA_PATH_PREFIX": "/api/",
    "AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "SECURITY_SCHEMES": {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT Bearer token for API authentication",
        }
    },
    "SECURITY": [
        {
            "Bearer": []
        }
    ],
    "PRELOAD_ENUM_CHOICES": True,
    "ENUM_GENERATE_CHOICES": True,
    "TAGS_SORT_ALPHABETICALLY": False,
    "X_IGNORE_AUTODISCOVERY": False,
}


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Email backend for development (console)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@example.com'

# Logging configuration
LOGGING_CONFIG = 'logging.config.dictConfig'

from utils.logging_config import LOGGING_CONFIG as CUSTOM_LOGGING  # noqa

LOGGING = CUSTOM_LOGGING


# AI Store Creation configuration (foundation only)
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL_NAME = os.getenv("AI_MODEL_NAME", "qwen2.5:1.5b")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "120"))
AI_API_URL = os.getenv("AI_API_URL", "http://localhost:11434/api/chat")
AI_HTTP_REFERER = os.getenv("AI_HTTP_REFERER", "")
AI_APP_TITLE = os.getenv("AI_APP_TITLE", "")
AI_DRAFT_CACHE_TTL = int(os.getenv("AI_DRAFT_CACHE_TTL", os.getenv("AI_DRAFT_TTL", "3600")))
# Backward-compatible alias used by draft_store helpers.
AI_DRAFT_TTL = AI_DRAFT_CACHE_TTL
AI_DRAFT_PREFIX = os.getenv("AI_DRAFT_PREFIX", "ai_draft")


# Cache configuration for temporary AI drafts.
# Rule:
# - If REDIS_URL exists, use Redis (django-redis backend)
# - Otherwise, use local-memory cache (safe local/dev fallback)
RUNNING_TESTS = "test" in sys.argv or bool(os.getenv("PYTEST_CURRENT_TEST"))
REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_BACKEND = os.getenv("CACHE_BACKEND", "").strip().lower()
CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", "ai_store_creation")

# Development-safe override:
# - CACHE_BACKEND=locmem forces local memory cache even if REDIS_URL is set.
if RUNNING_TESTS or CACHE_BACKEND == "locmem" or not REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ai-store-creation-local-cache",
            "TIMEOUT": AI_DRAFT_CACHE_TTL,
            "KEY_PREFIX": CACHE_KEY_PREFIX,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": AI_DRAFT_CACHE_TTL,
            "KEY_PREFIX": CACHE_KEY_PREFIX,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": True,
            },
        }
    }

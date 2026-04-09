"""
Logging configuration for the application.
إعدادات التسجيل (Logging) للتطبيق.
"""
import os
from pathlib import Path

# تحديد مسار مجلد السجلات
LOGS_DIR = Path(__file__).parent.parent / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

# إعدادات LOGGING الكاملة
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {funcName}:{lineno} - {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '{levelname} {asctime} {name} - {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        # Console handler
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        # File handler for all logs
        'file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'app.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        # File handler for errors only
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'error.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        # File handler for database operations
        'database_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'database.log'),
            'maxBytes': 1024 * 1024 * 5,  # 5MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        # File handler for security events
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'security.log'),
            'maxBytes': 1024 * 1024 * 5,  # 5MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        # File handler for API requests
        'api_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOGS_DIR / 'api.log'),
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        # Root logger
        'django': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'INFO',
            'propagate': False,
        },
        # Django database logger
        'django.db.backends': {
            'handlers': ['database_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        # Django security logger
        'django.security': {
            'handlers': ['console', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        # Project app loggers
        'users': {
            'handlers': ['console', 'file', 'error_file', 'security_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'stores': {
            'handlers': ['console', 'file', 'error_file', 'api_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'categories': {
            'handlers': ['console', 'file', 'error_file', 'api_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'products': {
            'handlers': ['console', 'file', 'error_file', 'api_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'utils': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        # REST Framework logger
        'rest_framework': {
            'handlers': ['console', 'file', 'api_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

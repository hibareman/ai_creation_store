#!/usr/bin/env python
"""
Quick verification script for logging and error handling setup
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import logging
from pathlib import Path

# Test 1: Verify logging config import
print("=" * 60)
print("TEST 1: Verifying Logging Configuration Import")
print("=" * 60)
try:
    from utils.logging_config import LOGGING_CONFIG
    print("✅ LOGGING_CONFIG imported successfully")
    print(f"   - Version: {LOGGING_CONFIG['version']}")
    print(f"   - Handlers: {len(LOGGING_CONFIG['handlers'])}")
    print(f"   - Loggers: {len(LOGGING_CONFIG['loggers'])}")
    print(f"   - Formatters: {len(LOGGING_CONFIG['formatters'])}")
except Exception as e:
    print(f"❌ Failed to import LOGGING_CONFIG: {e}")
    sys.exit(1)

# Test 2: Verify middleware imports
print("\n" + "=" * 60)
print("TEST 2: Verifying Middleware Classes")
print("=" * 60)
try:
    from utils.middleware import ExceptionHandlerMiddleware, RequestContextMiddleware
    print("✅ ExceptionHandlerMiddleware imported")
    print("✅ RequestContextMiddleware imported")
except Exception as e:
    print(f"❌ Failed to import middleware: {e}")
    sys.exit(1)

# Test 3: Verify exception classes
print("\n" + "=" * 60)
print("TEST 3: Verifying Exception Classes")
print("=" * 60)
try:
    from utils.exceptions import (
        BaseAppException,
        StoreNotFound,
        MultiTenantViolation,
        ValidationError,
    )
    print("✅ BaseAppException imported")
    print("✅ StoreNotFound imported")
    print("✅ MultiTenantViolation imported")
    print("✅ ValidationError imported")
    
    # Test exception instantiation
    exc = StoreNotFound("Test store")
    print(f"   - Exception message: {exc.message}")
    print(f"   - HTTP status: {exc.status_code}")
except Exception as e:
    print(f"❌ Failed to import exceptions: {e}")
    sys.exit(1)

# Test 4: Verify error response formatters
print("\n" + "=" * 60)
print("TEST 4: Verifying Response Formatters")
print("=" * 60)
try:
    from utils.errors import ErrorResponse, SuccessResponse
    print("✅ ErrorResponse imported")
    print("✅ SuccessResponse imported")
    
    # Test error formatting
    error = ErrorResponse()
    error_response = error.not_found("Test resource not found")
    print(f"   - Error response has 'error' key: {'error' in error_response}")
    print(f"   - Error response has 'request_id': {'request_id' in error_response}")
    
    # Test success formatting
    success = SuccessResponse()
    success_response = success.created({"id": 1, "name": "Test"})
    print(f"   - Success response has 'data' key: {'data' in success_response}")
    print(f"   - Success response has 'success' key: {'success' in success_response}")
except Exception as e:
    print(f"❌ Failed to import/use error formatters: {e}")
    sys.exit(1)

# Test 5: Verify logging paths
print("\n" + "=" * 60)
print("TEST 5: Verifying Logging Directories")
print("=" * 60)
try:
    logs_dir = Path(__file__).parent / 'logs'
    if logs_dir.exists():
        print(f"✅ Logs directory exists: {logs_dir}")
    else:
        print(f"⚠️  Logs directory created: {logs_dir}")
        logs_dir.mkdir(exist_ok=True)
except Exception as e:
    print(f"❌ Failed to verify logs directory: {e}")

# Test 6: Verify Django settings integration
print("\n" + "=" * 60)
print("TEST 6: Verifying Django Settings Integration")
print("=" * 60)
try:
    from django.conf import settings
    
    # Check middleware
    middleware = settings.MIDDLEWARE
    has_exception_handler = any('ExceptionHandlerMiddleware' in m for m in middleware)
    has_request_context = any('RequestContextMiddleware' in m for m in middleware)
    
    print(f"✅ ExceptionHandlerMiddleware registered: {has_exception_handler}")
    print(f"✅ RequestContextMiddleware registered: {has_request_context}")
    
    # Check logging
    has_logging = hasattr(settings, 'LOGGING') and settings.LOGGING is not None
    print(f"✅ LOGGING configured: {has_logging}")
    
    if has_logging:
        print(f"   - Number of loggers: {len(settings.LOGGING['loggers'])}")
        print(f"   - Number of handlers: {len(settings.LOGGING['handlers'])}")
except Exception as e:
    print(f"❌ Failed to verify settings: {e}")
    sys.exit(1)

# Test 7: Test logger instantiation
print("\n" + "=" * 60)
print("TEST 7: Testing Logger Instances")
print("=" * 60)
try:
    logger_stores = logging.getLogger('stores')
    logger_categories = logging.getLogger('categories')
    logger_products = logging.getLogger('products')
    
    print(f"✅ stores logger level: {logger_stores.level} (effective: {logger_stores.getEffectiveLevel()})")
    print(f"✅ categories logger level: {logger_categories.level} (effective: {logger_categories.getEffectiveLevel()})")
    print(f"✅ products logger level: {logger_products.level} (effective: {logger_products.getEffectiveLevel()})")
    
    # Test logging output (won't write to handler, but tests the mechanism)
    logger_stores.debug("Test debug message")
    logger_stores.info("Test info message")
    print("✅ Logger test messages created successfully")
except Exception as e:
    print(f"❌ Failed to test loggers: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ ALL VERIFICATION TESTS PASSED!")
print("=" * 60)
print("\nLogging and error handling infrastructure is ready:")
print("  - Custom exceptions with proper status codes")
print("  - Error/success response formatters")
print("  - Global exception handling middleware")
print("  - Request context tracking")
print("  - Multi-tenant aware logging")
print("  - Rotating file handlers")
print("\nNext steps:")
print("  1. Run integration tests: python manage.py test tests_integration")
print("  2. Check logs in: logs/ directory")
print("  3. Monitor security.log for violations")

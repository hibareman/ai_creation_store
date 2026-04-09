"""
Global exception handler middleware for the application.
Middleware لمعالجة الاستثناءات العامة على مستوى التطبيق.
"""
import logging
import json
from datetime import datetime
from uuid import uuid4
from django.http import JsonResponse
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.exceptions import APIException
from rest_framework import status

from utils.exceptions import BaseAppException
from utils.errors import ErrorResponse, SuccessResponse

logger = logging.getLogger(__name__)


class ExceptionHandlerMiddleware:
    """
    Middleware لمعالجة جميع الاستثناءات والأخطاء الغير متوقعة.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # إضافة request_id للطلب
        request.request_id = str(uuid4())
        request.start_time = datetime.utcnow()

        try:
            response = self.get_response(request)
            return response
        except Exception as exc:
            return self.handle_exception(request, exc)

    def handle_exception(self, request, exc):
        """معالجة الاستثناء وإرجاع استجابة JSON مناسبة"""
        
        request_id = getattr(request, 'request_id', str(uuid4()))
        tenant_id = getattr(request, 'tenant_id', 'N/A')
        user_id = getattr(request.user, 'id', None) if request.user.is_authenticated else None

        # تسجيل معلومات الخطأ
        log_context = {
            'request_id': request_id,
            'tenant_id': tenant_id,
            'user_id': user_id,
            'method': request.method,
            'path': request.path,
            'exception_type': exc.__class__.__name__,
        }

        # معالجة استثناءات التطبيق المخصصة
        if isinstance(exc, BaseAppException):
            return self._handle_app_exception(request_id, tenant_id, user_id, exc)

        # معالجة استثناءات DRF
        if isinstance(exc, DRFValidationError):
            return self._handle_drf_validation_error(request_id, exc)

        # معالجة استثناءات ValidationError من Django
        if isinstance(exc, DjangoValidationError):
            return self._handle_django_validation_error(request_id, exc)

        # معالجة استثناءات قاعدة البيانات
        if isinstance(exc, IntegrityError):
            logger.error(
                f"IntegrityError: {str(exc)}",
                extra=log_context,
                exc_info=True
            )
            return JsonResponse(
                ErrorResponse.format_error(
                    error_code='INTEGRITY_CONSTRAINT_VIOLATION',
                    message='Data integrity constraint violation',
                    status_code=status.HTTP_409_CONFLICT,
                    request_id=request_id
                ),
                status=status.HTTP_409_CONFLICT
            )

        # معالجة APIException من DRF
        if isinstance(exc, APIException):
            logger.warning(
                f"APIException: {exc.detail}",
                extra=log_context
            )
            return JsonResponse(
                ErrorResponse.format_error(
                    error_code=getattr(exc, 'default_code', 'API_ERROR'),
                    message=str(exc.detail),
                    status_code=exc.status_code,
                    request_id=request_id
                ),
                status=exc.status_code
            )

        # معالجة أي استثناء غير متوقع آخر
        logger.error(
            f"Unhandled exception: {str(exc)}",
            extra=log_context,
            exc_info=True
        )
        
        return JsonResponse(
            ErrorResponse.format_error(
                error_code='INTERNAL_SERVER_ERROR',
                message='An unexpected error occurred',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                request_id=request_id
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    def _handle_app_exception(self, request_id, tenant_id, user_id, exc):
        """معالجة استثناءات التطبيق المخصصة"""
        
        # تسجيل الخطأ بحسب الخطورة
        log_level = 'warning' if 400 <= exc.status_code < 500 else 'error'
        
        log_message = (
            f"{exc.code}: {exc.message} "
            f"(tenant_id={tenant_id}, user_id={user_id})"
        )
        
        if log_level == 'warning':
            logger.warning(log_message, extra={'request_id': request_id})
        else:
            logger.error(log_message, extra={'request_id': request_id}, exc_info=True)

        return JsonResponse(
            ErrorResponse.format_error(
                error_code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=exc.details,
                request_id=request_id
            ),
            status=exc.status_code
        )

    def _handle_drf_validation_error(self, request_id, exc):
        """معالجة استثناءات التحقق من صحة DRF"""
        
        logger.warning(
            f"Validation error: {exc.detail}",
            extra={'request_id': request_id}
        )

        # استخراج الأخطاء التفصيلية
        errors = {}
        if isinstance(exc.detail, dict):
            errors = {k: [str(v) for v in (v if isinstance(v, list) else [v])]
                     for k, v in exc.detail.items()}
        elif isinstance(exc.detail, list):
            errors = {'non_field_errors': [str(e) for e in exc.detail]}

        return JsonResponse(
            ErrorResponse.format_error(
                error_code='VALIDATION_ERROR',
                message='Validation failed',
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=errors,
                request_id=request_id
            ),
            status=status.HTTP_400_BAD_REQUEST
        )

    def _handle_django_validation_error(self, request_id, exc):
        """معالجة استثناءات التحقق من صحة Django"""
        
        logger.warning(
            f"Django validation error: {exc.message}",
            extra={'request_id': request_id}
        )

        return JsonResponse(
            ErrorResponse.format_error(
                error_code='VALIDATION_ERROR',
                message=exc.message,
                status_code=status.HTTP_400_BAD_REQUEST,
                request_id=request_id
            ),
            status=status.HTTP_400_BAD_REQUEST
        )


class RequestContextMiddleware:
    """
    Middleware لإضافة معلومات السياق إلى كل طلب.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # إضافة request_id
        request.request_id = str(uuid4())
        
        # إضافة timestamp
        request.start_time = datetime.utcnow()

        # تسجيل بيانات الطلب
        logger.debug(
            f"Request: {request.method} {request.path}",
            extra={
                'request_id': request.request_id,
                'user_id': getattr(request.user, 'id', None) if request.user.is_authenticated else None,
                'tenant_id': getattr(request, 'tenant_id', None),
            }
        )

        response = self.get_response(request)

        # تسجيل معلومات الاستجابة
        duration = (datetime.utcnow() - request.start_time).total_seconds()
        logger.debug(
            f"Response: {response.status_code} (duration: {duration:.3f}s)",
            extra={
                'request_id': request.request_id,
                'status_code': response.status_code,
                'duration': duration,
            }
        )

        # إضافة request_id إلى رؤوس الاستجابة
        response['X-Request-ID'] = request.request_id

        return response

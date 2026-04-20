"""
Global exception handler middleware for the application.
Plain JSON responses without success envelope wrapping.
"""
import logging
import json
from typing import Any
from datetime import datetime
from uuid import uuid4

from django.http import JsonResponse, HttpResponse
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.exceptions import APIException
from rest_framework import status
from rest_framework.response import Response as DRFResponse

from utils.exceptions import BaseAppException
from utils.errors import ErrorResponse
from utils.response_format import (
    DEFAULT_ERROR_MESSAGE,
    extract_error_message,
    is_enveloped_payload,
    normalize_http_status_code,
    normalize_success_data,
)

logger = logging.getLogger(__name__)


class ExceptionHandlerMiddleware:
    """
    Middleware لمعالجة جميع الاستثناءات والأخطاء غير المتوقعة.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid4())
        request.start_time = datetime.utcnow()

        try:
            response = self.get_response(request)
            return response
        except Exception as exc:
            return self.handle_exception(request, exc)

    def handle_exception(self, request, exc):
        request_id = getattr(request, 'request_id', str(uuid4()))
        tenant_id = getattr(request, 'tenant_id', 'N/A')
        user = getattr(request, 'user', None)
        user_id = getattr(user, 'id', None) if getattr(user, 'is_authenticated', False) else None

        log_context = {
            'request_id': request_id,
            'tenant_id': tenant_id,
            'user_id': user_id,
            'method': request.method,
            'path': request.path,
            'exception_type': exc.__class__.__name__,
        }

        if isinstance(exc, BaseAppException):
            return self._handle_app_exception(request_id, tenant_id, user_id, exc)

        if isinstance(exc, DRFValidationError):
            return self._handle_drf_validation_error(request_id, exc)

        if isinstance(exc, DjangoValidationError):
            return self._handle_django_validation_error(request_id, exc)

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
                    status_code=status.HTTP_400_BAD_REQUEST,
                    request_id=request_id
                ),
                status=status.HTTP_400_BAD_REQUEST
            )

        if isinstance(exc, APIException):
            logger.warning(
                f"APIException: {exc.detail}",
                extra=log_context
            )
            normalized_status = normalize_http_status_code(exc.status_code)
            return JsonResponse(
                ErrorResponse.format_error(
                    error_code=getattr(exc, 'default_code', 'API_ERROR'),
                    message=str(exc.detail),
                    status_code=normalized_status,
                    request_id=request_id
                ),
                status=normalized_status
            )

        logger.error(
            f"Unhandled exception: {str(exc)}",
            extra=log_context,
            exc_info=True
        )

        return JsonResponse(
            ErrorResponse.format_error(
                error_code='INTERNAL_SERVER_ERROR',
                message='An unexpected error occurred',
                status_code=status.HTTP_400_BAD_REQUEST,
                request_id=request_id
            ),
            status=status.HTTP_400_BAD_REQUEST
        )

    def _handle_app_exception(self, request_id, tenant_id, user_id, exc):
        log_level = 'warning' if 400 <= exc.status_code < 500 else 'error'

        log_message = (
            f"{exc.code}: {exc.message} "
            f"(tenant_id={tenant_id}, user_id={user_id})"
        )

        if log_level == 'warning':
            logger.warning(log_message, extra={'request_id': request_id})
        else:
            logger.error(log_message, extra={'request_id': request_id}, exc_info=True)

        normalized_status = normalize_http_status_code(exc.status_code)

        return JsonResponse(
            ErrorResponse.format_error(
                error_code=exc.code,
                message=exc.message,
                status_code=normalized_status,
                details=exc.details,
                request_id=request_id
            ),
            status=normalized_status
        )

    def _handle_drf_validation_error(self, request_id, exc):
        logger.warning(
            f"Validation error: {exc.detail}",
            extra={'request_id': request_id}
        )

        errors = {}
        if isinstance(exc.detail, dict):
            errors = {
                k: [str(v) for v in (v if isinstance(v, list) else [v])]
                for k, v in exc.detail.items()
            }
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
        logger.warning(
            f"Django validation error: {exc}",
            extra={'request_id': request_id}
        )

        message = ""
        if hasattr(exc, "messages") and exc.messages:
            message = str(exc.messages[0])
        elif hasattr(exc, "message"):
            message = str(exc.message)
        else:
            message = str(exc)

        return JsonResponse(
            ErrorResponse.format_error(
                error_code='VALIDATION_ERROR',
                message=message,
                status_code=status.HTTP_400_BAD_REQUEST,
                request_id=request_id
            ),
            status=status.HTTP_400_BAD_REQUEST
        )


class RequestContextMiddleware:
    """
    Middleware لإضافة معلومات السياق إلى كل طلب
    مع إزالة success envelope والإبقاء على JSON plain.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid4())
        request.start_time = datetime.utcnow()

        user = getattr(request, 'user', None)
        logger.debug(
            f"Request: {request.method} {request.path}",
            extra={
                'request_id': request.request_id,
                'user_id': getattr(user, 'id', None) if getattr(user, 'is_authenticated', False) else None,
                'tenant_id': getattr(request, 'tenant_id', None),
            }
        )

        response = self.get_response(request)
        response = self._standardize_api_response(request, response)

        duration = (datetime.utcnow() - request.start_time).total_seconds()
        logger.debug(
            f"Response: {response.status_code} (duration: {duration:.3f}s)",
            extra={
                'request_id': request.request_id,
                'status_code': response.status_code,
                'duration': duration,
            }
        )

        response['X-Request-ID'] = request.request_id
        return response

    @staticmethod
    def _should_standardize_response(path: str) -> bool:
        if not path.startswith('/api/'):
            return False

        excluded_paths = ('/api/schema/', '/api/docs/', '/api/redoc/')
        return not any(path.startswith(prefix) for prefix in excluded_paths)

    def _standardize_api_response(self, request, response):
        if not self._should_standardize_response(request.path):
            return response

        raw_status_code = int(getattr(response, 'status_code', status.HTTP_200_OK))
        status_code = self._normalize_status_for_request(request, raw_status_code)
        payload = self._extract_payload(response)

        if status_code == status.HTTP_204_NO_CONTENT:
            empty_response = HttpResponse(status=status.HTTP_204_NO_CONTENT)
            for header, value in response.items():
                header_lower = header.lower()
                if header_lower in {'content-type', 'content-length'}:
                    continue
                empty_response[header] = value
            return empty_response

        if status_code >= status.HTTP_400_BAD_REQUEST:
            if is_enveloped_payload(payload):
                plain_payload = {"detail": payload.get("message") or DEFAULT_ERROR_MESSAGE}
            elif isinstance(payload, dict):
                plain_payload = payload
                if not plain_payload:
                    plain_payload = {"detail": DEFAULT_ERROR_MESSAGE}
            else:
                plain_payload = {"detail": extract_error_message(payload, default=DEFAULT_ERROR_MESSAGE)}

            wrapped_response = JsonResponse(plain_payload, status=status_code)
        else:
            if is_enveloped_payload(payload):
                plain_payload = payload.get("data")
            else:
                plain_payload = normalize_success_data(payload)

            if plain_payload is None:
                if status_code == status.HTTP_201_CREATED:
                    plain_payload = {}
                else:
                    plain_payload = None

            if isinstance(plain_payload, (dict, list)):
                wrapped_response = JsonResponse(plain_payload, status=status_code, safe=not isinstance(plain_payload, list))
            elif plain_payload is None:
                wrapped_response = HttpResponse(status=status_code)
            else:
                wrapped_response = JsonResponse(plain_payload, status=status_code, safe=False)

        for header, value in response.items():
            header_lower = header.lower()
            if header_lower in {'content-type', 'content-length'}:
                continue
            wrapped_response[header] = value

        return wrapped_response

    @staticmethod
    def _extract_payload(response) -> Any:
        if isinstance(response, DRFResponse):
            return response.data

        content = getattr(response, 'content', b'')
        if not content:
            return None

        try:
            decoded = content.decode('utf-8')
        except Exception:
            return None

        trimmed = decoded.strip().lower()
        if trimmed.startswith('<!doctype') or trimmed.startswith('<html'):
            return None

        try:
            return json.loads(decoded)
        except (TypeError, ValueError):
            return decoded if isinstance(decoded, str) else None

    @staticmethod
    def _normalize_status_for_request(request, raw_status_code: int) -> int:
        if request.method == 'DELETE' and raw_status_code < status.HTTP_400_BAD_REQUEST:
            return status.HTTP_204_NO_CONTENT

        return normalize_http_status_code(raw_status_code)
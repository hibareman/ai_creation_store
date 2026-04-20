"""
Error response utilities and plain-response formatters.
"""
from typing import Dict, Any, List
from rest_framework.response import Response
from rest_framework import status

from utils.response_format import error_payload, success_payload


class ErrorResponse:
    """Plain error response formatter."""

    @staticmethod
    def format_error(
        error_code: str,
        message: str,
        status_code: int = 500,
        details: Dict[str, Any] = None,
        request_id: str = None,
        errors: Dict = None
    ) -> Dict[str, Any]:
        """
        Return plain error payload without envelope.
        Keep useful details when available.
        """
        payload = {"detail": message}

        if errors:
            payload["errors"] = errors

        if details:
            payload["details"] = details

        if error_code:
            payload["code"] = error_code

        return payload

    @staticmethod
    def response(
        error_code: str,
        message: str,
        status_code: int = 500,
        details: Dict[str, Any] = None,
        request_id: str = None,
        errors: Dict = None
    ) -> Response:
        data = ErrorResponse.format_error(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            request_id=request_id,
            errors=errors
        )
        return Response(data, status=status_code)

    @staticmethod
    def validation_error(
        message: str,
        field_errors: Dict[str, List[str]] = None,
        request_id: str = None
    ) -> Response:
        return ErrorResponse.response(
            error_code='VALIDATION_ERROR',
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            errors=field_errors or {},
            request_id=request_id
        )

    @staticmethod
    def not_found(
        resource_type: str,
        resource_id: Any = None,
        request_id: str = None
    ) -> Response:
        message = f"{resource_type}"
        if resource_id:
            message += f" {resource_id}"
        message += " not found"

        return ErrorResponse.response(
            error_code='NOT_FOUND',
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details={'resource_type': resource_type, 'resource_id': resource_id},
            request_id=request_id
        )

    @staticmethod
    def permission_denied(
        message: str = None,
        resource: str = None,
        request_id: str = None
    ) -> Response:
        return ErrorResponse.response(
            error_code='PERMISSION_DENIED',
            message=message or 'You do not have permission to access this resource',
            status_code=status.HTTP_403_FORBIDDEN,
            details={'resource': resource} if resource else None,
            request_id=request_id
        )

    @staticmethod
    def conflict(
        error_code: str,
        message: str,
        details: Dict = None,
        request_id: str = None
    ) -> Response:
        return ErrorResponse.response(
            error_code=error_code,
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
            request_id=request_id
        )

    @staticmethod
    def internal_server_error(
        message: str = None,
        request_id: str = None,
        error_details: Dict = None
    ) -> Response:
        return ErrorResponse.response(
            error_code='INTERNAL_SERVER_ERROR',
            message=message or 'An unexpected error occurred',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=error_details,
            request_id=request_id
        )


class SuccessResponse:
    """Plain success response formatter."""

    @staticmethod
    def format_success(
        data: Any = None,
        message: str = None,
        request_id: str = None,
        extra_fields: Dict = None
    ) -> Any:
        """
        Return plain success data without envelope.
        Merge extra_fields into dict payloads when relevant.
        """
        payload = data

        if extra_fields:
            if payload is None:
                payload = extra_fields
            elif isinstance(payload, dict):
                merged = dict(payload)
                merged.update(extra_fields)
                payload = merged

        return payload

    @staticmethod
    def response(
        data: Any = None,
        message: str = None,
        status_code: int = status.HTTP_200_OK,
        request_id: str = None,
        extra_fields: Dict = None
    ) -> Response:
        data_dict = SuccessResponse.format_success(
            data=data,
            message=message,
            request_id=request_id,
            extra_fields=extra_fields
        )
        return Response(data_dict, status=status_code)

    @staticmethod
    def created(
        data: Any = None,
        message: str = 'Resource created successfully',
        request_id: str = None
    ) -> Response:
        return SuccessResponse.response(
            data=data,
            message=message,
            status_code=status.HTTP_201_CREATED,
            request_id=request_id
        )

    @staticmethod
    def updated(
        data: Any = None,
        message: str = 'Resource updated successfully',
        request_id: str = None
    ) -> Response:
        return SuccessResponse.response(
            data=data,
            message=message,
            status_code=status.HTTP_200_OK,
            request_id=request_id
        )

    @staticmethod
    def deleted(
        message: str = 'Resource deleted successfully',
        request_id: str = None
    ) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def list(
        data: list,
        total_count: int = None,
        page: int = None,
        page_size: int = None,
        request_id: str = None
    ) -> Response:
        extra_fields = {}

        if total_count is not None:
            extra_fields['total_count'] = total_count

        if page is not None:
            extra_fields['page'] = page

        if page_size is not None:
            extra_fields['page_size'] = page_size

        return SuccessResponse.response(
            data=data,
            status_code=status.HTTP_200_OK,
            request_id=request_id,
            extra_fields=extra_fields if isinstance(data, dict) else None
        )
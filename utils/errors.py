"""
Error response utilities and formatters.
أدوات تنسيق استجابات الأخطاء.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from rest_framework.response import Response
from rest_framework import status


class ErrorResponse:
    """منسق استجابات الأخطاء الموحدة"""

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
        تنسيق استجابة خطأ موحدة.
        
        Args:
            error_code: كود الخطأ (مثل: VALIDATION_ERROR)
            message: رسالة الخطأ
            status_code: HTTP status code
            details: تفاصيل إضافية
            request_id: معرّف الطلب
            errors: قاموس الأخطاء التفصيلية (مثل validation errors)
        
        Returns:
            قاموس استجابة الخطأ
        """
        return {
            'success': False,
            'error': {
                'code': error_code,
                'message': message,
                'details': details or {},
                'errors': errors or {},
                'request_id': request_id or str(uuid.uuid4()),
                'timestamp': datetime.utcnow().isoformat(),
            }
        }

    @staticmethod
    def response(
        error_code: str,
        message: str,
        status_code: int = 500,
        details: Dict[str, Any] = None,
        request_id: str = None,
        errors: Dict = None
    ) -> Response:
        """
        إنشاء DRF Response للخطأ.
        
        Returns:
            DRF Response object مع status code مناسب
        """
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
        """استجابة خطأ التحقق من الصحة"""
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
        """استجابة الموارد غير الموجودة"""
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
        """استجابة الوصول المرفوض"""
        return ErrorResponse.response(
            error_code='PERMISSION_DENIED',
            message=message or 'You do not have permission to access this resource',
            status_code=status.HTTP_403_FORBIDDEN,
            details={'resource': resource},
            request_id=request_id
        )

    @staticmethod
    def conflict(
        error_code: str,
        message: str,
        details: Dict = None,
        request_id: str = None
    ) -> Response:
        """استجابة التعارض (مثل: slug مأخوز، منتج موجود بالفعل)"""
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
        """استجابة خطأ الخادم الداخلي"""
        return ErrorResponse.response(
            error_code='INTERNAL_SERVER_ERROR',
            message=message or 'An unexpected error occurred',
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=error_details,
            request_id=request_id
        )


class SuccessResponse:
    """منسق استجابات النجاح الموحدة"""

    @staticmethod
    def format_success(
        data: Any = None,
        message: str = None,
        request_id: str = None,
        extra_fields: Dict = None
    ) -> Dict[str, Any]:
        """
        تنسيق استجابة نجاح موحدة.
        
        Args:
            data: بيانات الاستجابة
            message: رسالة نجاح اختيارية
            request_id: معرّف الطلب
            extra_fields: حقول إضافية
        
        Returns:
            قاموس استجابة النجاح
        """
        response = {
            'success': True,
            'data': data,
            'request_id': request_id or str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat(),
        }
        
        if message:
            response['message'] = message
        
        if extra_fields:
            response.update(extra_fields)
        
        return response

    @staticmethod
    def response(
        data: Any = None,
        message: str = None,
        status_code: int = status.HTTP_200_OK,
        request_id: str = None,
        extra_fields: Dict = None
    ) -> Response:
        """
        إنشاء DRF Response للنجاح.
        
        Returns:
            DRF Response object مع status code مناسب
        """
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
        """استجابة الإنشاء الناجح (201)"""
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
        """استجابة التحديث الناجح (200)"""
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
        """استجابة الحذف الناجح (204)"""
        return SuccessResponse.response(
            data=None,
            message=message,
            status_code=status.HTTP_204_NO_CONTENT,
            request_id=request_id
        )

    @staticmethod
    def list(
        data: list,
        total_count: int = None,
        page: int = None,
        page_size: int = None,
        request_id: str = None
    ) -> Response:
        """استجابة قائمة البيانات"""
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
            extra_fields=extra_fields
        )

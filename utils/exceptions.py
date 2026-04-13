"""
Custom Exception classes for the AI Store Creation backend.
ملفات استثناءات مخصصة لمعالجة أخطاء الأعمال المختلفة.
"""
from rest_framework.exceptions import APIException


class BaseAppException(Exception):
    """Base exception for all application exceptions"""
    def __init__(self, message, code=None, details=None, status_code=500):
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        self.status_code = status_code
        super().__init__(self.message)


# ============ Business Logic Exceptions ============

class StoreNotFound(BaseAppException):
    """المتجر غير موجود"""
    def __init__(self, store_id=None, message=None):
        super().__init__(
            message or f"Store {store_id} not found",
            code='STORE_NOT_FOUND',
            status_code=404
        )


class StoreAlreadyExists(BaseAppException):
    """المتجر موجود بالفعل"""
    def __init__(self, name=None, message=None):
        super().__init__(
            message or f"Store with name '{name}' already exists",
            code='STORE_ALREADY_EXISTS',
            status_code=409
        )


class CategoryNotFound(BaseAppException):
    """التصنيف غير موجود"""
    def __init__(self, category_id=None, message=None):
        super().__init__(
            message or f"Category {category_id} not found",
            code='CATEGORY_NOT_FOUND',
            status_code=404
        )


class CategoryAlreadyExists(BaseAppException):
    """التصنيف موجود بالفعل في المتجر"""
    def __init__(self, name=None, store_id=None, message=None):
        super().__init__(
            message or f"Category '{name}' already exists in store {store_id}",
            code='CATEGORY_ALREADY_EXISTS',
            status_code=409
        )


class ProductNotFound(BaseAppException):
    """المنتج غير موجود"""
    def __init__(self, product_id=None, message=None):
        super().__init__(
            message or f"Product {product_id} not found",
            code='PRODUCT_NOT_FOUND',
            status_code=404
        )


class ProductAlreadyExists(BaseAppException):
    """المنتج موجود بالفعل (SKU مكرر)"""
    def __init__(self, sku=None, store_id=None, message=None):
        super().__init__(
            message or f"Product with SKU '{sku}' already exists in store {store_id}",
            code='PRODUCT_ALREADY_EXISTS',
            status_code=409,
            details={'sku': sku}
        )


class InvalidSlug(BaseAppException):
    """Slug غير صحيح"""
    def __init__(self, slug=None, message=None):
        super().__init__(
            message or f"Invalid slug format: {slug}",
            code='INVALID_SLUG',
            status_code=400
        )


class SlugAlreadyTaken(BaseAppException):
    """Slug مأخوذ بالفعل"""
    def __init__(self, slug=None, message=None):
        super().__init__(
            message or f"Slug '{slug}' is already taken",
            code='SLUG_ALREADY_TAKEN',
            status_code=409
        )


# ============ Validation Exceptions ============

class ValidationError(BaseAppException):
    """خطأ في التحقق من البيانات"""
    def __init__(self, message, field=None, details=None):
        super().__init__(
            message,
            code='VALIDATION_ERROR',
            status_code=400,
            details=details or {'field': field} if field else {}
        )


class InvalidInput(BaseAppException):
    """إدخال غير صحيح"""
    def __init__(self, message, details=None):
        super().__init__(
            message,
            code='INVALID_INPUT',
            status_code=400,
            details=details or {}
        )


class MissingRequiredField(ValidationError):
    """حقل مطلوب مفقود"""
    def __init__(self, field_name):
        super().__init__(
            f"Required field '{field_name}' is missing",
            field=field_name
        )


class InvalidFileType(ValidationError):
    """نوع الملف غير صحيح"""
    def __init__(self, file_type, allowed_types=None):
        super().__init__(
            f"Invalid file type '{file_type}'. Allowed types: {allowed_types}",
            field='file',
            details={'file_type': file_type, 'allowed_types': allowed_types}
        )


class FileTooLarge(ValidationError):
    """الملف كبير جداً"""
    def __init__(self, file_size, max_size):
        super().__init__(
            f"File size {file_size}MB exceeds maximum {max_size}MB",
            field='file',
            details={'file_size': file_size, 'max_size': max_size}
        )


class PriceValidationError(ValidationError):
    """خطأ في السعر"""
    def __init__(self, message=None):
        super().__init__(
            message or "Price must be greater than 0",
            field='price'
        )


class QuantityValidationError(ValidationError):
    """خطأ في الكمية"""
    def __init__(self, message=None):
        super().__init__(
            message or "Quantity must be non-negative",
            field='quantity'
        )


# ============ Multi-Tenant Exceptions ============

class MultiTenantViolation(BaseAppException):
    """انتهاك عزل المستأجر"""
    def __init__(self, message=None, resource_type=None, resource_id=None):
        super().__init__(
            message or f"You do not have access to {resource_type} {resource_id}",
            code='MULTI_TENANT_VIOLATION',
            status_code=403,
            details={'resource_type': resource_type, 'resource_id': resource_id}
        )


class UnauthorizedAccess(BaseAppException):
    """وصول غير مصرح"""
    def __init__(self, message=None, resource=None):
        super().__init__(
            message or f"Unauthorized access to {resource}",
            code='UNAUTHORIZED_ACCESS',
            status_code=403,
            details={'resource': resource}
        )


class PermissionDenied(BaseAppException):
    """الإذن مرفوض"""
    def __init__(self, message=None, required_permission=None):
        super().__init__(
            message or f"Permission '{required_permission}' is required",
            code='PERMISSION_DENIED',
            status_code=403,
            details={'required_permission': required_permission}
        )


class ResourceOwnershipViolation(MultiTenantViolation):
    """خرق ملكية الموارد"""
    def __init__(self, user_id=None, resource_type=None, resource_id=None):
        super().__init__(
            message=f"User {user_id} does not own {resource_type} {resource_id}",
            resource_type=resource_type,
            resource_id=resource_id
        )
        self.user_id = user_id


# ============ Database Exceptions ============

class DatabaseError(BaseAppException):
    """خطأ في قاعدة البيانات"""
    def __init__(self, message=None, operation=None):
        super().__init__(
            message or f"Database error during {operation}",
            code='DATABASE_ERROR',
            status_code=500,
            details={'operation': operation}
        )


class IntegrityConstraintViolation(DatabaseError):
    """انتهاك قيد السلامة المرجعية"""
    def __init__(self, constraint=None, message=None):
        super().__init__(
            message or f"Integrity constraint violated: {constraint}",
            operation='constraint_validation'
        )


# ============ External Service Exceptions ============

class ExternalServiceError(BaseAppException):
    """خطأ في خدمة خارجية"""
    def __init__(self, service_name, message=None):
        super().__init__(
            message or f"Error from external service: {service_name}",
            code='EXTERNAL_SERVICE_ERROR',
            status_code=502,
            details={'service': service_name}
        )


class AIServiceError(ExternalServiceError):
    """خطأ في خدمة الذكاء الاصطناعي"""
    def __init__(self, message=None):
        super().__init__(
            service_name='AI Service',
            message=message or "Error from AI service"
        )


# ============ Rate Limiting & Quota Exceptions ============

class RateLimitExceeded(BaseAppException):
    """تجاوز حد الطلبات"""
    def __init__(self, retry_after=None, message=None):
        super().__init__(
            message or "Rate limit exceeded. Please try again later.",
            code='RATE_LIMIT_EXCEEDED',
            status_code=429,
            details={'retry_after': retry_after}
        )


class QuotaExceeded(BaseAppException):
    """تجاوز الحصة المسموحة"""
    def __init__(self, resource_type=None, limit=None, message=None):
        super().__init__(
            message or f"Quota exceeded for {resource_type}",
            code='QUOTA_EXCEEDED',
            status_code=429,
            details={'resource_type': resource_type, 'limit': limit}
        )

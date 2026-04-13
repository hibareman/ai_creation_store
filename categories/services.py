import logging
from django.core.exceptions import ValidationError
from django.db import transaction
from .models import Category
from . import selectors

logger = logging.getLogger(__name__)


def create_category(store, name, description="", user=None):
    """
    Create a new category for a store.
    
    Args:
        store: Store instance
        name: Category name (required, unique within store)
        description: Optional category description
        user: User creating the category (for logging)
        
    Returns:
        Created Category instance
        
    Raises:
        ValidationError: If name is empty or already exists in store
        ValidationError: If user does not own the store (MULTI-TENANT)
    """
    
    # 🔴 🔴 🔴 الإضافة الجديدة - التحقق من الصلاحيات (MULTI-TENANT)
    if user:
        # التحقق 1: tenant_id يجب أن يتطابق
        if user.tenant_id != store.tenant_id:
            logger.warning(
                f"Multi-tenant violation: User {user.id} (tenant_id: {user.tenant_id}) "
                f"attempted to create category in store {store.id} (tenant_id: {store.tenant_id})"
            )
            raise ValidationError("You do not have permission to create a category in this store")
        
        # التحقق 2: المستخدم يجب أن يكون مالك المتجر
        if user.id != store.owner_id:
            logger.warning(
                f"Ownership violation: User {user.id} attempted to create category "
                f"in store {store.id} owned by {store.owner_id}"
            )
            raise ValidationError("You must own the store to create categories")
    
    # Validation: name is required and not empty
    if not name or not name.strip():
        logger.warning(f"Category creation attempted with empty name. Store: {store.id}")
        raise ValidationError("Category name is required and cannot be empty")
    
    # Validation: name must be unique within store
    existing = selectors.get_category_by_name(store, name)
    if existing:
        logger.warning(f"Duplicate category name: {name}. Store: {store.id}")
        raise ValidationError(f"Category '{name}' already exists in this store")
    
    # Create category with tenant_id from store
    category = Category(
        store=store,
        tenant_id=store.tenant_id,
        name=name.strip(),
        description=description.strip() if description else ""
    )
    
    with transaction.atomic():
        category.save()
    
    logger.info(
        f"Category created: {category.id}. "
        f"Store: {store.id}, Tenant: {store.tenant_id}, "
        f"User: {user.id if user else 'N/A'}"
    )
    
    return category


def update_category(category, name=None, description=None, user=None):
    """
    Update an existing category.
    
    Args:
        category: Category instance to update
        name: New category name (optional)
        description: New description (optional)
        user: User updating the category (for logging)
        
    Returns:
        Updated Category instance
        
    Raises:
        ValidationError: If validation fails
        ValidationError: If user does not own the category's store (MULTI-TENANT)
    """
    
    # 🔴 🔴 🔴 الإضافة الجديدة - التحقق من الصلاحيات (MULTI-TENANT)
    if user:
        # التحقق 1: tenant_id يجب أن يتطابق
        if user.tenant_id != category.tenant_id:
            logger.warning(
                f"Multi-tenant violation: User {user.id} (tenant_id: {user.tenant_id}) "
                f"attempted to update category {category.id} (tenant_id: {category.tenant_id})"
            )
            raise ValidationError("You do not have permission to update this category")
        
        # التحقق 2: المستخدم يجب أن يكون مالك المتجر
        if user.id != category.store.owner_id:
            logger.warning(
                f"Ownership violation: User {user.id} attempted to update category {category.id} "
                f"in store {category.store.id} owned by {category.store.owner_id}"
            )
            raise ValidationError("You must own the store to update categories")
    
    updated = False
    
    # Update name if provided
    if name is not None:
        if not name or not name.strip():
            logger.warning(f"Category update attempted with empty name. Category: {category.id}")
            raise ValidationError("Category name cannot be empty")
        
        # Check for duplicates (excluding self)
        existing = Category.objects.filter(
            store=category.store,
            name=name.strip()
        ).exclude(id=category.id)
        
        if existing.exists():
            logger.warning(
                f"Duplicate name during update: {name}. "
                f"Category: {category.id}, Store: {category.store.id}"
            )
            raise ValidationError(f"Category '{name}' already exists in this store")
        
        category.name = name.strip()
        updated = True
    
    # Update description if provided
    if description is not None:
        category.description = description.strip() if description else ""
        updated = True
    
    if updated:
        with transaction.atomic():
            category.save()
        
        logger.info(
            f"Category updated: {category.id}. "
            f"Store: {category.store.id}, Tenant: {category.tenant_id}, "
            f"User: {user.id if user else 'N/A'}"
        )
    
    return category


def delete_category(category, user=None):
    """
    Delete a category safely.
    
    Args:
        category: Category instance to delete
        user: User deleting the category (for logging)
        
    Returns:
        Boolean: True if deleted successfully
        
    Raises:
        ValidationError: If category has linked products
        ValidationError: If user does not own the category's store (MULTI-TENANT)
    """
    
    # 🔴 🔴 🔴 الإضافة الجديدة - التحقق من الصلاحيات (MULTI-TENANT)
    if user:
        # التحقق 1: tenant_id يجب أن يتطابق
        if user.tenant_id != category.tenant_id:
            logger.warning(
                f"Multi-tenant violation: User {user.id} (tenant_id: {user.tenant_id}) "
                f"attempted to delete category {category.id} (tenant_id: {category.tenant_id})"
            )
            raise ValidationError("You do not have permission to delete this category")
        
        # التحقق 2: المستخدم يجب أن يكون مالك المتجر
        if user.id != category.store.owner_id:
            logger.warning(
                f"Ownership violation: User {user.id} attempted to delete category {category.id} "
                f"in store {category.store.id} owned by {category.store.owner_id}"
            )
            raise ValidationError("You must own the store to delete categories")
    
    # Check if category has linked products
    if selectors.check_category_has_products(category):
        logger.warning(
            f"Deletion attempt on category with products. "
            f"Category: {category.id}, Store: {category.store.id}"
        )
        raise ValidationError(
            "Cannot delete category with assigned products. "
            "Please reassign or remove products first."
        )
    
    category_id = category.id
    store_id = category.store.id
    tenant_id = category.tenant_id
    
    with transaction.atomic():
        category.delete()
    
    logger.info(
        f"Category deleted: {category_id}. "
        f"Store: {store_id}, Tenant: {tenant_id}, "
        f"User: {user.id if user else 'N/A'}"
    )
    
    return True
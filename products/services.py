"""
Services for Products - Business Logic Layer

MULTI-TENANT RULES STRICTLY ENFORCED:
- PROMPT: "تحقّق من ملكية الموارد: قبل UPDATE/DELETE/READ، تحقق أن resource.tenant_id == request.tenant_id"
- PROMPT: "عند إنشاء أو تعديل أي سجل، عيّن tenant_id صراحةً"
- PROMPT: "سجّل كل عمليات الوصول والكتابة مع tenant_id, user_id"
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError

from stores.models import Store
from categories.models import Category
from .models import Product, ProductImage, Inventory
from . import selectors

logger = logging.getLogger(__name__)


# ============================================================================
# PRODUCT SERVICE FUNCTIONS
# ============================================================================

def create_product(
    store: Store,
    name: str,
    price: Decimal,
    sku: str,
    description: str = '',
    category: Category = None,
    status: str = 'active'
) -> Product:
    """
    Create a new product with validation and multi-tenant isolation.
    
    MULTI-TENANT RULE: tenant_id is set from store.tenant_id
    SECURITY: Validate store ownership in caller
    """
    # Validate store has tenant_id
    if not store.tenant_id:
        logger.error(f"Cannot create product: store {store.id} has no tenant_id")
        raise ValidationError("Store has no valid tenant context")
    
    # Validate inputs
    if not name or not name.strip():
        raise ValidationError("Product name is required")
    
    if price <= 0:
        raise ValidationError("Price must be greater than 0")
    
    if not sku or not sku.strip():
        raise ValidationError("SKU is required")
    
    # Normalize SKU
    sku = sku.strip().upper()
    
    # Check SKU uniqueness per store (MULTI-TENANT CONSTRAINT)
    if Product.objects.filter(store_id=store.id, sku=sku).exists():
        raise ValidationError(f"SKU '{sku}' already exists in this store")
    
    try:
        # Create product with tenant_id
        product = Product.objects.create(
            store=store,
            tenant_id=store.tenant_id,  # MULTI-TENANT: Set explicitly
            name=name.strip(),
            description=description.strip() if description else '',
            price=price,
            sku=sku,
            category=category,
            status=status
        )
        
        # Create inventory record
        Inventory.objects.create(
            product=product,
            stock_quantity=0
        )
        
        logger.info(
            f"Product created: id={product.id}, sku={sku}, "
            f"store_id={store.id}, tenant_id={product.tenant_id}"
        )
        
        return product
    
    except Exception as e:
        logger.error(
            f"Failed to create product: {str(e)}, "
            f"store_id={store.id}, tenant_id={store.tenant_id}"
        )
        raise


def update_product(
    product: Product,
    store_id: int,
    tenant_id: int,
    **data
) -> Product:
    """
    Update product with ownership validation.
    
    MULTI-TENANT RULE: Verify product ownership before updating
    SECURITY: Caller must pass store_id and tenant_id from request context
    """
    # MULTI-TENANT: Verify ownership
    if product.store_id != store_id or product.tenant_id != tenant_id:
        logger.warning(
            f"Unauthorized product update attempt: product_id={product.id}, "
            f"attempted_tenant_id={tenant_id}, actual_tenant_id={product.tenant_id}"
        )
        raise ValidationError("Access denied: You cannot modify this product")
    
    # Update allowed fields
    allowed_fields = ['name', 'description', 'price', 'sku', 'status', 'category']
    
    for field, value in data.items():
        if field not in allowed_fields:
            continue
        
        if field == 'name' and value:
            product.name = value.strip()
        elif field == 'description' and value is not None:
            product.description = value.strip() if value else ''
        elif field == 'price' and value:
            if value <= 0:
                raise ValidationError("Price must be greater than 0")
            product.price = value
        elif field == 'sku' and value:
            sku = value.strip().upper()
            # Check uniqueness (exclude current product)
            if Product.objects.filter(
                store_id=store_id,
                sku=sku
            ).exclude(id=product.id).exists():
                raise ValidationError(f"SKU '{sku}' already exists in this store")
            product.sku = sku
        elif field == 'status' and value:
            if value in ['active', 'inactive']:
                product.status = value
        elif field == 'category':
            # Verify category belongs to same store
            if value:
                if value.store_id != store_id:
                    raise ValidationError("Category does not belong to this store")
            product.category = value
    
    try:
        product.save()
        logger.info(
            f"Product updated: id={product.id}, sku={product.sku}, "
            f"store_id={store_id}, tenant_id={tenant_id}"
        )
        return product
    
    except Exception as e:
        logger.error(
            f"Failed to update product: {str(e)}, "
            f"product_id={product.id}, tenant_id={tenant_id}"
        )
        raise


def delete_product(product: Product, store_id: int, tenant_id: int) -> None:
    """
    Delete product with ownership validation.
    
    MULTI-TENANT RULE: Verify ownership before deletion
    """
    # MULTI-TENANT: Verify ownership
    if product.store_id != store_id or product.tenant_id != tenant_id:
        logger.warning(
            f"Unauthorized product deletion attempt: product_id={product.id}, "
            f"attempted_tenant_id={tenant_id}, actual_tenant_id={product.tenant_id}"
        )
        raise ValidationError("Access denied: You cannot delete this product")
    
    try:
        product_sku = product.sku
        product_id = product.id
        product.delete()
        
        logger.info(
            f"Product deleted: id={product_id}, sku={product_sku}, "
            f"store_id={store_id}, tenant_id={tenant_id}"
        )
    
    except Exception as e:
        logger.error(
            f"Failed to delete product: {str(e)}, "
            f"product_id={product.id}, tenant_id={tenant_id}"
        )
        raise


# ============================================================================
# INVENTORY SERVICE FUNCTIONS
# ============================================================================

def update_inventory(
    product: Product,
    store_id: int,
    tenant_id: int,
    stock_quantity: int
) -> Inventory:
    """
    Update product inventory with ownership validation.
    
    MULTI-TENANT RULE: Verify product ownership before updating
    """
    # MULTI-TENANT: Verify ownership
    if product.store_id != store_id or product.tenant_id != tenant_id:
        logger.warning(
            f"Unauthorized inventory update attempt: product_id={product.id}, "
            f"attempted_tenant_id={tenant_id}, actual_tenant_id={product.tenant_id}"
        )
        raise ValidationError("Access denied: You cannot modify this product")
    
    if stock_quantity < 0:
        raise ValidationError("Stock quantity cannot be negative")
    
    try:
        inventory = product.inventory
        old_quantity = inventory.stock_quantity
        inventory.stock_quantity = stock_quantity
        inventory.save()
        
        logger.info(
            f"Inventory updated: product_id={product.id}, "
            f"old_quantity={old_quantity}, new_quantity={stock_quantity}, "
            f"store_id={store_id}, tenant_id={tenant_id}"
        )
        
        return inventory
    
    except Exception as e:
        logger.error(
            f"Failed to update inventory: {str(e)}, "
            f"product_id={product.id}, tenant_id={tenant_id}"
        )
        raise


# ============================================================================
# PRODUCT IMAGE SERVICE FUNCTIONS
# ============================================================================

def add_product_image(
    product: Product,
    store_id: int,
    tenant_id: int,
    image_url: str = None,
    image_file=None
) -> ProductImage:
    """
    Add an image to a product with ownership validation.
    
    MULTI-TENANT RULE: Verify product ownership before adding image
    """
    # MULTI-TENANT: Verify ownership
    if product.store_id != store_id or product.tenant_id != tenant_id:
        logger.warning(
            f"Unauthorized image upload attempt: product_id={product.id}, "
            f"attempted_tenant_id={tenant_id}, actual_tenant_id={product.tenant_id}"
        )
        raise ValidationError("Access denied: You cannot modify this product")
    
    image_url = image_url.strip() if image_url else ''
    if not image_url and not image_file:
        raise ValidationError("Image file or image URL is required")
    
    try:
        product_image = ProductImage.objects.create(
            product=product,
            image_url=image_url,
            image_file=image_file
        )
        
        logger.info(
            f"Product image added: product_id={product.id}, "
            f"image_id={product_image.id}, store_id={store_id}, tenant_id={tenant_id}"
        )
        
        return product_image
    
    except Exception as e:
        logger.error(
            f"Failed to add product image: {str(e)}, "
            f"product_id={product.id}, tenant_id={tenant_id}"
        )
        raise


def delete_product_image(
    product_image: ProductImage,
    store_id: int,
    tenant_id: int
) -> None:
    """
    Delete a product image with ownership validation.
    
    MULTI-TENANT RULE: Verify product ownership before deleting image
    """
    # MULTI-TENANT: Verify product ownership
    if (product_image.product.store_id != store_id or
        product_image.product.tenant_id != tenant_id):
        
        logger.warning(
            f"Unauthorized image deletion attempt: image_id={product_image.id}, "
            f"product_id={product_image.product_id}, "
            f"attempted_tenant_id={tenant_id}, "
            f"actual_tenant_id={product_image.product.tenant_id}"
        )
        raise ValidationError("Access denied: You cannot delete this image")
    
    try:
        image_id = product_image.id
        product_id = product_image.product_id
        product_image.delete()
        
        logger.info(
            f"Product image deleted: image_id={image_id}, "
            f"product_id={product_id}, store_id={store_id}, tenant_id={tenant_id}"
        )
    
    except Exception as e:
        logger.error(
            f"Failed to delete product image: {str(e)}, "
            f"image_id={product_image.id}, tenant_id={tenant_id}"
        )
        raise

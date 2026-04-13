"""
Services for Products - Business Logic Layer

MULTI-TENANT RULES STRICTLY ENFORCED:
- PROMPT: "طھط­ظ‚ظ‘ظ‚ ظ…ظ† ظ…ظ„ظƒظٹط© ط§ظ„ظ…ظˆط§ط±ط¯: ظ‚ط¨ظ„ UPDATE/DELETE/READطŒ طھط­ظ‚ظ‚ ط£ظ† resource.tenant_id == request.tenant_id"
- PROMPT: "ط¹ظ†ط¯ ط¥ظ†ط´ط§ط، ط£ظˆ طھط¹ط¯ظٹظ„ ط£ظٹ ط³ط¬ظ„طŒ ط¹ظٹظ‘ظ† tenant_id طµط±ط§ط­ط©ظ‹"
- PROMPT: "ط³ط¬ظ‘ظ„ ظƒظ„ ط¹ظ…ظ„ظٹط§طھ ط§ظ„ظˆطµظˆظ„ ظˆط§ظ„ظƒطھط§ط¨ط© ظ…ط¹ tenant_id, user_id"
"""

import logging
from decimal import Decimal
from django.core.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied

from stores.models import Store
from categories.models import Category
from .models import Product, ProductImage, Inventory

logger = logging.getLogger(__name__)


# ============================================================================
# PRODUCT SERVICE FUNCTIONS
# ============================================================================

def _validate_store_authorization(user, store: Store):
    """
    Defense-in-depth authorization check for store-scoped operations.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        raise PermissionDenied("Authentication required")

    if user.tenant_id != store.tenant_id:
        logger.warning(
            f"Multi-tenant violation: user_id={user.id}, user_tenant_id={user.tenant_id}, "
            f"store_id={store.id}, store_tenant_id={store.tenant_id}"
        )
        raise PermissionDenied("You do not have access to this store")

    if user.id != store.owner_id:
        logger.warning(
            f"Ownership violation: user_id={user.id}, store_id={store.id}, store_owner_id={store.owner_id}"
        )
        raise PermissionDenied("You do not own this store")


def create_product(
    user,
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
    """
    _validate_store_authorization(user, store)

    if not store.tenant_id:
        logger.error(f"Cannot create product: store {store.id} has no tenant_id")
        raise ValidationError("Store has no valid tenant context")

    if not name or not name.strip():
        raise ValidationError("Product name is required")

    if price <= 0:
        raise ValidationError("Price must be greater than 0")

    if not sku or not sku.strip():
        raise ValidationError("SKU is required")

    sku = sku.strip().upper()

    if Product.objects.filter(store_id=store.id, sku=sku).exists():
        raise ValidationError(f"SKU '{sku}' already exists in this store")

    if category is not None:
        if category.store_id != store.id or category.tenant_id != store.tenant_id:
            raise ValidationError("Category does not belong to this store")

    try:
        product = Product.objects.create(
            store=store,
            tenant_id=store.tenant_id,
            name=name.strip(),
            description=description.strip() if description else '',
            price=price,
            sku=sku,
            category=category,
            status=status
        )

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
    user,
    store: Store,
    product: Product,
    **data
) -> Product:
    """
    Update product with ownership validation.
    """
    _validate_store_authorization(user, store)

    if product.store_id != store.id or product.tenant_id != store.tenant_id:
        logger.warning(
            f"Unauthorized product update attempt: product_id={product.id}, "
            f"store_id={store.id}, store_tenant_id={store.tenant_id}, "
            f"product_store_id={product.store_id}, product_tenant_id={product.tenant_id}"
        )
        raise PermissionDenied("You cannot modify this product")

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
            if Product.objects.filter(
                store_id=store.id,
                sku=sku
            ).exclude(id=product.id).exists():
                raise ValidationError(f"SKU '{sku}' already exists in this store")
            product.sku = sku
        elif field == 'status' and value:
            if value in ['active', 'inactive']:
                product.status = value
        elif field == 'category':
            if value and (value.store_id != store.id or value.tenant_id != store.tenant_id):
                raise ValidationError("Category does not belong to this store")
            product.category = value

    try:
        product.save()
        logger.info(
            f"Product updated: id={product.id}, sku={product.sku}, "
            f"store_id={store.id}, tenant_id={store.tenant_id}"
        )
        return product

    except Exception as e:
        logger.error(
            f"Failed to update product: {str(e)}, "
            f"product_id={product.id}, tenant_id={store.tenant_id}"
        )
        raise


def delete_product(user, store: Store, product: Product) -> None:
    """
    Delete product with ownership validation.
    """
    _validate_store_authorization(user, store)

    if product.store_id != store.id or product.tenant_id != store.tenant_id:
        logger.warning(
            f"Unauthorized product deletion attempt: product_id={product.id}, "
            f"store_id={store.id}, store_tenant_id={store.tenant_id}, "
            f"product_store_id={product.store_id}, product_tenant_id={product.tenant_id}"
        )
        raise PermissionDenied("You cannot delete this product")

    try:
        product_sku = product.sku
        product_id = product.id
        product.delete()

        logger.info(
            f"Product deleted: id={product_id}, sku={product_sku}, "
            f"store_id={store.id}, tenant_id={store.tenant_id}"
        )

    except Exception as e:
        logger.error(
            f"Failed to delete product: {str(e)}, "
            f"product_id={product.id}, tenant_id={store.tenant_id}"
        )
        raise


# ============================================================================
# INVENTORY SERVICE FUNCTIONS
# ============================================================================

def update_inventory(
    user,
    store: Store,
    product: Product,
    stock_quantity: int
) -> Inventory:
    """
    Update product inventory with ownership validation.
    """
    _validate_store_authorization(user, store)

    if product.store_id != store.id or product.tenant_id != store.tenant_id:
        logger.warning(
            f"Unauthorized inventory update attempt: product_id={product.id}, "
            f"store_id={store.id}, store_tenant_id={store.tenant_id}, "
            f"product_store_id={product.store_id}, product_tenant_id={product.tenant_id}"
        )
        raise PermissionDenied("You cannot modify this product")

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
            f"store_id={store.id}, tenant_id={store.tenant_id}"
        )

        return inventory

    except Exception as e:
        logger.error(
            f"Failed to update inventory: {str(e)}, "
            f"product_id={product.id}, tenant_id={store.tenant_id}"
        )
        raise


# ============================================================================
# PRODUCT IMAGE SERVICE FUNCTIONS
# ============================================================================

def add_product_image(
    user,
    store: Store,
    product: Product,
    image_url: str = None,
    image_file=None
) -> ProductImage:
    """
    Add an image to a product with ownership validation.
    """
    _validate_store_authorization(user, store)

    if product.store_id != store.id or product.tenant_id != store.tenant_id:
        logger.warning(
            f"Unauthorized image upload attempt: product_id={product.id}, "
            f"store_id={store.id}, store_tenant_id={store.tenant_id}, "
            f"product_store_id={product.store_id}, product_tenant_id={product.tenant_id}"
        )
        raise PermissionDenied("You cannot modify this product")

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
            f"image_id={product_image.id}, store_id={store.id}, tenant_id={store.tenant_id}"
        )

        return product_image

    except Exception as e:
        logger.error(
            f"Failed to add product image: {str(e)}, "
            f"product_id={product.id}, tenant_id={store.tenant_id}"
        )
        raise


def delete_product_image(
    user,
    store: Store,
    product_image: ProductImage
) -> None:
    """
    Delete a product image with ownership validation.
    """
    _validate_store_authorization(user, store)

    if (product_image.product.store_id != store.id or
        product_image.product.tenant_id != store.tenant_id):
        logger.warning(
            f"Unauthorized image deletion attempt: image_id={product_image.id}, "
            f"product_id={product_image.product_id}, store_id={store.id}, "
            f"store_tenant_id={store.tenant_id}, product_store_id={product_image.product.store_id}, "
            f"product_tenant_id={product_image.product.tenant_id}"
        )
        raise PermissionDenied("You cannot delete this image")

    try:
        image_id = product_image.id
        product_id = product_image.product_id
        product_image.delete()

        logger.info(
            f"Product image deleted: image_id={image_id}, "
            f"product_id={product_id}, store_id={store.id}, tenant_id={store.tenant_id}"
        )

    except Exception as e:
        logger.error(
            f"Failed to delete product image: {str(e)}, "
            f"image_id={product_image.id}, tenant_id={store.tenant_id}"
        )
        raise

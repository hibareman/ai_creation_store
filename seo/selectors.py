from categories.models import Category
from products.models import Product
from products.selectors import get_public_product_detail
from stores.models import Store
from stores.selectors import get_public_store_by_subdomain

from .models import CategorySEO, ProductSEO, StoreSEO


def get_store_seo_by_store(store):
    return StoreSEO.objects.filter(store=store).first()


def get_product_seo_by_product(product):
    return ProductSEO.objects.filter(product=product).first()


def get_category_seo_by_category(category):
    return CategorySEO.objects.filter(category=category).first()


def get_public_store_seo_by_subdomain(subdomain):
    store = get_public_store_by_subdomain(subdomain)
    if not store:
        return None
    return get_store_seo_by_store(store)


def get_public_product_seo(store, product_id):
    product = get_public_product_detail(store, product_id)
    if not product:
        return None
    return get_product_seo_by_product(product)


def get_owner_store_for_seo(store_id, tenant_id, user_id=None):
    # user_id intentionally unused for lookup to preserve 403 for same-tenant non-owner.
    return Store.objects.filter(id=store_id, tenant_id=tenant_id).select_related("owner").first()


def get_owner_product_for_seo(store_id, product_id, tenant_id):
    return (
        Product.objects.filter(
            id=product_id,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .select_related("store", "category")
        .first()
    )


def get_owner_category_for_seo(store_id, category_id, tenant_id):
    return (
        Category.objects.filter(
            id=category_id,
            store_id=store_id,
            tenant_id=tenant_id,
        )
        .select_related("store")
        .first()
    )

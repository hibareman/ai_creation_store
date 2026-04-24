from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from products.selectors import get_public_product_detail
from stores.selectors import get_public_store_by_subdomain

from .models import CategorySEO, ProductSEO, StoreSEO
from .selectors import (
    get_category_seo_by_category,
    get_product_seo_by_product,
    get_public_product_seo,
    get_public_store_seo_by_subdomain,
    get_store_seo_by_store,
)


SEO_FIELD_MAP = {
    "metaTitle": "meta_title",
    "metaDescription": "meta_description",
    "metaKeywords": "meta_keywords",
    "ogTitle": "og_title",
    "ogDescription": "og_description",
    "ogImageUrl": "og_image_url",
    "canonicalUrl": "canonical_url",
}


def validate_owner_store_access(store, user):
    if user is None:
        return

    if getattr(user, "tenant_id", None) != store.tenant_id:
        raise PermissionDenied("You do not have access to this store")

    if getattr(user, "id", None) != store.owner_id:
        raise PermissionDenied("You do not own this store")


def build_store_seo_payload(store, seo_obj=None):
    meta_title = (getattr(seo_obj, "meta_title", "") or store.name or "")
    meta_description = (getattr(seo_obj, "meta_description", "") or store.description or "")

    return {
        "metaTitle": meta_title,
        "metaDescription": meta_description,
        "metaKeywords": getattr(seo_obj, "meta_keywords", "") or "",
        "ogTitle": (getattr(seo_obj, "og_title", "") or meta_title or store.name or ""),
        "ogDescription": (getattr(seo_obj, "og_description", "") or meta_description or store.description or ""),
        "ogImageUrl": getattr(seo_obj, "og_image_url", "") or "",
        "canonicalUrl": getattr(seo_obj, "canonical_url", "") or "",
    }


def build_product_seo_payload(product, seo_obj=None):
    meta_title = (getattr(seo_obj, "meta_title", "") or product.name or "")
    meta_description = (getattr(seo_obj, "meta_description", "") or product.description or "")

    return {
        "metaTitle": meta_title,
        "metaDescription": meta_description,
        "metaKeywords": getattr(seo_obj, "meta_keywords", "") or "",
        "ogTitle": (getattr(seo_obj, "og_title", "") or meta_title or product.name or ""),
        "ogDescription": (getattr(seo_obj, "og_description", "") or meta_description or product.description or ""),
        "ogImageUrl": getattr(seo_obj, "og_image_url", "") or "",
        "canonicalUrl": getattr(seo_obj, "canonical_url", "") or "",
    }


def build_category_seo_payload(category, seo_obj=None):
    category_description = getattr(category, "description", "") or ""
    meta_title = (getattr(seo_obj, "meta_title", "") or category.name or "")
    meta_description = (getattr(seo_obj, "meta_description", "") or category_description)

    return {
        "metaTitle": meta_title,
        "metaDescription": meta_description,
        "metaKeywords": getattr(seo_obj, "meta_keywords", "") or "",
        "ogTitle": (getattr(seo_obj, "og_title", "") or meta_title or category.name or ""),
        "ogDescription": (getattr(seo_obj, "og_description", "") or meta_description or category_description),
        "ogImageUrl": getattr(seo_obj, "og_image_url", "") or "",
        "canonicalUrl": getattr(seo_obj, "canonical_url", "") or "",
    }


def _update_seo_instance(seo_obj, seo_data):
    updated_fields = []

    for payload_key, model_field in SEO_FIELD_MAP.items():
        if payload_key not in seo_data:
            continue

        new_value = seo_data[payload_key]
        old_value = getattr(seo_obj, model_field)
        if old_value != new_value:
            setattr(seo_obj, model_field, new_value)
            updated_fields.append(model_field)

    if updated_fields:
        seo_obj.save(update_fields=list(set(updated_fields + ["updated_at"])))


def get_owner_store_seo_payload(store, user=None):
    validate_owner_store_access(store, user)
    seo_obj = get_store_seo_by_store(store)

    return {
        "store_id": store.id,
        "seo": build_store_seo_payload(store, seo_obj=seo_obj),
    }


def update_owner_store_seo(store, seo_data, user=None):
    validate_owner_store_access(store, user)

    with transaction.atomic():
        seo_obj, _ = StoreSEO.objects.get_or_create(store=store)
        _update_seo_instance(seo_obj, seo_data)

    return get_owner_store_seo_payload(store, user=user)


def get_owner_product_seo_payload(store, product, user=None):
    validate_owner_store_access(store, user)

    if product.store_id != store.id:
        raise NotFound("Product not found")

    seo_obj = get_product_seo_by_product(product)
    return {
        "product_id": product.id,
        "store_id": store.id,
        "seo": build_product_seo_payload(product, seo_obj=seo_obj),
    }


def update_owner_product_seo(store, product, seo_data, user=None):
    validate_owner_store_access(store, user)

    if product.store_id != store.id:
        raise NotFound("Product not found")

    with transaction.atomic():
        seo_obj, _ = ProductSEO.objects.get_or_create(product=product)
        _update_seo_instance(seo_obj, seo_data)

    return get_owner_product_seo_payload(store, product, user=user)


def get_owner_category_seo_payload(store, category, user=None):
    validate_owner_store_access(store, user)

    if category.store_id != store.id:
        raise NotFound("Category not found")

    seo_obj = get_category_seo_by_category(category)
    return {
        "category_id": category.id,
        "store_id": store.id,
        "seo": build_category_seo_payload(category, seo_obj=seo_obj),
    }


def update_owner_category_seo(store, category, seo_data, user=None):
    validate_owner_store_access(store, user)

    if category.store_id != store.id:
        raise NotFound("Category not found")

    with transaction.atomic():
        seo_obj, _ = CategorySEO.objects.get_or_create(category=category)
        _update_seo_instance(seo_obj, seo_data)

    return get_owner_category_seo_payload(store, category, user=user)


def get_public_store_seo_payload(subdomain):
    store = get_public_store_by_subdomain(subdomain)
    if not store:
        raise NotFound("Store not found")

    seo_obj = get_public_store_seo_by_subdomain(subdomain)
    return {
        "store_id": store.id,
        "seo": build_store_seo_payload(store, seo_obj=seo_obj),
    }


def get_public_product_seo_payload(subdomain, product_id):
    store = get_public_store_by_subdomain(subdomain)
    if not store:
        raise NotFound("Store not found")

    product = get_public_product_detail(store, product_id)
    if not product:
        raise NotFound("Product not found")

    seo_obj = get_public_product_seo(store, product_id)
    return {
        "product_id": product.id,
        "store_id": store.id,
        "seo": build_product_seo_payload(product, seo_obj=seo_obj),
    }

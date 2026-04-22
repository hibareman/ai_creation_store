import logging
from django.db import DatabaseError, IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from .models import Store, StoreSettings, StoreDomain
from products.selectors import count_active_products_for_store
from .selectors import is_subdomain_available

logger = logging.getLogger(__name__)

def create_store(owner, name, description="", status="setup", slug=None):
    """
    Create a new store for the given owner.
    The store inherits the owner's tenant_id.
    Automatically creates StoreSettings with default values.
    
    Args:
        owner: The user who owns the store
        name: Store name
        description: Store description
        status: Store status (default: 'setup')
        slug: Optional custom slug for the store
    
    Returns:
        Store instance if created successfully, None if failed
    
    Raises:
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        store = Store(
            owner=owner,
            name=name,
            description=description,
            status=status,
            tenant_id=getattr(owner, 'tenant_id', None),
            slug=slug
        )
        store.save()
        
        # Create StoreSettings automatically with default values
        try:
            StoreSettings.objects.create(store=store)
        except DatabaseError as e:
            logger.error(f"Failed to create StoreSettings for store '{name}' (id: {store.id}): {str(e)}")
            raise
        
        logger.info(f"Store '{name}' created successfully by user '{owner.username}' (user_id: {owner.id}, tenant_id: {store.tenant_id})")
        return store
    
    except DatabaseError as e:
        logger.error(f"Database error while creating store '{name}' for user '{owner.username}': {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while creating store '{name}' for user '{owner.username}': {str(e)}")
        raise


def is_slug_available(slug, store_id=None):
    """Return True if the slug is available for use."""
    query = Store.objects.filter(slug=slug)
    if store_id:
        query = query.exclude(id=store_id)
    return not query.exists()


def suggest_slugs(name, limit=5, store_id=None):
    """Suggest available slugs based on a store name."""
    base_slug = slugify(name)
    suggestions = []
    counter = 0

    while len(suggestions) < limit:
        candidate = base_slug if counter == 0 else f"{base_slug}-{counter}"
        query = Store.objects.filter(slug=candidate)
        if store_id:
            query = query.exclude(id=store_id)

        if not query.exists():
            suggestions.append(candidate)

        counter += 1
        if counter > limit * 10:
            break

    return suggestions


def validate_store_access(store, user):
    if getattr(user, 'tenant_id', None) != store.tenant_id:
        raise ValidationError("You do not have access to this store")

    if getattr(user, 'id', None) != store.owner_id:
        raise ValidationError("You do not have access to this store")


def set_store_subdomain(store, subdomain, user=None):
    """
    Set and persist a globally unique subdomain for a store.

    Rules:
    - Normalize input (strip, lowercase, slugify)
    - Enforce global uniqueness excluding current store
    - Enforce tenant + ownership checks when user is provided
    """
    if user is not None:
        validate_store_access(store, user)

    normalized_subdomain = slugify((subdomain or '').strip().lower())
    if not normalized_subdomain:
        raise ValidationError("Invalid subdomain")

    if not is_subdomain_available(normalized_subdomain, store_id=store.id):
        raise ValidationError("Subdomain is already taken")

    store.subdomain = normalized_subdomain
    try:
        store.save(update_fields=['subdomain'])
    except IntegrityError:
        raise ValidationError("Subdomain is already taken")

    logger.info(
        f"Store '{store.name}' (id: {store.id}, tenant_id: {store.tenant_id}) "
        f"subdomain set to '{store.subdomain}'"
    )
    return store


def update_store(store, **kwargs):
    """
    Update store fields. Allowed fields: name, slug, description, status
    
    Args:
        store: Store instance to update
        **kwargs: Fields to update (name, description, status)
    
    Returns:
        Updated Store instance if successful, None if failed
    
    Raises:
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        # Track which fields are being updated
        updated_fields = []
        
        for field in ['name', 'slug', 'description', 'status']:
            if field in kwargs:
                old_value = getattr(store, field)
                new_value = kwargs[field]
                if old_value != new_value:
                    setattr(store, field, new_value)
                    updated_fields.append(f"{field}: '{old_value}' -> '{new_value}'")
        
        if updated_fields:
            store.save()
            logger.info(f"Store '{store.name}' (id: {store.id}, tenant_id: {store.tenant_id}) updated: {', '.join(updated_fields)}")
        else:
            logger.debug(f"No changes to store '{store.name}' (id: {store.id})")
        
        return store
    
    except DatabaseError as e:
        logger.error(f"Database error while updating store '{store.name}' (id: {store.id}): {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while updating store '{store.name}' (id: {store.id}): {str(e)}")
        raise


def update_store_settings(store, user=None, **kwargs):
    """
    Update store-level settings while preserving tenant/owner isolation.
    Supports updating fields on both Store and StoreSettings.

    Supported payload keys:
    - Store fields: storeName, storeUrl, storeDescription
    - StoreSettings fields: storeEmail, storePhone, currency, language, timezone,
      emailNotifications, orderNotifications, marketingNotifications, twoFactorAuth
    """
    if user is not None:
        try:
            validate_store_access(store, user)
        except ValidationError:
            if (
                getattr(user, 'tenant_id', None) == store.tenant_id and
                getattr(user, 'id', None) != store.owner_id
            ):
                raise ValidationError("You must own the store to update settings")
            raise

    try:
        settings, _created = StoreSettings.objects.get_or_create(store=store)

        store_updated_fields = []
        settings_updated_fields = []

        if 'storeName' in kwargs:
            new_name = str(kwargs['storeName']).strip()
            if not new_name:
                raise ValidationError("storeName cannot be empty")
            if store.name != new_name:
                store.name = new_name
                store_updated_fields.append('name')

        if 'storeUrl' in kwargs:
            normalized_slug = slugify(str(kwargs['storeUrl']).strip().lower())
            if not normalized_slug:
                raise ValidationError("storeUrl is invalid")

            slug_exists = Store.objects.filter(slug=normalized_slug).exclude(id=store.id).exists()
            if slug_exists:
                raise ValidationError("storeUrl is already taken")

            if store.slug != normalized_slug:
                store.slug = normalized_slug
                store_updated_fields.append('slug')

        if 'storeDescription' in kwargs:
            new_description = str(kwargs['storeDescription']).strip()
            if store.description != new_description:
                store.description = new_description
                store_updated_fields.append('description')

        settings_field_map = {
            'storeEmail': 'store_email',
            'storePhone': 'store_phone',
            'currency': 'currency',
            'language': 'language',
            'timezone': 'timezone',
            'emailNotifications': 'email_notifications',
            'orderNotifications': 'order_notifications',
            'marketingNotifications': 'marketing_notifications',
            'twoFactorAuth': 'two_factor_auth',
        }

        for payload_key, model_field in settings_field_map.items():
            if payload_key not in kwargs:
                continue

            new_value = kwargs[payload_key]
            old_value = getattr(settings, model_field)
            if old_value != new_value:
                setattr(settings, model_field, new_value)
                settings_updated_fields.append(model_field)

        with transaction.atomic():
            if store_updated_fields:
                store.save(update_fields=list(set(store_updated_fields + ['updated_at'])))

            if settings_updated_fields:
                settings.save(update_fields=list(set(settings_updated_fields + ['updated_at'])))

        if store_updated_fields or settings_updated_fields:
            logger.info(
                f"Store settings updated for store '{store.name}' (id: {store.id}, tenant_id: {store.tenant_id}). "
                f"Store fields: {store_updated_fields or []}, Settings fields: {settings_updated_fields or []}"
            )
        else:
            logger.debug(f"No changes to StoreSettings for store '{store.name}' (id: {store.id})")

        return settings

    except DatabaseError as e:
        logger.error(f"Database error while updating settings for store '{store.name}' (id: {store.id}): {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while updating settings for store '{store.name}' (id: {store.id}): {str(e)}")
        raise
def add_domain(store, domain, is_primary=False):
    """
    Add a new domain to a store.
    
    Args:
        store: Store instance
        domain: Domain name (e.g., 'myshop.com')
        is_primary: Whether this is the primary domain (default: False)
    
    Returns:
        Created StoreDomain instance
    
    Raises:
        IntegrityError: If domain already exists (unique constraint)
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        # If making this domain primary, unset other primary domains
        if is_primary:
            StoreDomain.objects.filter(store=store, is_primary=True).update(is_primary=False)
        
        domain_obj = StoreDomain.objects.create(
            store=store,
            domain=domain,
            is_primary=is_primary
        )
        
        logger.info(f"Domain '{domain}' added to store '{store.name}' (id: {store.id}), is_primary={is_primary}")
        return domain_obj
    
    except Exception as e:
        logger.error(f"Error adding domain '{domain}' to store '{store.name}' (id: {store.id}): {str(e)}")
        raise


def update_domain(store, domain, is_primary=False, new_domain=None):
    """
    Update a domain for a store.
    
    Args:
        store: Store instance
        domain: Current domain name to update
        is_primary: Whether to set this as primary domain
        new_domain: Optional new domain value (if changing domain string)
    
    Returns:
        Updated StoreDomain instance
    
    Raises:
        StoreDomain.DoesNotExist: If domain not found for this store
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        domain_obj = StoreDomain.objects.get(store=store, domain=domain)

        target_domain = new_domain if new_domain is not None else domain
        old_primary = domain_obj.is_primary
        if domain_obj.domain != target_domain:
            domain_obj.domain = target_domain
        domain_obj.is_primary = is_primary
        
        # If making this domain primary, unset other primary domains
        if is_primary and not old_primary:
            StoreDomain.objects.filter(store=store, is_primary=True).exclude(id=domain_obj.id).update(is_primary=False)
        
        domain_obj.save()
        
        logger.info(
            f"Domain '{domain}' updated to '{domain_obj.domain}' in store '{store.name}' "
            f"(id: {store.id}), is_primary={is_primary}"
        )
        return domain_obj
    
    except StoreDomain.DoesNotExist:
        logger.warning(f"Domain '{domain}' not found for store '{store.name}' (id: {store.id})")
        raise
    except DatabaseError as e:
        logger.error(f"Database error while updating domain '{domain}' in store '{store.name}' (id: {store.id}): {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while updating domain '{domain}' in store '{store.name}' (id: {store.id}): {str(e)}")
        raise


def delete_domain(store, domain):
    """
    Delete a domain from a store.
    
    Args:
        store: Store instance
        domain: Domain name to delete
    
    Returns:
        True if deleted successfully
    
    Raises:
        StoreDomain.DoesNotExist: If domain not found for this store
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        domain_obj = StoreDomain.objects.get(store=store, domain=domain)
        domain_obj_id = domain_obj.id
        domain_obj.delete()
        
        logger.info(f"Domain '{domain}' deleted from store '{store.name}' (id: {store.id})")
        return True
    
    except StoreDomain.DoesNotExist:
        logger.warning(f"Domain '{domain}' not found for store '{store.name}' (id: {store.id})")
        raise
    except DatabaseError as e:
        logger.error(f"Database error while deleting domain '{domain}' from store '{store.name}' (id: {store.id}): {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while deleting domain '{domain}' from store '{store.name}' (id: {store.id}): {str(e)}")
        raise


def get_store_domains(store):
    """
    Get all domains for a store.
    
    Args:
        store: Store instance
    
    Returns:
        QuerySet of StoreDomain objects
    """
    return StoreDomain.objects.filter(store=store).order_by('-is_primary', 'domain')


def evaluate_store_publish_readiness(store, user=None):
    """
    Evaluate whether a store is ready to be published.

    Returns:
        dict with:
        - is_ready: bool
        - errors: list[str]
        - checks: dict
    """
    errors = []

    has_valid_name = bool((store.name or '').strip())
    has_subdomain = bool((store.subdomain or '').strip())
    is_active_status = store.status == 'active'

    active_products_count = 0
    if store.id and store.tenant_id is not None:
        active_products_count = count_active_products_for_store(
            store_id=store.id,
            tenant_id=store.tenant_id
        )
    has_active_products = active_products_count > 0

    tenant_match = None
    ownership_match = None
    if user is not None:
        tenant_match = getattr(user, 'tenant_id', None) == store.tenant_id
        ownership_match = getattr(user, 'id', None) == store.owner_id

    if not has_valid_name:
        errors.append("Store name is required before publishing.")
    if not has_subdomain:
        errors.append("Store subdomain is required before publishing.")
    if not is_active_status:
        errors.append("Store status must be 'active' before publishing.")
    if not has_active_products:
        errors.append("At least one active product is required before publishing.")

    if user is not None:
        if not tenant_match:
            errors.append("You do not have access to this store.")
        if not ownership_match:
            errors.append("You must own this store to publish it.")

    checks = {
        'has_valid_name': has_valid_name,
        'has_subdomain': has_subdomain,
        'is_active_status': is_active_status,
        'active_products_count': active_products_count,
        'has_active_products': has_active_products,
        'tenant_match': tenant_match,
        'ownership_match': ownership_match,
    }

    return {
        'is_ready': len(errors) == 0,
        'errors': errors,
        'checks': checks,
    }


def publish_store(store, user=None):
    """
    Publish a store after validating access and readiness.
    """
    if user is not None:
        validate_store_access(store, user)

    readiness = evaluate_store_publish_readiness(store, user=user)
    if not readiness['is_ready']:
        raise ValidationError(readiness['errors'])

    store.is_published = True
    store.published_at = timezone.now()
    try:
        store.save(update_fields=['is_published', 'published_at'])
    except IntegrityError:
        raise ValidationError("Failed to publish store due to a data conflict")
    return store


def unpublish_store(store, user=None):
    """
    Unpublish a store after validating access.
    """
    if user is not None:
        validate_store_access(store, user)

    store.is_published = False
    store.published_at = None
    try:
        store.save(update_fields=['is_published', 'published_at'])
    except IntegrityError:
        raise ValidationError("Failed to unpublish store due to a data conflict")
    return store


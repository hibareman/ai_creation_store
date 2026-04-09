import logging
from django.db import DatabaseError
from django.utils.text import slugify
from .models import Store, StoreSettings, StoreDomain

logger = logging.getLogger(__name__)

def create_store(owner, name, description="", status="active", slug=None):
    """
    Create a new store for the given owner.
    The store inherits the owner's tenant_id.
    Automatically creates StoreSettings with default values.
    
    Args:
        owner: The user who owns the store
        name: Store name
        description: Store description
        status: Store status (default: 'active')
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


def update_store(store, **kwargs):
    """
    Update store fields. Allowed fields: name, description, status
    
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
        
        for field in ['name', 'description', 'status']:
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


def update_store_settings(store, **kwargs):
    """
    Update StoreSettings for a given store.
    Allowed fields: currency, language, timezone
    
    Args:
        store: Store instance
        **kwargs: Settings fields to update (currency, language, timezone)
    
    Returns:
        Updated StoreSettings instance
    
    Raises:
        StoreSettings.DoesNotExist: If store has no settings (shouldn't happen)
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        settings = store.settings
        updated_fields = []
        
        for field in ['currency', 'language', 'timezone']:
            if field in kwargs:
                old_value = getattr(settings, field)
                new_value = kwargs[field]
                if old_value != new_value:
                    setattr(settings, field, new_value)
                    updated_fields.append(f"{field}: '{old_value}' -> '{new_value}'")
        
        if updated_fields:
            settings.save()
            logger.info(f"StoreSettings for store '{store.name}' (id: {store.id}) updated: {', '.join(updated_fields)}")
        else:
            logger.debug(f"No changes to StoreSettings for store '{store.name}' (id: {store.id})")
        
        return settings
    
    except StoreSettings.DoesNotExist:
        logger.error(f"StoreSettings not found for store '{store.name}' (id: {store.id})")
        raise
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


def update_domain(store, domain, is_primary=False):
    """
    Update a domain for a store.
    
    Args:
        store: Store instance
        domain: Domain name to update
        is_primary: Whether to set this as primary domain
    
    Returns:
        Updated StoreDomain instance
    
    Raises:
        StoreDomain.DoesNotExist: If domain not found for this store
        DatabaseError: If database operation fails (re-raised after logging)
    """
    try:
        domain_obj = StoreDomain.objects.get(store=store, domain=domain)
        
        old_primary = domain_obj.is_primary
        domain_obj.is_primary = is_primary
        
        # If making this domain primary, unset other primary domains
        if is_primary and not old_primary:
            StoreDomain.objects.filter(store=store, is_primary=True).exclude(id=domain_obj.id).update(is_primary=False)
        
        domain_obj.save()
        
        logger.info(f"Domain '{domain}' updated in store '{store.name}' (id: {store.id}), is_primary={is_primary}")
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
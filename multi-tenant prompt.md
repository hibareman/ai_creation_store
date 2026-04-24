You are implementing features in this Django backend with strict multi-tenant isolation.

PROJECT LAYER CONTRACT (MUST FOLLOW):
- Models: persistence rules only
- Selectors: data access only (querying/filtering)
- Services: ALL business logic + final access control (tenant + ownership)
- Serializers: input shape/type validation + output formatting only
- Views: orchestration only (validate input -> load scoped data -> call service -> return response)

MANDATORY MULTI-TENANT RULES:
1) Never trust client-provided tenant_id, owner_id, user_id, or store ownership data.
2) Always take tenant/user context from middleware-authenticated request:
   - request.user
   - request.tenant_id
3) For store-scoped endpoints, load store with tenant-scoped selector/query FIRST:
   - get_store_by_id(store_id, tenant_id=request.tenant_id)
4) If tenant-scoped lookup returns nothing, return NotFound (no cross-tenant leakage).
5) Always pass request.user to service methods that enforce ownership/access.
6) Service layer must enforce:
   - user.tenant_id == store.tenant_id
   - user.id == store.owner_id
7) Do not implement tenant/ownership business checks in serializers.
8) Do not put business logic in views or serializers.
9) Keep selectors free of business decisions (no permission logic there).
10) Preserve existing API contracts and error messages unless explicitly required to change.

IMPLEMENTATION PATTERN FOR STORE-SCOPED WRITE ENDPOINTS:
1) permission_classes = [TenantAuthenticated]
2) Parse/validate request payload using request serializer only
3) Load store by (store_id + request.tenant_id)
4) Call service with (store, ..., user=request.user)
5) Format response using response serializer

SECURITY CHECKLIST BEFORE MERGE:
- Tenant-scoped lookup exists for all scoped resources
- No path uses unscoped lookup for sensitive operations
- Service access validation is present and used
- Serializer has no service calls and no access-control logic
- View does not trust client ownership/tenant fields
- No cross-tenant resource enumeration possible

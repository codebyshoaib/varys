---
name: taleemabad-core Patterns
description: DO / NEVER DO / Recurring gotchas for taleemabad-core development
updated: 2026-06-02
---

# Patterns — taleemabad-core

## DO

- **TenantMixin on every new model** — multi-tenant schema isolation is mandatory; every model must be scoped to a tenant
- **Soft-delete only**: set `is_active=False` (triggers `deleted_at` via `SoftDeleteMixin.save()`); never call `.delete()`
- **Reversible migrations**: always implement `database_backwards`; test it locally before committing
- **BasePushSyncSerializer**: all push-sync endpoints must subclass it; never roll custom sync logic
- **`db.transaction()` for multi-table Dexie writes**: wrap all cross-table IndexedDB writes in a single Dexie transaction to avoid partial state on the frontend
- **Increment Dexie version on schema change**: any change to indexed fields or stores requires bumping `db.version(N)` in the frontend
- **Include `profileId` in Dexie key AND filter**: every write in `api/teachertraining.ts` must scope to `profileId` in both the key and the query filter
- **Feature branch → PR**: never push to `develop` or `main` directly
- **Run `/feature` before `/develop`**: always research + plan with Varys's approval before coding
- **Log every bug** to `.claude/features/<feature>/bugs.md` with OPEN/FIXED status
- **Confidence ≥ 86%** before marking a feature ready for PR

## NEVER DO

- **Hard delete** — never call `.delete()` on any model; always `is_active=False`
- **Non-reversible migration** — never use `RunSQL` without a reverse, never drop columns without a plan
- **Forget `tenant_id` filter on GET** — every queryset must filter by tenant; missing this = data leak
- **Work on `develop` branch directly** — always feature branch → PR → review → merge
- **Use Haiku model** for taleemabad-core tasks — codebase is too large and complex; use Sonnet or higher
- **Skip the harness** — no direct coding without `/feature` plan approval from Varys
- **Mock the database in tests** — use Django test DB; only mock external APIs
- **Leave `any` types in new Python code** — mypy strict; all new code must be fully typed

## Recurring Issues (Known Gotchas)

### Race Condition in Dexie Writes
**Symptom**: Duplicate or missing records after offline sync pushes.  
**Cause**: Multiple async writes to Dexie without wrapping in `db.transaction()`.  
**Fix**: Always wrap multi-table writes in `db.transaction('rw', [table1, table2], async () => { ... })`.

### Timestamp Precision Mismatch
**Symptom**: Records re-sync even when no changes made; `updated_at` comparisons fail.  
**Cause**: Python `datetime` stores microseconds; JavaScript `Date.now()` is milliseconds; Dexie stores as ms integer.  
**Fix**: Normalize to milliseconds before storing in Dexie; backend should truncate to ms precision in push-sync serializer.

### Soft-Delete + Sync Conflict
**Symptom**: Deleted records reappear after sync from another device.  
**Cause**: Offline device pushes stale record after server soft-deleted it; timestamp-wins gives precedence to offline write.  
**Fix**: Sync response must always return `is_active` field; frontend must respect `is_active=False` as a tombstone and not re-push.

### Multi-Tenant Data Leak
**Symptom**: Coach or teacher sees data from another school/tenant.  
**Cause**: QuerySet missing `filter(school__tenant=request.tenant)` or equivalent tenant scope.  
**Fix**: Every ViewSet `get_queryset()` must filter by tenant; add tenant-scope test in every new view's test class.

### GFK (GenericForeignKey) Profile Attachment
**Symptom**: `ContentType` mismatch when attaching coach/teacher profiles to observations.  
**Cause**: Passing wrong `content_type_id` or profile type string.  
**Fix**: Use `gfk_helpers.get_content_type_for_profile_type()` and `attach_user_profile_gfk()` — never construct GFK manually.

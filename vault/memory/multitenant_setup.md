---
name: Multi-tenant setup with omer.localhost
description: Taleemabad uses multi-tenant architecture with different schemas per tenant
type: project
originSessionId: 260e7955-822b-4871-a93e-6ed54552d5c2
---
Taleemabad Core uses a multi-tenant architecture where:
- Each tenant has their own database schema
- omer.localhost is one of the running tenants in the project
- Kamal's project is running with this multi-tenant configuration already in place
- Tests should run against the actual running omer.localhost backend, not localhost:8000 docker instance

This means:
- When testing teacher training, we should point to the actual running backend on omer.localhost (not localhost:8000 from Docker)
- The multi-tenant setup handles schema isolation and tenant context
- Tests need to account for the tenant-specific URLs (omer.localhost domain)

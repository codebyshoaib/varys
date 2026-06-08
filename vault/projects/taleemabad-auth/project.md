---
name: taleemabad-auth
description: JWT authentication middleware for Taleemabad services
---

# taleemabad-auth — Authentication Service

## Overview
- **GitHub**: Taleemabad organization (private)
- **Local Path**: `{{config:REPO_ROOT}} (actual path TBD)
- **Tech Stack**: Python/Django or Node.js (TBD)
- **Purpose**: JWT token issuance and validation across [[taleemabad-core]] and [[taleemabad-cms]]
- **Status**: Active
- **Consumers**: taleemabad-core, taleemabad-cms

## Key Responsibilities

### Token Issuance
- User login → generate JWT token
- Token includes: user_id, roles, permissions
- Configurable expiration (access + refresh tokens)
- Secure signing with shared secret or RSA keys

### Token Validation
- Middleware on protected endpoints validates token signature
- Extracts user info from token claims
- Enforces permission checks
- Handles token expiration and refresh

### User Roles & Permissions
- Define roles: admin, editor, viewer, learner
- Map roles to endpoint permissions
- Example: admin can delete training, viewer can only read

### OAuth Integration (Future)
- NIETE SSO integration planned
- External provider support (Google, etc.)

## API Endpoints

```
POST   /api/v1/auth/login/           # User login → token
POST   /api/v1/auth/refresh/         # Refresh access token
POST   /api/v1/auth/logout/          # Token revocation
POST   /api/v1/auth/register/        # User registration (if enabled)
GET    /api/v1/auth/validate/        # Token validation (internal)
```

## Related Files
- [[architecture]] — Token structure, validation flow
- [[decisions]] — Auth strategy, why JWT vs sessions
- [[related]] — Links to taleemabad-core and taleemabad-cms

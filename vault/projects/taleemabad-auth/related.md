---
name: taleemabad-auth Relationships
description: Links to services that depend on auth
---

# Related Projects

## Backend Service
- **[[projects/taleemabad-core]]** — Validates JWT tokens on protected endpoints
  - All API endpoints require valid token (except public endpoints)
  - Extracts user info from token claims
  - Uses roles/permissions for endpoint authorization

## Frontend Service
- **[[projects/taleemabad-cms]]** — Obtains tokens, includes in API requests
  - User logs in via CMS
  - Stores tokens (localStorage or cookies)
  - Includes access token in Authorization header for all API calls
  - Handles token refresh before expiration

## Token Lifecycle

### Issuance
1. **CMS**: User enters email + password
2. **CMS**: POST `/api/v1/auth/login/` to auth service
3. **Auth**: Validates credentials, generates tokens
4. **CMS**: Receives access + refresh tokens

### Usage
1. **CMS**: Includes access token in all API requests to core
2. **Core**: Validates token signature, extracts user info
3. **Core**: Serves request (if permission check passes)

### Refresh
1. **CMS**: Access token nearing expiration (or API returns 401)
2. **CMS**: POST `/api/v1/auth/refresh/` with refresh token
3. **Auth**: Validates refresh token, issues new access token
4. **CMS**: Stores new token, retries original API call

### Logout
1. **CMS**: User clicks logout
2. **CMS**: POST `/api/v1/auth/logout/` (optional cleanup)
3. **CMS**: Deletes tokens from localStorage/cookies
4. **Subsequent requests**: Include no token, core returns 401

## Cross-Project Concerns

### User Database
- Auth service owns user table
- Core references user_id via JWT claims
- CMS displays user info from token claims

### Role Synchronization
- Auth service defines roles
- Core uses roles for permission checks
- CMS displays role-appropriate UI (admin sees delete button, viewer doesn't)

### NIETE SSO (Future)
- NIETE users login via NIETE SSO
- Auth service bridges NIETE identity to local tokens
- Enables single sign-on across Taleemabad services

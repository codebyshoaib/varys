---
name: taleemabad-auth Architecture
description: JWT token structure, validation, middleware
---

# Architecture — taleemabad-auth

## JWT Token Structure

```json
{
  "sub": "user_id",
  "iat": 1234567890,
  "exp": 1234571490,
  "roles": ["admin", "editor"],
  "permissions": ["training:write", "quiz:read"],
  "user_email": "user@example.com"
}
```

## Token Types

### Access Token
- **Expiration**: 1 hour
- **Usage**: All API requests
- **Refresh**: Via refresh token before expiration

### Refresh Token
- **Expiration**: 30 days
- **Usage**: Only for `/api/v1/auth/refresh/`
- **Rotation**: New access + refresh token issued on refresh

## Authentication Flow

```
1. User submits login (email + password)
2. Validate credentials against user database
3. Generate access + refresh tokens
4. Return tokens to client
5. Client stores tokens (localStorage/sessionStorage)
6. Client includes access token in Authorization header: Bearer {token}
7. Protected endpoints validate token signature
8. If valid, extract user info and serve request
9. If expired, client calls refresh endpoint
10. If refresh expired, user must login again
```

## Validation Middleware

```python
# Django example
class JWTAuthMiddleware:
    def authenticate(self, request):
        header = request.headers.get("Authorization")
        if not header:
            return None
        
        try:
            scheme, token = header.split()
            if scheme != "Bearer":
                return None
            
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user = User.objects.get(id=payload["sub"])
            return user, None
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token expired")
        except jwt.InvalidTokenError:
            raise AuthenticationFailed("Invalid token")
```

## Permission Checking

### Role-Based Access Control (RBAC)
- Roles: admin, editor, viewer, learner
- Each role has predefined permissions
- Example: `admin` has all permissions; `viewer` has `training:read` only

### Permission Decorator
```python
@permission_required("training:write")
def create_training(request):
    # Only users with training:write permission
    pass
```

## User Roles

| Role | Can | Cannot |
|------|-----|---------|
| admin | Create/edit/delete trainings, manage users | Nothing |
| editor | Create/edit trainings, upload assets | Delete trainings, manage users |
| viewer | View trainings, take quizzes | Create/edit trainings, manage assets |
| learner | Take quizzes, view progress | Anything admin-related |

## Security Considerations

### Token Signing
- Use HS256 (symmetric) with long secret or RS256 (asymmetric) with key pair
- Never expose secret key in frontend or version control
- Rotate keys periodically

### Token Storage (Frontend)
- Option 1: localStorage (vulnerable to XSS if JWT exposed)
- Option 2: httpOnly cookies (immune to XSS, requires CSRF protection)
- Option 3: sessionStorage (cleared on browser close, better privacy)

### HTTPS Enforcement
- All auth endpoints must use HTTPS in production
- Prevents token interception on the wire

### CORS Configuration
- Allow credentials in CORS headers if using cookies
- Example: `Access-Control-Allow-Credentials: true`

## Deployment Notes

- Token secret stored as environment variable (never hardcoded)
- Different secrets for dev/staging/production
- Consider centralized key management (AWS Secrets Manager, etc.) at scale

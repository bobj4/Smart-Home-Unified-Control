# HTTP Headers Implementation

This document describes the HTTP headers implementation for the Smart Home Backend, covering security headers (SEC-24) and CORS configuration (SEC-14).

## Overview

Security headers and CORS are implemented through a layered middleware approach:

1. **SecurityHeadersMiddleware**: Applied via `@app.middleware("http")` decorator to add security headers to all responses
2. **CORSMiddleware**: Applied via `app.add_middleware()` for CORS preflight handling

## Security Headers (SEC-24)

The `SecurityHeadersMiddleware` in `backend/app/headers.py` adds the following headers to all responses:

### Implemented Headers

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | Strict CSP policy | Restricts resource loading to prevent XSS and injection attacks |
| `X-Frame-Options` | DENY | Prevents clickjacking by disallowing framing |
| `X-Content-Type-Options` | nosniff | Prevents MIME type sniffing |
| `Strict-Transport-Security` | max-age=31536000; includeSubDomains | Enforces HTTPS connections |
| `Referrer-Policy` | strict-origin-when-cross-origin | Controls referrer information leakage |
| `X-XSS-Protection` | 1; mode=block | Legacy XSS filter for older browsers |
| `X-Permitted-Cross-Domain-Policies` | none | Prevents browser plugins from accessing content |
| `Permissions-Policy` | geolocation, microphone, camera, etc. | Restricts browser features |
| `Cache-Control` | no-store, no-cache, must-revalidate, private | Prevents caching of sensitive data |
| `Pragma` | no-cache | HTTP/1.0 fallback for cache control |

### CSP Policy Details

The Content-Security-Policy is configured as follows:

```
default-src 'self'; 
script-src 'self'; 
style-src 'self' 'unsafe-inline'; 
img-src 'self' data: https:; 
font-src 'self'; 
connect-src 'self'; 
frame-ancestors 'self'; 
form-action 'self'; 
base-uri 'self'; 
upgrade-insecure-requests;
```

This policy:
- Restricts all resource loading to the same origin
- Allows inline styles (can be tightened if needed)
- Allows images from same origin, data URIs, and HTTPS sources
- Restricts form actions to the same origin
- Enforces secure upgrades for HTTP to HTTPS

## CORS Configuration (SEC-14)

### Default Configuration

By default, the CORS middleware has **no origins allowed**:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # Empty by default - SEC-14
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This implements SEC-14: "CORS origin allow-list, no origins allowed by default."

### Configuration Options

CORS can be configured via environment variables (see `backend/app/db_config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | (empty) | Comma-separated list of allowed origins |
| `CORS_ALLOW_CREDENTIALS` | True | Whether to allow credentials |
| `CORS_ALLOW_METHODS` | * | Allowed HTTP methods |
| `CORS_ALLOW_HEADERS` | * | Allowed request headers |
| `CORS_EXPOSE_HEADERS` | x-requested-with | Headers exposed to clients |
| `CORS_MAX_AGE` | 86400 | Preflight cache time in seconds |

### Usage Examples

#### Development (Allow specific origins)

Set in `.env`:
```
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

#### Production (No origins - secure default)

```
CORS_ORIGINS=  # Leave empty for secure default
```

#### With specific configuration

```
CORS_ORIGINS=https://example.com
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=GET,POST,OPTIONS
CORS_ALLOW_HEADERS=Content-Type,Authorization,X-Requested-With
CORS_EXPOSE_HEADERS=Content-Length
CORS_MAX_AGE=3600
```

## Middleware Order

The middleware stack order is important:

1. **SecurityHeadersMiddleware** - Runs first on all responses
2. **CORSMiddleware** - Runs before handlers, handles preflight requests
3. **SessionMiddleware** - Validates session tokens
4. **Route handlers** - Process the actual request

## Testing Headers

### Check Security Headers

```bash
curl -I http://localhost:8000/health
```

Expected headers:
- `Content-Security-Policy: default-src 'self'; ...`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 1; mode=block`
- `X-Permitted-Cross-Domain-Policies: none`
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), ...`
- `Cache-Control: no-store, no-cache, must-revalidate, private`

### Check CORS Headers (Preflight)

```bash
curl -X OPTIONS \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  http://localhost:8000/api/v1/login
```

Expected response (if origin is allowed):
- `Access-Control-Allow-Origin: http://localhost:3000`
- `Access-Control-Allow-Credentials: true`
- `Access-Control-Allow-Methods: GET, POST, OPTIONS`
- `Access-Control-Allow-Headers: *`
- `Access-Control-Max-Age: 86400`

## Customization

### Extending Security Headers

To add custom security headers, modify `backend/app/headers.py` in the `SecurityHeadersMiddleware.dispatch()` method:

```python
response.headers["Custom-Header"] = "custom-value"
```

### Extending CORS

To extend CORS functionality, use the `CORSMiddleware` class in `backend/app/headers.py`:

```python
from backend.app.headers import CORSMiddleware

# Create with custom configuration
cors = CORSMiddleware(
    origins=["https://example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["X-Custom-Header"],
    max_age=3600,
)
```

## Security Considerations

### 1. CSP and Inline Scripts

The current CSP allows `'unsafe-inline'` for styles. For production, consider:
- Using CSS hashes instead of inline styles
- Loading styles from external files
- Using nonces for inline scripts

### 2. HSTS and Mixed Content

The `Strict-Transport-Security` header enforces HTTPS. Ensure:
- All traffic is served over HTTPS
- No mixed content (HTTP resources on HTTPS pages)
- Load balancer/proxy also supports HSTS

### 3. CORS in Production

The default configuration (empty `allow_origins`) is secure but restrictive. For production:
- Whitelist only trusted origins
- Avoid `allow_credentials=True` with wildcard origins
- Consider shorter `max_age` values for dynamic configurations

### 4. Header Precedence

Note that `Access-Control-Allow-Origin` can only be set once. The middleware ensures this by:
- Checking origin allowlist first
- Setting the header only for allowed origins
- Using the standard FastAPI CORSMiddleware

## Files Modified

- `backend/app/headers.py` - New file with `SecurityHeadersMiddleware` and `CORSMiddleware` classes
- `backend/main.py` - Added security headers middleware
- `backend/app/factory.py` - Added security headers middleware
- `backend/app/db_config.py` - Added CORS configuration settings
- `backend/app/routes/auth.py` - Removed redundant `add_security_headers()` function
- `docs/SECURITY.md` - Updated to reflect implemented headers

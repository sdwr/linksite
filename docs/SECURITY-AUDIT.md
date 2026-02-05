# Security Audit — Linksite

**Date:** 2025-01-17  
**Severity Scale:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## 🔴 CRITICAL: Hardcoded Database Password

**File:** `db.py` line 14

```python
DEFAULT_DATABASE_URL = 'postgresql://postgres:0JvN0xPnOFcxPbmm@db.rsjcdwmgbxthsuyspndt.supabase.co:5432/postgres'
```

**Impact:** Anyone with repo access has full database access (read/write/delete).

**Fix:**
```python
DEFAULT_DATABASE_URL = None  # Must be set via DATABASE_URL env var

def get_pool(min_conn=2, max_conn=10):
    ...
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")
```

**Also:** Rotate this password immediately if repo has ever been public.

---

## 🔴 CRITICAL: Credentials in TOOLS.md

**File:** `TOOLS.md` (workspace root)

Contains plaintext:
- Supabase service role key
- Supabase DB password
- Reddit client ID/secret
- GitHub PAT

**Impact:** If committed to git or accessible, all services are compromised.

**Fix:**
1. Move all credentials to `.env` (gitignored)
2. Remove from TOOLS.md, replace with "see .env" or "see 1Password"
3. Rotate ALL exposed credentials
4. Check git history for past commits containing secrets

---

## 🟠 HIGH: CORS Allows All Origins + Credentials

**File:** `main.py` lines 113-118

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # ← Dangerous combo
    ...
)
```

**Impact:** Any website can make authenticated requests to your API, enabling CSRF-style attacks.

**Fix:**
```python
ALLOWED_ORIGINS = [
    "https://linksite-dev-bawuw.sprites.app",
    "http://localhost:3000",  # dev only
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
```

---

## 🟠 HIGH: No Auth on Write Endpoints

**Affected endpoints:**
- `POST /api/link` — create links (no auth)
- `POST /api/link/{id}/notes` — post comments (no auth)
- `POST /api/link/{id}/tags` — add tags (no auth)
- `POST /api/link/{id}/find-discussions` — triggers external API calls (no auth)
- `POST /api/check` — create links (no auth)

**Impact:** 
- Spam/abuse (flood with garbage links/comments)
- Resource exhaustion (trigger expensive external API calls)
- Data pollution

**Fix options:**
1. **Rate limiting** (minimum): Add IP-based rate limits to all write endpoints
2. **API key requirement**: Require `X-API-Key` header for write operations
3. **User auth**: Require login for write operations (beyond anonymous cookie)

Quick rate limit example:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/api/link")
@limiter.limit("10/minute")
async def api_link_create(body: LinkCreate, request: Request):
    ...
```

---

## 🟡 MEDIUM: User Cookie Not HttpOnly

**File:** `main.py` line 165

```python
response.set_cookie(
    key="user_id",
    value=user_id,
    httponly=False,  # Intentional for JS access
    ...
)
```

**Impact:** XSS vulnerabilities could steal user IDs.

**Mitigation:** 
- Ensure robust XSS protection (CSP headers, sanitized inputs)
- Consider if JS really needs access, or if a separate non-sensitive cookie could work

---

## 🟡 MEDIUM: No Rate Limiting on Most Endpoints

Only `/api/links/{link_id}/react` has rate limiting (10s cooldown).

**Missing rate limits:**
- Link creation
- Note/comment creation  
- Tag operations
- Search/browse endpoints
- Discussion lookup (triggers external API calls)

**Fix:** Add rate limiting middleware or per-endpoint limits.

---

## 🟡 MEDIUM: External API Abuse Vector

**File:** `scratchpad_api.py`

`POST /api/link/{id}/find-discussions` triggers Reddit OAuth + HN API calls with no auth/rate limit.

**Impact:** Attacker could exhaust your Reddit API quota or cause IP bans.

**Fix:**
1. Require auth or API key
2. Add aggressive rate limiting (e.g., 5/minute per IP)
3. Queue requests instead of processing immediately

---

## 🟢 LOW: Admin Password Empty Fallback

**File:** `main.py` line 103

```python
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
```

Returns 500 if not set (good), but the empty string default could cause confusion.

**Fix:**
```python
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("[WARNING] ADMIN_PASSWORD not set — admin routes disabled")
```

---

## 🟢 LOW: Verbose Error Messages

Some error handlers return raw exception text which could leak implementation details.

**Fix:** Return generic errors in production, log full errors server-side.

---

## Summary & Priority

| Issue | Severity | Effort | Priority |
|-------|----------|--------|----------|
| Hardcoded DB password | 🔴 Critical | Low | **NOW** |
| Credentials in TOOLS.md | 🔴 Critical | Low | **NOW** |
| CORS allow all + credentials | 🟠 High | Low | This week |
| No auth on write endpoints | 🟠 High | Medium | This week |
| Cookie not HttpOnly | 🟡 Medium | Low | Soon |
| Missing rate limits | 🟡 Medium | Medium | Soon |
| External API abuse | 🟡 Medium | Low | Soon |

---

## Immediate Actions

1. **Remove hardcoded password from db.py** — require env var
2. **Rotate Supabase DB password** — assume compromised
3. **Check if repo is public** — if yes, rotate ALL credentials
4. **Move secrets from TOOLS.md to .env**
5. **Restrict CORS origins**

---

*Generated by security audit*

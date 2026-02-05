# Dead Code Analysis — Linksite

## Summary

**27 Python files** are not imported by the main application.

---

## Category 1: Old Application (SAFE TO REMOVE)

| File | Description | Safe? |
|------|-------------|-------|
| `app.py` | Old Flask app, replaced by `main.py` (FastAPI) | ✅ Yes |

**Evidence:** Uses Flask, has its own Supabase client initialization. The entire app has migrated to FastAPI in `main.py`.

---

## Category 2: One-Off Migration Scripts (PROBABLY SAFE)

| File | Description | Safe? |
|------|-------------|-------|
| `migrate_v2.py` | v2 schema migration | ✅ Already run |
| `migrate_v3.py` | v3 schema migration | ✅ Already run |
| `run_migration.py` | Admin dashboard migration | ✅ Already run |
| `run_gatherer_migration.py` | Gatherer table migration | ✅ Already run |
| `run_rate_limit_migration.py` | Rate limit table migration | ✅ Already run |
| `run_ddl.py` | Generic DDL runner | ⚠️ May be useful |
| `verify_migration.py` | Post-migration verification | ✅ Already run |

**Note:** These were run once to set up the DB schema. Keeping them doesn't hurt (documentation), but they're not needed for runtime.

---

## Category 3: Diagnostic Scripts (PROBABLY SAFE)

| File | Description | Safe? |
|------|-------------|-------|
| `check_status.py` | Shows processing_status counts | ⚠️ Useful for debugging |
| `check_links.py` | Check links in DB | ⚠️ Useful for debugging |
| `check_summaries.py` | Check summary status | ⚠️ Useful for debugging |
| `check_existing_summaries.py` | Check existing summaries | ⚠️ Useful for debugging |
| `check_summary_ids.py` | Check summary IDs | ⚠️ Useful for debugging |
| `check_sync.py` | Check sync status | ⚠️ Useful for debugging |
| `get_links_needing_summary.py` | List links needing summary | ⚠️ Useful for debugging |

**Note:** These are CLI diagnostic tools. Useful to keep for manual debugging, but not required for app operation.

---

## Category 4: Test Scripts (PROBABLY SAFE)

| File | Description | Safe? |
|------|-------------|-------|
| `test_dedup.py` | Test deduplication logic | ⚠️ Test code |
| `test_feeds.py` | Test feed parsing | ⚠️ Test code |
| `test_resolve.py` | Test URL resolution | ⚠️ Test code |
| `test_summary_icon.py` | Test summary icons | ⚠️ Test code |
| `test_youtube.py` | Test YouTube extraction | ⚠️ Test code |

**Note:** Test scripts. Could be moved to a `tests/` directory or removed if tests aren't being run.

---

## Category 5: Utility Scripts (MIXED)

| File | Description | Safe? |
|------|-------------|-------|
| `dump_links.py` | Export links to JSON | ⚠️ May be useful for backup |
| `fetch_10_links.py` | Test fetch of 10 links | ✅ Test code |
| `show_samples.py` | Display sample links | ✅ Test code |
| `compare_summaries.py` | Compare summary quality | ⚠️ Analysis tool |
| `run_summaries.py` | Manual summary batch runner | ⚠️ May be useful |
| `process_urls.py` | Old URL processing script | ✅ Replaced by worker |
| `director_fix.py` | One-time director fix | ✅ Already run |

---

## Category 6: Unused Endpoints (IN scratchpad_api.py)

| Endpoint | Description | Used? |
|----------|-------------|-------|
| `POST /api/link/{id}/find-discussions` | Manual trigger for discussion lookup | ❌ Not called from anywhere |

**Evidence:** 
- Not in frontend (web/src)
- Not in admin HTML templates (main.py)
- Not in any automation

**Recommendation:** Either remove or add admin UI button to use it.

---

## Recommendations

### Tier 1: Safe to Remove Now
```
app.py                    # Old Flask app
director_fix.py           # One-time fix
fetch_10_links.py         # Test script
show_samples.py           # Test script
process_urls.py           # Replaced by worker
```

### Tier 2: Move to `scripts/` Directory
```
migrate_v2.py
migrate_v3.py
run_migration.py
run_gatherer_migration.py
run_rate_limit_migration.py
run_ddl.py
verify_migration.py
```

### Tier 3: Move to `tools/` Directory
```
check_status.py
check_links.py
check_summaries.py
check_existing_summaries.py
check_summary_ids.py
check_sync.py
get_links_needing_summary.py
dump_links.py
compare_summaries.py
run_summaries.py
```

### Tier 4: Move to `tests/` Directory
```
test_dedup.py
test_feeds.py
test_resolve.py
test_summary_icon.py
test_youtube.py
```

### Tier 5: Decide on Endpoints
- `POST /api/link/{id}/find-discussions` — either add to admin UI or remove

---

## Impact Analysis

### If We Remove Tier 1 Files:

| File | Risk | Impact |
|------|------|--------|
| `app.py` | None | Old code, not used |
| `director_fix.py` | None | One-time fix already applied |
| `fetch_10_links.py` | None | Manual test script |
| `show_samples.py` | None | Display script |
| `process_urls.py` | Low | Old ingestion, replaced by `ingest_link_async()` + worker |

**Total risk:** Very low. These files are not imported or called by the main application.

### If We Reorganize (Tiers 2-4):

Moving files to subdirectories would:
- ✅ Clean up root directory
- ✅ Make it clear what's core vs tooling
- ⚠️ Break any manual `python check_status.py` workflows (fixable by updating path)

---

## Files to KEEP in Root

These are actively used by the application:

```
main.py           # FastAPI app
db.py             # Database connection pool
db_compat.py      # Supabase compatibility layer
ingest.py         # Content extraction
director.py       # Link rotation director
gatherer.py       # RSS feed gatherer
worker.py         # Background processor
scratchpad_api.py # Main API routes
scratchpad_routes.py # HTML routes
ai_engine.py      # AI content generation
ai_routes.py      # AI API routes
backoff.py        # Rate limiting
prompts.py        # AI prompts
user_utils.py     # User name generation
```

---

*Analysis completed: 2025-01-17*

# Linksite TODOs

## Feed Scraping Cleanup
- [ ] Refactor `ingest.py` — separate scraping logic (YouTube vs article) from vectorization more cleanly
- [ ] `main.py` has inline HTML templates (LINKS_TEMPLATE, ADMIN_TEMPLATE) — extract to proper Jinja2 template files
- [ ] RSS feed processing (`process_single_feed`) only grabs first 10 entries — make configurable
- [ ] YouTube scraping relies on a single Invidious instance (`inv.tux.pizza`) — add fallback instances or retry logic
- [ ] `ingest_link()` silently swallows errors after printing — add proper error tracking/logging
- [ ] `scrape_article()` and `scrape_youtube()` duplicate logic already in `ContentExtractor` class — consolidate
- [ ] Feed sync uses `description` field inconsistently — `ingest_link()` falls back to RSS summary over scraped content
- [ ] Content is truncated to 5000 chars before vectorization with no indication — consider smarter chunking
- [ ] `app.py` (Flask) and `main.py` (FastAPI) both serve the same links view — pick one and remove the other
- [ ] No deduplication beyond exact URL match — similar content from different URLs can flood the DB
- [ ] Add rate limiting / backoff for external scraping requests
- [ ] `vectorize()` uses a global lazy-loaded model singleton — fine for now, but consider lifecycle management for production

## General
- [ ] Phase 3 (LinkCompass / similarity navigation) not yet implemented
- [ ] Phase 4 frontend (`web/`) has scaffolding with mock data but no backend integration
- [ ] No Dockerfile or `fly.toml` in repo — deployment config may be elsewhere or manual

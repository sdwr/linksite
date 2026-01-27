# Link Discovery Game - Backend (Phase 2)

Backend ingestion engine for the link discovery game. This system extracts content from URLs (YouTube videos and websites), generates vector embeddings, and stores them in a Supabase database for similarity-based link discovery.

## Features

- **YouTube Content Extraction**: Automatically extracts video title, channel name, and auto-generated captions/transcripts
- **Website Content Extraction**: Extracts OpenGraph metadata and main body text (filtering out nav, ads, etc.)
- **Vector Embeddings**: Converts text content into 384-dimensional vectors using `all-MiniLM-L6-v2` model
- **Supabase Integration**: Stores links with vector embeddings for fast similarity search using pgvector

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Supabase Database

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to the SQL Editor in your Supabase dashboard
3. Run the SQL schema from `schema.sql`

### 3. Configure Environment Variables

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your Supabase credentials:
   - `SUPABASE_URL`: Found in Project Settings > API
   - `SUPABASE_KEY`: Use the `anon` public key from Project Settings > API

## Usage

### Processing URLs from test_urls.txt

Run the main processing script:

```bash
python process_urls.py
```

This will:
1. Read URLs from `test_urls.txt`
2. Extract content from each URL
3. Generate vector embeddings
4. Store everything in your Supabase database

### Using the Ingestion Module Directly

```python
from ingest import extract_content, vectorize

# Extract content from any URL
content = extract_content("https://www.example.com")
print(f"Title: {content['title']}")
print(f"Text: {content['text_content'][:200]}...")

# Generate vector embedding
vector = vectorize(content['text_content'])
print(f"Vector dimensions: {len(vector)}")  # Should be 384
```

### YouTube Example

```python
from ingest import extract_content

# Extract from YouTube video
content = extract_content("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

print(f"Title: {content['title']}")
print(f"Channel: {content['metadata']['channel_name']}")
print(f"Transcript: {content['text_content'][:500]}...")
```

## File Structure

```
linksite/
├── schema.sql              # Supabase database schema
├── ingest.py              # Core content extraction and vectorization module
├── process_urls.py        # Main script to process URLs from file
├── test_urls.txt          # Sample URLs for testing
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── README.md             # This file
```

## Database Schema

The `links` table includes:

- `id`: Auto-incrementing primary key
- `url`: Unique URL (text)
- `title`: Extracted title
- `meta_json`: JSONB field storing metadata (og:image, channel_name, type, etc.)
- `content_vector`: 384-dimensional vector embedding (pgvector)
- `comment_vector`: 384-dimensional vector for averaged user comments
- `created_at`: Timestamp
- `updated_at`: Auto-updated timestamp

## Adding Your Own URLs

Edit `test_urls.txt` and add one URL per line:

```
https://www.youtube.com/watch?v=example
https://interesting-blog.com/article
https://news.ycombinator.com/
```

Lines starting with `#` are treated as comments.

## Next Steps (Phase 3)

After populating your database with links, you'll need to:

1. Create the `LinkCompass` class for finding related links
2. Implement the 5-slot system (Deep Dive, Pivot, Wildcard)
3. Add comment vectorization for user feedback

See `PROJECT_BRIEF.md` for the full roadmap.

## Troubleshooting

### "Missing Supabase credentials" error
Make sure you've created a `.env` file with valid `SUPABASE_URL` and `SUPABASE_KEY`

### YouTube extraction fails
Some YouTube videos may have restricted captions or may be unavailable. The script will fall back to the video description if captions aren't available.

### Website extraction returns empty text
Some websites heavily rely on JavaScript to render content. The current implementation uses static HTML parsing, so JavaScript-heavy sites may not extract well.

### Vector dimension mismatch
The `all-MiniLM-L6-v2` model produces 384-dimensional vectors. Make sure your database schema uses `vector(384)`.

## Dependencies

- **beautifulsoup4**: HTML parsing
- **yt-dlp**: YouTube content extraction
- **sentence-transformers**: Vector embeddings
- **supabase**: Database client
- **pgvector**: PostgreSQL vector similarity search

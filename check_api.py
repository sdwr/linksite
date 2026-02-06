#!/usr/bin/env python3
"""Check youtube-transcript-api."""
import youtube_transcript_api
print("Version:", youtube_transcript_api.__version__ if hasattr(youtube_transcript_api, '__version__') else 'unknown')

from youtube_transcript_api import YouTubeTranscriptApi
print("Methods:", [m for m in dir(YouTubeTranscriptApi) if not m.startswith('_')])

# Try the new fetch method
try:
    ytt_api = YouTubeTranscriptApi()
    result = ytt_api.fetch('dQw4w9WgXcQ')
    print("fetch() worked! Result type:", type(result))
    if hasattr(result, 'snippets'):
        print("Snippets:", len(result.snippets))
    else:
        print("First item:", result[:1] if result else 'empty')
except Exception as e:
    print(f"fetch() failed: {type(e).__name__}: {e}")

# Try list_transcripts
try:
    ytt_api = YouTubeTranscriptApi()
    transcripts = ytt_api.list('dQw4w9WgXcQ')
    print("list() worked! Result:", transcripts)
except Exception as e:
    print(f"list() failed: {type(e).__name__}: {e}")

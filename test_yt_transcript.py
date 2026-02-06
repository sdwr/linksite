#!/usr/bin/env python3
"""Test youtube-transcript-api from cloud sprite - working version."""
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, 
    NoTranscriptFound, 
    VideoUnavailable,
)

test_videos = [
    ('dQw4w9WgXcQ', 'Rick Astley - Never Gonna Give You Up'),
    ('jNQXAC9IVRw', 'Me at the zoo (first YT video)'),
    ('9bZkp7q19f0', 'Gangnam Style'),
    ('kJQP7kiw5Fk', 'Despacito'),
]

print("=" * 70)
print("YOUTUBE TRANSCRIPT API TEST (from cloud sprite)")
print("=" * 70)

ytt_api = YouTubeTranscriptApi()

for video_id, name in test_videos:
    try:
        result = ytt_api.fetch(video_id)
        text = ' '.join([s.text for s in result.snippets])
        print(f"OK: {name[:40]:40} - {len(result.snippets):4} segments, {len(text):6} chars")
        print(f"    First 100 chars: {text[:100]}...")
    except TranscriptsDisabled:
        print(f"BLOCKED: {name[:40]:40} - Transcripts disabled for this video")
    except NoTranscriptFound:
        print(f"NOTFOUND: {name[:40]:40} - No transcript available")
    except VideoUnavailable:
        print(f"UNAVAIL: {name[:40]:40} - Video unavailable")
    except Exception as e:
        print(f"ERROR: {name[:40]:40} - {type(e).__name__}: {str(e)[:60]}")

print("=" * 70)

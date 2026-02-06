#!/usr/bin/env python3
"""Test youtube-transcript-api from cloud sprite."""
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, 
    NoTranscriptFound, 
    VideoUnavailable,
    TooManyRequests,
    YouTubeRequestFailed
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

for video_id, name in test_videos:
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        text = ' '.join([t['text'] for t in transcript])
        print(f"OK: {name[:40]:40} - {len(transcript):4} segments, {len(text):6} chars")
        print(f"    First 100 chars: {text[:100]}...")
    except TranscriptsDisabled:
        print(f"BLOCKED: {name[:40]:40} - Transcripts disabled for this video")
    except NoTranscriptFound:
        print(f"NOTFOUND: {name[:40]:40} - No transcript available")
    except VideoUnavailable:
        print(f"UNAVAIL: {name[:40]:40} - Video unavailable")
    except TooManyRequests:
        print(f"RATELIM: {name[:40]:40} - Rate limited (IP blocked)")
    except YouTubeRequestFailed as e:
        print(f"FAIL: {name[:40]:40} - {str(e)[:50]}")
    except Exception as e:
        print(f"ERROR: {name[:40]:40} - {type(e).__name__}: {str(e)[:50]}")

print("=" * 70)

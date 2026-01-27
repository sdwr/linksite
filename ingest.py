"""
Link Discovery Game - Content Ingestion Module

This module handles extracting content from URLs (YouTube videos and websites)
and converting them into vector embeddings for similarity search.
"""

import os
import re
from typing import Dict, Optional, List
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
import trafilatura
from sentence_transformers import SentenceTransformer


class ContentExtractor:
    """Handles content extraction from various URL types."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """Check if a URL is a YouTube video."""
        youtube_patterns = [
            r'(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)',
            r'(https?://)?(www\.)?youtube\.com/shorts/'
        ]
        return any(re.search(pattern, url) for pattern in youtube_patterns)

    def extract_youtube_content(self, url: str) -> Dict:
        """
        Extract content from a YouTube video using Invidious API.

        Returns:
            dict: Contains 'title', 'channel_name', 'description', 'thumbnail'
        """
        try:
            # Extract video ID from URL
            video_id = self._extract_youtube_id(url)
            if not video_id:
                raise Exception("Could not extract YouTube video ID")

            # Use public Invidious instance
            invidious_url = f"https://inv.tux.pizza/api/v1/videos/{video_id}"

            response = requests.get(invidious_url, timeout=15)
            response.raise_for_status()

            data = response.json()

            return {
                'title': data.get('title', ''),
                'channel_name': data.get('author', ''),
                'transcript': data.get('description', ''),
                'thumbnail': data.get('videoThumbnails', [{}])[0].get('url', '') if data.get('videoThumbnails') else '',
                'type': 'youtube',
                'tags': data.get('keywords', [])
            }

        except Exception as e:
            raise Exception(f"Error extracting YouTube content: {str(e)}")

    @staticmethod
    def _extract_youtube_id(url: str) -> Optional[str]:
        """Extract YouTube video ID from various URL formats."""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _parse_vtt(vtt_content: str) -> str:
        """Parse VTT subtitle format to extract text."""
        lines = vtt_content.split('\n')
        text_lines = []

        for line in lines:
            line = line.strip()
            # Skip VTT headers, timestamps, and empty lines
            if (not line or
                line.startswith('WEBVTT') or
                '-->' in line or
                re.match(r'^\d+$', line)):
                continue
            # Remove VTT tags
            line = re.sub(r'<[^>]+>', '', line)
            if line:
                text_lines.append(line)

        return ' '.join(text_lines)

    def extract_website_content(self, url: str) -> Dict:
        """
        Extract content from a website using Trafilatura.

        Returns:
            dict: Contains 'title', 'og_image', 'main_text'
        """
        try:
            # Fetch the webpage
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                raise Exception("Could not fetch URL")

            # Extract main text content using trafilatura
            main_text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)

            if not main_text:
                main_text = ''

            # Also parse with BeautifulSoup for metadata
            soup = BeautifulSoup(downloaded, 'html.parser')

            # Extract OpenGraph metadata
            og_title = None
            og_image = None

            og_title_tag = soup.find('meta', property='og:title')
            if og_title_tag:
                og_title = og_title_tag.get('content')

            og_image_tag = soup.find('meta', property='og:image')
            if og_image_tag:
                og_image = og_image_tag.get('content')

            # Fallback to regular title if no OG title
            if not og_title:
                title_tag = soup.find('title')
                og_title = title_tag.string if title_tag else ''

            return {
                'title': og_title,
                'og_image': og_image,
                'main_text': main_text,
                'type': 'website'
            }

        except Exception as e:
            raise Exception(f"Error extracting website content: {str(e)}")


def scrape_youtube(url: str) -> Dict:
    """
    Scrape YouTube video using Invidious API.

    Args:
        url: YouTube video URL

    Returns:
        dict: Video metadata including title, description, tags
    """
    extractor = ContentExtractor()
    result = extractor.extract_youtube_content(url)

    return {
        'title': result['title'],
        'description': result['transcript'],
        'tags': result.get('tags', []),
        'channel': result['channel_name'],
        'thumbnail': result['thumbnail'],
        'type': 'youtube'
    }


def scrape_article(url: str) -> Dict:
    """
    Scrape article/website content using Trafilatura.

    Args:
        url: Website URL

    Returns:
        dict: Article content including title and main text
    """
    extractor = ContentExtractor()
    result = extractor.extract_website_content(url)

    return {
        'title': result['title'],
        'description': result['main_text'],
        'og_image': result['og_image'],
        'type': 'website'
    }


def extract_content(url: str) -> Dict:
    """
    Main function to extract content from any URL.

    Args:
        url: The URL to extract content from

    Returns:
        dict: Extracted content with title and text content
    """
    extractor = ContentExtractor()

    if extractor.is_youtube_url(url):
        result = extractor.extract_youtube_content(url)
        # Normalize output format
        return {
            'url': url,
            'title': result['title'],
            'text_content': result['transcript'],
            'metadata': {
                'channel_name': result['channel_name'],
                'thumbnail': result['thumbnail'],
                'type': 'youtube'
            }
        }
    else:
        result = extractor.extract_website_content(url)
        # Normalize output format
        return {
            'url': url,
            'title': result['title'],
            'text_content': result['main_text'],
            'metadata': {
                'og_image': result['og_image'],
                'type': 'website'
            }
        }


class TextVectorizer:
    """Handles text vectorization using sentence transformers."""

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        """Initialize the vectorizer with a specific model."""
        self.model = SentenceTransformer(model_name)

    def vectorize(self, text: str) -> List[float]:
        """
        Convert text to a vector embedding.

        Args:
            text: The text to vectorize

        Returns:
            list: Vector embedding (384 dimensions for all-MiniLM-L6-v2)
        """
        if not text or not text.strip():
            # Return zero vector for empty text
            return [0.0] * 384

        # Encode the text
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()


# Global vectorizer instance (lazy loaded)
_vectorizer = None


def vectorize(text: str) -> List[float]:
    """
    Convert text to a vector embedding using the default model.

    Args:
        text: The text to vectorize

    Returns:
        list: Vector embedding (384 dimensions)
    """
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = TextVectorizer()
    return _vectorizer.vectorize(text)


if __name__ == "__main__":
    # Example usage
    test_url = "https://www.example.com"

    try:
        content = extract_content(test_url)
        print(f"Title: {content['title']}")
        print(f"Text preview: {content['text_content'][:200]}...")
        print(f"Metadata: {content['metadata']}")

        # Vectorize the content
        vector = vectorize(content['text_content'])
        print(f"\nVector dimensions: {len(vector)}")
        print(f"Vector preview: {vector[:5]}...")

    except Exception as e:
        print(f"Error: {e}")

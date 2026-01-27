"""
Main script to process URLs from test_urls.txt and store them in Supabase.

This script reads URLs from test_urls.txt, extracts their content,
generates vector embeddings, and stores everything in the Supabase database.
"""

import os
import sys
from typing import List, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from tqdm import tqdm
import json

from ingest import extract_content, vectorize


class LinkIngester:
    """Handles the ingestion pipeline from URL to database."""

    def __init__(self, supabase_url: str, supabase_key: str):
        """Initialize the ingester with Supabase credentials."""
        self.supabase: Client = create_client(supabase_url, supabase_key)

    def process_url(self, url: str) -> Optional[dict]:
        """
        Process a single URL: extract content, vectorize, and store in database.

        Args:
            url: The URL to process

        Returns:
            dict: The inserted database record, or None if failed
        """
        try:
            # Extract content
            print(f"Extracting content from: {url}")
            content = extract_content(url)

            # Vectorize the text content
            print(f"Generating vector embedding...")
            vector = vectorize(content['text_content'])

            # Prepare data for database
            data = {
                'url': url,
                'title': content['title'],
                'meta_json': content['metadata'],
                'content_vector': vector
            }

            # Check if URL already exists
            existing = self.supabase.table('links').select('id').eq('url', url).execute()

            if existing.data:
                # Update existing record
                print(f"Updating existing record for: {url}")
                result = self.supabase.table('links').update(data).eq('url', url).execute()
            else:
                # Insert new record
                print(f"Inserting new record for: {url}")
                result = self.supabase.table('links').insert(data).execute()

            print(f"✓ Successfully processed: {url}\n")
            return result.data[0] if result.data else None

        except Exception as e:
            print(f"✗ Error processing {url}: {str(e)}\n")
            return None

    def process_url_file(self, file_path: str) -> dict:
        """
        Process all URLs from a file.

        Args:
            file_path: Path to the file containing URLs (one per line)

        Returns:
            dict: Statistics about the processing
        """
        urls = self._read_urls_from_file(file_path)

        if not urls:
            print(f"No URLs found in {file_path}")
            return {'total': 0, 'success': 0, 'failed': 0}

        print(f"Found {len(urls)} URLs to process\n")
        print("=" * 60)

        success_count = 0
        failed_count = 0

        for url in urls:
            result = self.process_url(url)
            if result:
                success_count += 1
            else:
                failed_count += 1

        print("=" * 60)
        print(f"\nProcessing complete!")
        print(f"Total: {len(urls)} | Success: {success_count} | Failed: {failed_count}")

        return {
            'total': len(urls),
            'success': success_count,
            'failed': failed_count
        }

    @staticmethod
    def _read_urls_from_file(file_path: str) -> List[str]:
        """Read and parse URLs from a text file."""
        urls = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        urls.append(line)
        except FileNotFoundError:
            print(f"Error: File not found: {file_path}")
        except Exception as e:
            print(f"Error reading file: {e}")

        return urls

    def get_stats(self) -> dict:
        """Get statistics about the links database."""
        try:
            # Count total links
            result = self.supabase.table('links').select('id', count='exact').execute()
            total_count = result.count

            # Count by type
            youtube_count = self.supabase.table('links')\
                .select('id', count='exact')\
                .eq('meta_json->>type', 'youtube')\
                .execute().count

            website_count = self.supabase.table('links')\
                .select('id', count='exact')\
                .eq('meta_json->>type', 'website')\
                .execute().count

            return {
                'total': total_count,
                'youtube': youtube_count,
                'websites': website_count
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}


def main():
    """Main entry point for the script."""
    # Load environment variables from .env file
    load_dotenv()

    # Get Supabase credentials from environment
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')

    if not supabase_url or not supabase_key:
        print("Error: Missing Supabase credentials!")
        print("Please set SUPABASE_URL and SUPABASE_KEY in your .env file")
        print("\nExample .env file:")
        print("SUPABASE_URL=https://your-project.supabase.co")
        print("SUPABASE_KEY=your-anon-key")
        sys.exit(1)

    # Initialize ingester
    ingester = LinkIngester(supabase_url, supabase_key)

    # Process URLs from test_urls.txt
    urls_file = 'test_urls.txt'

    if not os.path.exists(urls_file):
        print(f"Error: {urls_file} not found!")
        print("Please create test_urls.txt with one URL per line")
        sys.exit(1)

    # Run the processing
    stats = ingester.process_url_file(urls_file)

    # Display database statistics
    if stats['success'] > 0:
        print("\n" + "=" * 60)
        print("Database Statistics:")
        db_stats = ingester.get_stats()
        for key, value in db_stats.items():
            print(f"  {key.capitalize()}: {value}")


if __name__ == "__main__":
    main()

Phase 1: The "Seed" Strategy (Getting Links)
Before you build the scraper, you need high-quality URLs. Don't try to scrape the "whole web." Start with a curated "Seed Set" of ~500 links to define the vibe of your game.

Where to get them:

Kagi Small Web (RSS): This is your gold mine. It filters for non-commercial, indie blogs.

Feed URL: https://kagi.com/api/v1/smallweb/feed/

Hacker News (Top Stories): Good for tech/science.

API: https://hacker-news.firebaseio.com/v0/topstories.json

Reddit (Curated): Use JSON feeds of specific subreddits (e.g., reddit.com/r/DeepIntoYouTube.json).

Subreddits: r/InternetIsBeautiful, r/ObscureMedia, r/WebGames, r/DataIsBeautiful.

Phase 2: The Ingestion Engine (Backend)
Goal: A Python script that takes a URL, extracts the "Meat" (text/transcript), and turns it into a mathematical Vector.

Tech Stack: Python, beautifulsoup4 (Web), yt-dlp (YouTube), sentence-transformers (Vectors), Supabase (Database).

> Prompt for Claude (Copy/Paste this):
I need to build the backend for a link discovery game. Please write a Python module called ingest.py that does the following:

Setup: Uses beautifulsoup4 for HTML and yt-dlp for YouTube.

Function extract_content(url):

If it's a YouTube URL: Extract the video Title, Channel Name, and the Auto-Generated Captions (transcript) using yt-dlp.

If it's a Website: Extract the OpenGraph Title/Image and the main body text (strip nav/ads).

Function vectorize(text):

Use the sentence-transformers library (model: all-MiniLM-L6-v2) to convert the extracted text into a vector embedding.

Database:

Write a Supabase (PostgreSQL) schema that includes a table links with columns: id, url, title, meta_json, content_vector (using pgvector), and comment_vector.

Please provide the full Python code and the SQL to set up the database.

Phase 3: The "Compass" Logic (The Brain)
Goal: The logic that decides which links appear in your 5 slots (Deep Dive vs. Pivot).

> Prompt for Claude:
Now I need the logic to find related links. Create a Python class LinkCompass with a method get_compass(current_link_id) that returns 5 specific links:

Slots 1 & 2 (Deep Dive): Query the database for the 2 nearest neighbors to the current link's vector (lowest cosine distance).

Slots 3 & 4 (Pivot): Query for the top 50 matches, but skip the top 10. Pick 2 random links from ranks 11–50. (This finds related but distinct content).

Slot 5 (Wildcard): Pick a completely random link from the database.

Bonus: Add a method analyze_comments(comments_list) that takes a list of user comments, vectorizes them using the same model, and averages them to create a comment_vector. Update the links table to store this.

Phase 4: The Game Client (Frontend)
Goal: A web app where the user "plays" the browser.

Tech Stack: Next.js (React), Tailwind CSS.

> Prompt for Claude:
Scaffold a Next.js application for the frontend. I need a main component called GameBrowser:

Layout: A full-screen interface.

Center: A generic <iframe> that displays the current active_url.

Overlay: A floating HUD (Heads Up Display) at the bottom.

The HUD:

Display the current Link Title.

Show 5 large "Directional" buttons corresponding to the Compass slots (Down Arrows for Deep Dive, Right Arrows for Pivot, Star for Wildcard).

When a button is clicked, fetch the next link from the backend and update the iframe.

Gamification:

Add a visual "Energy Bar" at the top that decreases by 10% every time the user moves to a new link.

Add a "Recharge" button that simulates a cooldown or "mining" action.

Order of Operations
Run Phase 2 first. Get the database set up and the script running.

Feed the machine. Manually run the script on 10–20 URLs from the "Seed Sources" to populate your database so you have data to test.

Run Phase 3. Test that the "Compass" actually returns related links.

Run Phase 4. Build the UI last.
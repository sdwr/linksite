"""
Simple web server to display links from the Supabase database.
"""

import os
from flask import Flask, render_template_string
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Supabase client
supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_KEY')
)

# HTML template
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Link Discovery - Top 50 Links</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 10px;
        }
        .stats {
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stats p {
            margin: 5px 0;
            color: #666;
        }
        .error {
            background: #ffebee;
            color: #c62828;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #c62828;
        }
        .warning {
            background: #fff3cd;
            color: #856404;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #ffc107;
        }
        .link-list {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .link-item {
            padding: 15px 20px;
            border-bottom: 1px solid #eee;
            transition: background-color 0.2s;
        }
        .link-item:hover {
            background-color: #f9f9f9;
        }
        .link-item:last-child {
            border-bottom: none;
        }
        .link-number {
            display: inline-block;
            width: 40px;
            color: #999;
            font-weight: bold;
        }
        .link-title {
            font-size: 16px;
            font-weight: 500;
            color: #1a73e8;
            margin-bottom: 5px;
        }
        .link-url {
            font-size: 13px;
            color: #5f6368;
            word-break: break-all;
        }
        .link-meta {
            font-size: 12px;
            color: #999;
            margin-top: 5px;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            margin-right: 8px;
            font-weight: 500;
        }
        .badge-youtube {
            background: #ff0000;
            color: white;
        }
        .badge-website {
            background: #4CAF50;
            color: white;
        }
        a {
            color: inherit;
            text-decoration: none;
        }
        a:hover .link-title {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <h1>🔗 Link Discovery - Top 50 Links</h1>

    {% if error %}
    <div class="error">
        <strong>Error:</strong> {{ error }}
        {% if setup_instructions %}
        <br><br>
        <strong>Setup Instructions:</strong><br>
        1. Go to your Supabase project dashboard<br>
        2. Navigate to SQL Editor<br>
        3. Run the contents of <code>schema.sql</code> to create the database table<br>
        4. Run <code>python process_urls.py</code> to populate the database
        {% endif %}
    </div>
    {% endif %}

    {% if warning %}
    <div class="warning">
        <strong>Note:</strong> {{ warning }}
    </div>
    {% endif %}

    {% if stats %}
    <div class="stats">
        <p><strong>Total Links:</strong> {{ stats.total }}</p>
        <p><strong>YouTube Videos:</strong> {{ stats.youtube }}</p>
        <p><strong>Websites:</strong> {{ stats.websites }}</p>
    </div>
    {% endif %}

    {% if links %}
    <div class="link-list">
        {% for link in links %}
        <div class="link-item">
            <span class="link-number">{{ loop.index }}.</span>
            <a href="{{ link.url }}" target="_blank">
                <div class="link-title">{{ link.title or 'Untitled' }}</div>
                <div class="link-url">{{ link.url }}</div>
                <div class="link-meta">
                    {% if link.meta_json and link.meta_json.type %}
                    <span class="badge badge-{{ link.meta_json.type }}">{{ link.meta_json.type }}</span>
                    {% endif %}
                    {% if link.meta_json and link.meta_json.channel_name %}
                    Channel: {{ link.meta_json.channel_name }}
                    {% endif %}
                    <span style="margin-left: 10px;">Added: {{ link.created_at[:10] if link.created_at else 'N/A' }}</span>
                </div>
            </a>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</body>
</html>
"""

@app.route('/')
def index():
    try:
        # Try to fetch links from database
        response = supabase.table('links').select('*').order('created_at', desc=True).limit(50).execute()

        links = response.data if response.data else []

        # Get stats
        stats = None
        if links:
            stats = {
                'total': len(links),
                'youtube': sum(1 for link in links if link.get('meta_json', {}).get('type') == 'youtube'),
                'websites': sum(1 for link in links if link.get('meta_json', {}).get('type') == 'website')
            }

        warning = None
        if not links:
            warning = "No links found in the database. Run 'python process_urls.py' to add links."

        return render_template_string(TEMPLATE, links=links, stats=stats, warning=warning, error=None, setup_instructions=False)

    except Exception as e:
        error_msg = str(e)
        setup_needed = 'PGRST205' in error_msg or 'table' in error_msg.lower()

        return render_template_string(
            TEMPLATE,
            links=[],
            stats=None,
            warning=None,
            error=error_msg,
            setup_instructions=setup_needed
        )

if __name__ == '__main__':
    # Run on all interfaces so it's accessible from the web
    # Use PORT environment variable (set by Fly.io) or default to 8080
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)

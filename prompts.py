"""
AI Content Engine â€” Prompt Templates

Each prompt is a function that takes context and returns a formatted string.
This keeps prompts testable and versionable.
"""

# ============================================================
# Discovery Prompts
# ============================================================

def discovery_filter_prompt(topic: str, search_results: list[dict]) -> str:
    """Given search results, pick the most interesting/novel links."""
    results_text = "\n".join(
        f"- [{r.get('title', 'Untitled')}]({r.get('url', '')})\n  {r.get('snippet', '')}"
        for r in search_results
    )

    return f"""You are a link curator for a tech/culture discussion site. Your job is to find interesting, discussion-worthy links.

Topic: {topic}

Here are search results to evaluate:

{results_text}

For each result, decide if it's worth adding to the site. A good link is:
- Substantive (not just a press release or fluff piece)
- Discussion-worthy (people would have opinions about it)
- Not paywalled or login-gated (prefer open access)
- Recent and relevant

Return a JSON array of the best links (up to 10). For each:
```json
[
  {{
    "url": "https://...",
    "title": "...",
    "reason": "Why this is interesting (1 sentence)",
    "quality": 1-10
  }}
]
```

Only include links with quality >= 6. Return `[]` if nothing is good enough.
Return ONLY the JSON array, no other text."""


def discovery_hn_prompt(items: list[dict]) -> str:
    """Filter HN frontpage items for the most discussion-worthy."""
    items_text = "\n".join(
        f"- {i.get('title', '?')} ({i.get('score', 0)} pts, {i.get('descendants', 0)} comments)\n  {i.get('url', 'no url')}"
        for i in items
    )

    return f"""You are curating links from Hacker News for a link discussion site.

Current HN frontpage:

{items_text}

Pick the 5-10 most interesting links that would spark good discussion. Prefer:
- Original content (not "Show HN" unless exceptional)
- Technical depth
- Surprising or counterintuitive findings
- Broad appeal (not just niche tooling)

Return a JSON array:
```json
[
  {{
    "url": "https://...",
    "title": "...",
    "reason": "Why this is interesting",
    "quality": 1-10
  }}
]
```

Return ONLY the JSON array, no other text."""


# ============================================================
# Enrichment Prompts
# ============================================================

def description_prompt(title: str, url: str, content: str) -> str:
    """Generate a concise description for a link."""
    content_preview = content[:3000] if content else "(no content extracted)"

    return f"""Write a concise, informative description (2-3 sentences) for this link. 
Be factual and specific. Don't use marketing language or superlatives.
If the content is a video, describe what it covers.

Title: {title}
URL: {url}
Content preview:
{content_preview}

Return ONLY the description text, nothing else."""


def technical_analysis_prompt(title: str, url: str, content: str) -> str:
    """Deep technical analysis of a link's content."""
    content_preview = content[:4000] if content else "(no content extracted)"

    return f"""You are a technical analyst. Write an insightful technical comment about this link.

Focus on:
- What's technically novel or interesting
- How it works at a high level
- What problems it solves and what tradeoffs it makes
- Relevant technical context a reader should know

Title: {title}
URL: {url}
Content:
{content_preview}

Write 2-4 paragraphs. Be specific and substantive â€” no vague praise. 
If you don't have enough information for a real technical analysis, say so briefly and focus on what you can observe.
Return ONLY the comment text."""


def business_analysis_prompt(title: str, url: str, content: str) -> str:
    """Business and market implications analysis."""
    content_preview = content[:3000] if content else "(no content extracted)"

    return f"""You are a business analyst. Write a brief comment analyzing the business/market implications of this link.

Consider:
- Who benefits from this? Who loses?
- Market size and competitive landscape
- Timing â€” why now?
- What's the business model (if applicable)?

Title: {title}
URL: {url}
Content:
{content_preview}

Write 1-3 paragraphs. Be specific and analytical. Avoid generic business jargon.
If the content isn't business-relevant, write a brief note about its broader impact instead.
Return ONLY the comment text."""


def contrarian_prompt(title: str, url: str, content: str) -> str:
    """Devil's advocate / contrarian perspective."""
    content_preview = content[:3000] if content else "(no content extracted)"

    return f"""You are a thoughtful contrarian. Write a comment that pushes back on the main thesis of this link.

Your role:
- Find the weakest assumptions and challenge them
- Consider failure modes and unintended consequences
- Ask the questions that cheerleaders don't
- Be constructive â€” propose alternatives, don't just criticize

Title: {title}
URL: {url}
Content:
{content_preview}

Write 1-3 paragraphs. Be intellectually honest â€” if the content is genuinely solid, acknowledge that and focus on edge cases or missing considerations.
Return ONLY the comment text."""


def summary_prompt(title: str, url: str, content: str) -> str:
    """TL;DR summary."""
    content_preview = content[:4000] if content else "(no content extracted)"

    return f"""Write a TL;DR summary of this link in 1-2 sentences. Be specific â€” include key facts, numbers, or conclusions.

Title: {title}
URL: {url}
Content:
{content_preview}

Return ONLY the summary text (1-2 sentences), nothing else."""


def tag_suggestions_prompt(title: str, url: str, content: str, existing_tags: list[str] = None) -> str:
    """Suggest relevant tags for a link."""
    content_preview = content[:2000] if content else "(no content extracted)"
    existing = ", ".join(existing_tags) if existing_tags else "none"

    return f"""Suggest 3-7 tags for this link. Tags should be:
- Lowercase, hyphenated (e.g., "machine-learning", "open-source")
- Specific enough to be useful (not just "technology")
- A mix of topic tags and format tags (e.g., "research-paper", "tutorial")

Title: {title}
URL: {url}
Content preview:
{content_preview}

Existing tags on this link: {existing}
Don't duplicate existing tags.

Return a JSON array of tag strings:
```json
["tag-one", "tag-two", "tag-three"]
```

Return ONLY the JSON array, no other text."""


def related_links_prompt(target_title: str, target_content: str, candidate_links: list[dict]) -> str:
    """Identify which candidate links are most related to the target."""
    candidates_text = "\n".join(
        f"- ID {c['id']}: {c.get('title', '?')} â€” {(c.get('description') or c.get('content') or '')[:200]}"
        for c in candidate_links
    )

    return f"""Given a target link and a list of candidates, identify the 3-5 most related links.

Target link:
Title: {target_title}
Content: {target_content[:2000]}

Candidates:
{candidates_text}

Return a JSON array of objects with the candidate ID and a brief reason:
```json
[
  {{"id": 123, "reason": "Both discuss transformer architecture scaling"}}
]
```

Return ONLY the JSON array, no other text."""


# ============================================================
# Comment Author Personas
# ============================================================

PERSONAS = {
    "technical": {
        "author": "ai-technical",
        "prompt_fn": technical_analysis_prompt,
        "model": "sonnet",
        "description": "Deep technical analysis",
    },
    "business": {
        "author": "ai-business",
        "prompt_fn": business_analysis_prompt,
        "model": "haiku",
        "description": "Business/market implications",
    },
    "contrarian": {
        "author": "ai-contrarian",
        "prompt_fn": contrarian_prompt,
        "model": "sonnet",
        "description": "Devil's advocate perspective",
    },
    "summary": {
        "author": "ai-summary",
        "prompt_fn": summary_prompt,
        "model": "haiku",
        "description": "TL;DR summary",
    },
}

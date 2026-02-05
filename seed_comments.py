#!/usr/bin/env python3
"""
Seed comments for linksite using AI-generated personas.
Uses Claude Sonnet (claude-3-5-sonnet-20241022) for generating comments.
"""

import os
import random
import time
import anthropic
from db import execute, query

# === Configuration ===

CLAUDE_MODEL = "claude-3-5-sonnet-20241022"

# User IDs from existing users table
USER_IDS = [
    "1ab945e3-0adb-4faa-8c12-8453dc92d10c",  # JollyPangolin74
    "cbf1f9f6-7a0c-4e0c-b2cd-95d10778f233",  # MightyOwl28
    "e3bdfcc0-301f-4b56-ac3a-8ec837921740",  # RusticHedgehog35
    "6898ff29-dd7b-4f76-aeef-83f5b4f9f4f7",  # DizzyOwl77
    "00664f1a-a207-4c06-bb62-95a471219679",  # CheekyNarwhal79
    "286deecd-b3e1-43e2-9d9e-8b5f1da09694",  # LuckyMeerkat79
    "c4ac1688-e3e5-4f54-a0f9-defe1a04c49d",  # BraveDolphin11
    "39354fae-28de-479c-a1ab-4be93269b0ae",  # WildLemur82
    "d96115b9-1e4e-47b8-9915-4c9117666502",  # MightyLlama70
    "97c6c199-e161-417f-ac2f-db70cd54a7bc",  # LazyHawk25
]

# Links with summaries to generate comments for
LINKS = [
    {
        "id": 229,
        "title": "You can code only 4 hours per day. Here's why.",
        "summary": "Research backs what developers feel: the cognitive ceiling for deep work is 3-4 hours daily."
    },
    {
        "id": 195,
        "title": "National Pigeon Service - Wikipedia",
        "summary": "Britain's National Pigeon Service contributed 200,000 birds to WWII, 16,554 parachuted onto the continent."
    },
    {
        "id": 176,
        "title": "Superlinear Returns (Paul Graham)",
        "summary": "Paul Graham identifies two sources of superlinear returns: exponential growth and thresholds (winner-take-all)."
    },
    {
        "id": 230,
        "title": "The cults of TDD and GenAI",
        "summary": "Drew DeVault argues that TDD and coding agents exploit the same psychological reflex: both let mediocre programmers feel like great ones."
    },
    {
        "id": 241,
        "title": "From Microsoft to Microslop to Linux",
        "summary": "A 20-year Windows user finally snapped after 24H2 introduced unfixable Chrome rendering bugs."
    },
    {
        "id": 234,
        "title": "C++ Modules are here to stay",
        "summary": "C++20 modules eliminate the #include directive, providing 8.6x compile speedup."
    },
    {
        "id": 239,
        "title": "Rust at Scale: WhatsApp",
        "summary": "WhatsApp rewrote their media validation library from 160,000 lines of C++ to 90,000 lines of Rust."
    },
    {
        "id": 235,
        "title": "Cuttlefish: Coordination-free distributed",
        "summary": "Cuttlefish achieves 286ns admission latency by exploiting commutative operations."
    },
    {
        "id": 226,
        "title": "The teammate who asks too many questions",
        "summary": "The teammate who asks 'obvious' questions is catching blind spots before they become costly mistakes."
    },
]

# === Persona Styles & Filters ===

STYLES = {
    "Laconic": {
        "weight": 25,
        "rules": "One sentence max. Gut reaction. No setup. Profanity/slang OK."
    },
    "Mobile": {
        "weight": 15,
        "rules": "All lowercase. Minimal punctuation. Maybe one common typo (its/it's, your/you're, could of). No effort to be coherent."
    },
    "Anecdotal": {
        "weight": 20,
        "rules": "Tell a micro-story. Include: year, specific person (cousin, uncle, coworker), specific failure or detail. End on the detail, not a lesson."
    },
    "Chaos": {
        "weight": 15,
        "rules": "Messy paragraph OR one word. Parentheticals, em-dashes, trailing off. End with 'anyway' or 'idk' or '...' — never a conclusion."
    },
    "Fragmented": {
        "weight": 15,
        "rules": "Short clipped sentences. Spiral into a specific rabbit hole. Show distraction."
    },
    "Flowing": {
        "weight": 10,
        "rules": "One continuous thought with self-interruption. Get tangled in your own reasoning. Don't resolve it."
    },
}

FILTERS = {
    "Pragmatist": {
        "weight": 25,
        "focus": "Reality vs. hype. Will this ship? Is it a demo? Pricing tiers. Skepticism about claims."
    },
    "Failure-Hunter": {
        "weight": 20,
        "focus": "Entropy. How it will break, why it failed in the past, specific scars."
    },
    "Social Critic": {
        "weight": 20,
        "focus": "Human dynamics. Loneliness, cringe, how people treat each other, social exhaustion."
    },
    "Optimizer": {
        "weight": 15,
        "focus": "Fixate on waste, efficiency, hidden costs, battery life, GPU burn, time-sinks."
    },
    "Localizer": {
        "weight": 10,
        "focus": "Physical impact. Noise, neighbors, safety, 'where would I put this.'"
    },
    "Specialist": {
        "weight": 10,
        "focus": "Technical minutiae. One specific spec, jargon, mechanics. Ignore the big picture."
    },
}


def weighted_choice(options: dict) -> str:
    """Pick an option based on weights."""
    items = list(options.keys())
    weights = [options[k]["weight"] for k in items]
    return random.choices(items, weights=weights, k=1)[0]


def generate_comment(client: anthropic.Anthropic, title: str, summary: str, style: str, filter_name: str) -> str:
    """Generate a single comment using Claude Sonnet."""
    style_rules = STYLES[style]["rules"]
    filter_focus = FILTERS[filter_name]["focus"]
    
    prompt = f"""You are writing a comment on a link aggregator.

Style: {style}
Style rules: {style_rules}

Filter: {filter_name}
Filter focus: {filter_focus}

Link title: "{title}"
Summary: "{summary}"

Rules:
- Use the style specified exactly
- End on a hanging detail, not a conclusion
- No summaries, no "in conclusion," no restating the headline
- React to the summary content, not just the title
- Be authentic to how real internet users comment

Write ONE comment, nothing else."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text.strip()


def generate_reply(client: anthropic.Anthropic, original_comment: str, title: str, summary: str, style: str, filter_name: str) -> str:
    """Generate a reply to an existing comment."""
    style_rules = STYLES[style]["rules"]
    filter_focus = FILTERS[filter_name]["focus"]
    
    prompt = f"""You are writing a reply to a comment on a link aggregator.

Style: {style}
Style rules: {style_rules}

Filter: {filter_name}
Filter focus: {filter_focus}

Original article title: "{title}"
Original article summary: "{summary}"

Comment you're replying to:
"{original_comment}"

Rules:
- Reply to the comment, not the article directly
- Use the style specified exactly
- End on a hanging detail, not a conclusion
- Be authentic to how real internet users reply
- Can agree, disagree, add context, or go on a tangent

Write ONE reply, nothing else."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text.strip()


def insert_comment(link_id: int, user_id: str, content: str, parent_id: int = None) -> int:
    """Insert a comment into the database and return its ID."""
    if parent_id:
        result = execute(
            """
            INSERT INTO comments (link_id, user_id, content, parent_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (link_id, user_id, content, parent_id)
        )
    else:
        result = execute(
            """
            INSERT INTO comments (link_id, user_id, content)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (link_id, user_id, content)
        )
    return result[0]["id"] if result else None


def main():
    # Initialize Anthropic client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable required")
        return
    
    client = anthropic.Anthropic(api_key=api_key)
    
    stats = {}
    total_comments = 0
    total_replies = 0
    
    for link in LINKS:
        link_id = link["id"]
        title = link["title"]
        summary = link["summary"]
        
        # Random number of comments (3-10)
        num_comments = random.randint(3, 10)
        link_stats = {"comments": 0, "replies": 0}
        
        print(f"\n=== Link {link_id}: {title[:50]}... ===")
        print(f"Generating {num_comments} comments...")
        
        generated_comments = []  # Track (comment_id, content, user_id) for potential replies
        
        for i in range(num_comments):
            # Pick random style and filter
            style = weighted_choice(STYLES)
            filter_name = weighted_choice(FILTERS)
            
            # Pick random user (different from recent ones if possible)
            used_users = [c[2] for c in generated_comments[-3:]] if generated_comments else []
            available_users = [u for u in USER_IDS if u not in used_users] or USER_IDS
            user_id = random.choice(available_users)
            
            try:
                # Generate comment
                content = generate_comment(client, title, summary, style, filter_name)
                
                # Insert into database
                comment_id = insert_comment(link_id, user_id, content)
                
                if comment_id:
                    generated_comments.append((comment_id, content, user_id))
                    link_stats["comments"] += 1
                    print(f"  [{i+1}] {style} + {filter_name}: {content[:60]}...")
                
                # Small delay to avoid rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  Error generating comment {i+1}: {e}")
        
        # Generate replies for 20-30% of comments
        reply_chance = random.uniform(0.2, 0.3)
        for comment_id, original_content, original_user in generated_comments:
            if random.random() < reply_chance:
                # 1-3 replies per comment
                num_replies = random.randint(1, 3)
                
                for r in range(num_replies):
                    # Pick different user for reply
                    reply_user = random.choice([u for u in USER_IDS if u != original_user])
                    
                    # Pick random style and filter for reply
                    style = weighted_choice(STYLES)
                    filter_name = weighted_choice(FILTERS)
                    
                    try:
                        reply_content = generate_reply(client, original_content, title, summary, style, filter_name)
                        reply_id = insert_comment(link_id, reply_user, reply_content, parent_id=comment_id)
                        
                        if reply_id:
                            link_stats["replies"] += 1
                            print(f"    -> Reply: {reply_content[:50]}...")
                        
                        time.sleep(0.5)
                        
                    except Exception as e:
                        print(f"    Error generating reply: {e}")
        
        stats[link_id] = link_stats
        total_comments += link_stats["comments"]
        total_replies += link_stats["replies"]
        print(f"  Link {link_id}: {link_stats['comments']} comments, {link_stats['replies']} replies")
    
    # Final summary
    print("\n" + "=" * 50)
    print("SEED COMPLETE")
    print("=" * 50)
    print(f"Total comments: {total_comments}")
    print(f"Total replies: {total_replies}")
    print(f"Grand total: {total_comments + total_replies}")
    print("\nPer-link breakdown:")
    for link_id, s in stats.items():
        print(f"  Link {link_id}: {s['comments']} comments, {s['replies']} replies")


if __name__ == "__main__":
    main()

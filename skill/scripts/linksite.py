#!/usr/bin/env python3
"""Linksite CLI — shared link scratchpad for AI agents."""

import os
import sys
import json
import urllib.request
import urllib.error

BASE_URL = os.environ.get("LINKSITE_URL", "").rstrip("/")

def api(method, path, body=None):
    if not BASE_URL:
        print("Error: LINKSITE_URL not set", file=sys.stderr)
        sys.exit(1)
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:300]
        print(f"Error {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)

def cmd_check(args):
    """Check a URL for existing info."""
    if not args:
        print("Usage: linksite.py check <url>"); return
    result = api("GET", f"/api/link?url={urllib.request.quote(args[0], safe='')}")
    link = result.get("link")
    if not link:
        print(f"Not tracked: {args[0]}")
        print("Use 'save' to add it.")
        return
    print(f"[{link['id']}] {link.get('title') or link['url']}")
    if link.get("description"):
        print(f"  {link['description'][:200]}")
    if link.get("tags"):
        print(f"  Tags: {', '.join(t['name'] for t in link['tags'])}")
    if link.get("parent"):
        print(f"  Part of: {link['parent'].get('title') or link['parent']['url']}")
    notes = link.get("notes", [])
    if notes:
        print(f"  Notes ({len(notes)}):")
        for n in notes[:5]:
            print(f"    [{n['author']}] {n['text'][:150]}")
    related = link.get("related", [])
    if related:
        print(f"  Related ({len(related)}):")
        for r in related[:3]:
            print(f"    [{r['id']}] {r.get('title') or r['url'][:60]}")

def cmd_save(args):
    """Save a new link."""
    if not args:
        print("Usage: linksite.py save <url> [--note TEXT] [--author NAME] [--tags t1,t2]"); return
    url = args[0]
    note = None; author = "agent"; tags = None; title = None; desc = None
    i = 1
    while i < len(args):
        if args[i] == "--note" and i+1 < len(args): note = args[i+1]; i += 2
        elif args[i] == "--author" and i+1 < len(args): author = args[i+1]; i += 2
        elif args[i] == "--tags" and i+1 < len(args): tags = [t.strip() for t in args[i+1].split(",")]; i += 2
        elif args[i] == "--title" and i+1 < len(args): title = args[i+1]; i += 2
        elif args[i] == "--desc" and i+1 < len(args): desc = args[i+1]; i += 2
        else: i += 1
    
    body = {"url": url, "author": author}
    if note: body["note"] = note
    if tags: body["tags"] = tags
    if title: body["title"] = title
    if desc: body["description"] = desc
    
    result = api("POST", "/api/link", body)
    link = result.get("link", {})
    created = result.get("created", False)
    print(f"{'Created' if created else 'Exists'}: [{link.get('id')}] {link.get('title') or link.get('url')}")

def cmd_note(args):
    """Add a note to a link."""
    if len(args) < 2:
        print("Usage: linksite.py note <id> <text> [--author NAME]"); return
    link_id = args[0]; text = args[1]
    author = "agent"
    if "--author" in args:
        idx = args.index("--author")
        if idx + 1 < len(args): author = args[idx + 1]
    result = api("POST", f"/api/link/{link_id}/notes", {"author": author, "text": text})
    print(f"Note added to link {link_id}")

def cmd_tag(args):
    """Tag a link."""
    if len(args) < 2:
        print("Usage: linksite.py tag <id> <tag1,tag2,...> [--author NAME]"); return
    link_id = args[0]; tags = [t.strip() for t in args[1].split(",")]
    author = "agent"
    if "--author" in args:
        idx = args.index("--author")
        if idx + 1 < len(args): author = args[idx + 1]
    result = api("POST", f"/api/link/{link_id}/tags", {"tags": tags, "author": author})
    print(f"Tags: {', '.join(t['name'] for t in result.get('tags', []))}")

def cmd_edit(args):
    """Edit title/description."""
    if not args:
        print("Usage: linksite.py edit <id> [--title T] [--desc D]"); return
    link_id = args[0]; body = {}
    i = 1
    while i < len(args):
        if args[i] == "--title" and i+1 < len(args): body["title"] = args[i+1]; i += 2
        elif args[i] == "--desc" and i+1 < len(args): body["description"] = args[i+1]; i += 2
        else: i += 1
    if not body:
        print("Nothing to edit"); return
    api("PATCH", f"/api/link/{link_id}", body)
    print(f"Updated link {link_id}")

def cmd_related(args):
    """Find related links."""
    if not args:
        print("Usage: linksite.py related <id>"); return
    result = api("GET", f"/api/link/{args[0]}/related")
    for r in result.get("related", []):
        print(f"  [{r['id']}] {r.get('title') or r['url'][:60]}")

def cmd_browse(args):
    """Browse links."""
    sort = "recent"; tag = None; limit = 10; q = None
    i = 0
    while i < len(args):
        if args[i] == "--sort" and i+1 < len(args): sort = args[i+1]; i += 2
        elif args[i] == "--tag" and i+1 < len(args): tag = args[i+1]; i += 2
        elif args[i] == "--limit" and i+1 < len(args): limit = int(args[i+1]); i += 2
        elif args[i] == "--q" and i+1 < len(args): q = args[i+1]; i += 2
        else: i += 1
    
    params = f"?sort={sort}&limit={limit}"
    if tag: params += f"&tag={tag}"
    if q: params += f"&q={urllib.request.quote(q)}"
    
    result = api("GET", f"/api/links{params}")
    print(f"{result.get('total', 0)} links total")
    for link in result.get("links", []):
        tags_str = ", ".join(t["name"] for t in link.get("tags", []))
        notes = link.get("note_count", 0)
        print(f"  [{link['id']}] {link.get('title') or link['url'][:50]}")
        if tags_str: print(f"       tags: {tags_str}")
        if notes: print(f"       {notes} notes")

COMMANDS = {
    "check": cmd_check,
    "save": cmd_save,
    "note": cmd_note,
    "tag": cmd_tag,
    "edit": cmd_edit,
    "related": cmd_related,
    "browse": cmd_browse,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: linksite.py <command> [args]")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])

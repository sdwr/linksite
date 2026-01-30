"""
director_fix.py -- Patch the _adjust_timers bug in director.py

The bug: _adjust_timers ends after the skip check with NO timer adjustment code.
A partial sed deleted the old block but didn't insert the replacement.

This script reads director.py, finds the end of _adjust_timers, and appends the
missing timer adjustment block.

Usage:
    python3 director_fix.py              # dry-run (prints patched output)
    python3 director_fix.py --apply      # writes patched file in-place
"""

import sys
import re

DIRECTOR_PATH = "/home/sprite/linksite/director.py"

# The code block to insert at the end of _adjust_timers, right after the skip check.
# This goes after the "return" inside the skip-threshold block.
PATCH_BLOCK = '''
        # Calculate adjusted end time from BASE, not current_end (avoids accumulating bonus every tick)
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        base_duration = self.get_weight("rotation_default_sec", 120)
        base_end = started + timedelta(seconds=base_duration)
        adjusted = base_end + timedelta(seconds=bonus - penalty)

        if adjusted != datetime.fromisoformat(state["current_end"].replace("Z", "+00:00")):
            self.db.table("director_state").update({
                "current_end": adjusted.isoformat()
            }).eq("id", state["id"]).execute()
'''


def patch(source: str) -> str:
    """Find _adjust_timers and append the missing timer block."""

    # Strategy: find the last line of _adjust_timers.
    # The method currently ends with:
    #     if any(count >= skip_threshold for count in user_downvotes.values()):
    #         print(f"[Director] Skip triggered by user downvotes on link {link_id}")
    #         await self._rotate(now)
    #         return
    #
    # After that "return", the method just ends (no timer code).
    # We need to insert our block after that return statement, still inside _adjust_timers.

    # Find the _adjust_timers method
    marker = "async def _adjust_timers(self, state: dict, now: datetime):"
    if marker not in source:
        print("ERROR: Could not find _adjust_timers method signature", file=sys.stderr)
        sys.exit(1)

    # Check if patch is already applied
    if "base_end = started + timedelta(seconds=base_duration)" in source:
        print("Patch already applied. No changes needed.", file=sys.stderr)
        return source

    # Find the skip return block -- this is the last meaningful code in _adjust_timers
    # We look for the pattern ending with "await self._rotate(now)\n            return"
    # that's inside _adjust_timers
    skip_pattern = re.compile(
        r'(            await self\._rotate\(now\)\n            return\n)',
        re.MULTILINE
    )

    # Find _adjust_timers start position
    method_start = source.index(marker)

    # Find the next method definition after _adjust_timers (to know the boundary)
    next_method = re.search(r'\n    # ---.*?---|\n    async def (?!_adjust_timers)', source[method_start + 10:])
    if next_method:
        method_end = method_start + 10 + next_method.start()
    else:
        method_end = len(source)

    method_body = source[method_start:method_end]

    # Find the last "return" in the skip block within this method
    matches = list(skip_pattern.finditer(method_body))
    if not matches:
        # Fallback: just find the end of the method and insert before it
        print("WARNING: Could not find skip-return pattern, inserting at method end", file=sys.stderr)
        insert_pos = method_end
        return source[:insert_pos] + PATCH_BLOCK + "\n" + source[insert_pos:]

    last_match = matches[-1]
    # Insert position: right after the "return\n" of the skip block
    insert_pos_in_method = last_match.end()
    insert_pos = method_start + insert_pos_in_method

    patched = source[:insert_pos] + PATCH_BLOCK + source[insert_pos:]
    return patched


def main():
    apply = "--apply" in sys.argv
    path = DIRECTOR_PATH

    # Allow overriding path for local testing
    for arg in sys.argv[1:]:
        if not arg.startswith("--") and arg.endswith(".py"):
            path = arg

    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    patched = patch(source)

    if apply:
        with open(path, "w", encoding="utf-8") as f:
            f.write(patched)
        print(f"Patched {path} in-place.")
    else:
        print("=== DRY RUN === (use --apply to write)")
        print(patched)


if __name__ == "__main__":
    main()

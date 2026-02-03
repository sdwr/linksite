"""
The Director -- async brain that selects which link to show.

Runs as an asyncio task inside the FastAPI process.
Handles: link selection, satellite generation, timer adjustment, score propagation.
Now also: nomination-aware rotation and event broadcasting.
"""

import asyncio
import random
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable
# db_compat provides the same .table() API as supabase Client


class Director:
    def __init__(self, supabase, broadcast_fn: Callable = None):
        self.db = supabase
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._rotation_count = 0
        self._broadcast = broadcast_fn or (lambda e: None)

    # --- Lifecycle ----------------------------------------

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        print("[Director] Started")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        print("[Director] Stopped")

    def skip(self):
        """Force immediate rotation."""
        now = datetime.now(timezone.utc)
        self.db.table("global_state").update({
            "rotation_ends_at": now.isoformat()
        }).eq("id", 1).execute()
        print("[Director] Skip requested")

    # --- Config -------------------------------------------

    def get_weight(self, key: str, default: float = 0.0) -> float:
        try:
            resp = self.db.table("score_weights").select("value").eq("key", key).execute()
            if resp.data:
                return float(resp.data[0]["value"])
        except Exception:
            pass
        return default

    # --- Main Loop ----------------------------------------

    async def _loop(self):
        print("[Director] Loop started")
        while self.running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Director] Error in tick: {e}")
            await asyncio.sleep(2)
        print("[Director] Loop ended")

    async def _tick(self):
        now = datetime.now(timezone.utc)
        state = self._get_state()

        if not state or not state.get("current_link_id"):
            # No link selected yet -- pick one immediately
            await self._rotate(now)
            return

        rotation_ends = state.get("rotation_ends_at")
        if rotation_ends:
            ends_at = datetime.fromisoformat(rotation_ends.replace("Z", "+00:00"))
            if now < ends_at:
                # Still showing -- adjust timers based on votes
                await self._adjust_timers(state, now)
                return

        # Time to rotate
        await self._rotate(now)

    # --- State --------------------------------------------

    def _get_state(self) -> Optional[dict]:
        resp = self.db.table("global_state").select("*").eq("id", 1).execute()
        return resp.data[0] if resp.data else None

    # --- Timer Adjustment ---------------------------------

    async def _adjust_timers(self, state: dict, now: datetime):
        link_id = state["current_link_id"]
        started_at = state.get("started_at", now.isoformat())

        # Get votes since this link started showing
        resp = self.db.table("votes").select("*").eq(
            "link_id", link_id
        ).gte("created_at", started_at).execute()
        votes = resp.data or []

        if not votes:
            return

        upvotes = sum(1 for v in votes if v["value"] == 1)
        downvotes = sum(1 for v in votes if v["value"] == -1)

        bonus = upvotes * self.get_weight("upvote_time_bonus_sec", 15)
        penalty = downvotes * self.get_weight("downvote_time_penalty_sec", 20)

        # Check per-user downvote skip
        skip_threshold = int(self.get_weight("downvote_skip_threshold", 3))
        user_downvotes: dict = {}
        for v in votes:
            if v["value"] == -1:
                uid = v["user_id"]
                user_downvotes[uid] = user_downvotes.get(uid, 0) + 1

        if any(count >= skip_threshold for count in user_downvotes.values()):
            print(f"[Director] Skip triggered by user downvotes on link {link_id}")
            await self._rotate(now)
            return

        # Calculate adjusted end time from BASE, not current_end (avoids accumulating bonus every tick)
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        base_duration = self.get_weight("rotation_default_sec", 120)
        base_end = started + timedelta(seconds=base_duration)
        adjusted = base_end + timedelta(seconds=bonus - penalty)

        # Update rotation_ends_at if changed
        current_ends = state.get("rotation_ends_at")
        if current_ends:
            current_ends_dt = datetime.fromisoformat(current_ends.replace("Z", "+00:00"))
            if abs((adjusted - current_ends_dt).total_seconds()) > 1:
                self.db.table("global_state").update({
                    "rotation_ends_at": adjusted.isoformat()
                }).eq("id", 1).execute()

    # --- Rotation -----------------------------------------

    async def _rotate(self, now: datetime):
        self._rotation_count += 1
        print(f"[Director] Rotating (#{self._rotation_count})...")

        # Get current state to check nominations and clear them
        old_state = self._get_state()
        old_rotation_id = (old_state or {}).get("started_at", "")
        old_satellites = (old_state or {}).get("satellites") or []

        # Check nominations for current satellites
        nominated_link = self._check_nominations(old_rotation_id, old_satellites)

        # Clear nominations for the completed rotation
        self._clear_nominations(old_rotation_id)

        # Calculate momentum
        momentum = self._calculate_momentum(now)

        # Get fatigue list (recently shown link IDs)
        fatigue = self._get_fatigue()

        if nominated_link:
            # A satellite was nominated -- use it
            link = nominated_link
            pool = "nominated"
            print(f"[Director] Nomination winner: link {link['id']}")
        else:
            # Normal pool selection
            pool = self._pick_pool()
            print(f"[Director] Pool: {pool}")
            link = self._select_from_pool(pool, momentum, fatigue)

        if not link:
            print("[Director] No links available!")
            await asyncio.sleep(10)
            return

        link_id = link["id"]
        print(f"[Director] Selected link {link_id}: {link.get('title', '?')[:60]}")

        # Generate satellites
        satellites = self._generate_satellites(link_id, fatigue)

        # Calculate timers
        duration = int(self.get_weight("rotation_default_sec", 120))
        reveal_interval = int(self.get_weight("reveal_interval_sec", 20))
        sat_count = len(satellites)
        reveal_duration = sat_count * reveal_interval

        # Assign reveal timestamps to satellites
        for i, sat in enumerate(satellites):
            sat["reveal_at"] = (now + timedelta(seconds=(i + 1) * reveal_interval)).isoformat()
            sat["revealed"] = False

        # Update global state
        self.db.table("global_state").update({
            "current_link_id": link_id,
            "started_at": now.isoformat(),
            "reveal_ends_at": (now + timedelta(seconds=reveal_duration)).isoformat(),
            "rotation_ends_at": (now + timedelta(seconds=duration)).isoformat(),
            "selection_reason": pool,
            "satellites": satellites,
        }).eq("id", 1).execute()

        # Update link tracking
        self.db.table("links").update({
            "last_shown_at": now.isoformat(),
            "times_shown": link.get("times_shown", 0) + 1,
        }).eq("id", link_id).execute()

        # Log selection
        self.db.table("director_log").insert({
            "link_id": link_id,
            "reason": pool,
            "momentum_snapshot": momentum,
            "duration_seconds": duration,
        }).execute()

        # Broadcast rotation event
        self._broadcast({
            "type": "rotation",
            "new_link": {
                "id": link_id,
                "title": link.get("title", ""),
                "url": link.get("url", ""),
            },
            "reason": pool,
        })

        # Periodic score propagation
        if self._rotation_count % 10 == 0:
            self._propagate_scores()

    # --- Nominations --------------------------------------

    def _check_nominations(self, rotation_id: str, satellites: list) -> Optional[dict]:
        """Check if any satellite has nominations; return the most-nominated one."""
        if not rotation_id or not satellites:
            return None

        try:
            nom_resp = self.db.table("nominations").select(
                "link_id"
            ).eq("rotation_id", rotation_id).execute()
            nominations = nom_resp.data or []
        except Exception as e:
            print(f"[Director] Error checking nominations: {e}")
            return None

        if not nominations:
            return None

        # Count nominations per link
        nom_counts: dict = {}
        for n in nominations:
            lid = n["link_id"]
            nom_counts[lid] = nom_counts.get(lid, 0) + 1

        # Filter to only satellite link IDs
        sat_link_ids = set(s.get("link_id") for s in satellites)
        sat_noms = {lid: count for lid, count in nom_counts.items() if lid in sat_link_ids}

        if not sat_noms:
            return None

        # Find the winner (most nominations)
        winner_id = max(sat_noms, key=sat_noms.get)
        winner_count = sat_noms[winner_id]
        print(f"[Director] Nomination winner: link {winner_id} with {winner_count} nominations")

        # Fetch the link data
        try:
            link_resp = self.db.table("links").select(
                "id, title, feed_id, direct_score, times_shown, last_shown_at, url"
            ).eq("id", winner_id).execute()
            if link_resp.data:
                return link_resp.data[0]
        except Exception as e:
            print(f"[Director] Error fetching nominated link: {e}")

        return None

    def _clear_nominations(self, rotation_id: str):
        """Clear all nominations for a completed rotation."""
        if not rotation_id:
            return
        try:
            self.db.table("nominations").delete().eq(
                "rotation_id", rotation_id
            ).execute()
        except Exception as e:
            print(f"[Director] Error clearing nominations: {e}")

    # --- Momentum -----------------------------------------

    def _calculate_momentum(self, now: datetime) -> dict:
        window_min = int(self.get_weight("momentum_window_min", 30))
        since = (now - timedelta(minutes=window_min)).isoformat()

        # Get recent votes with link info
        resp = self.db.table("votes").select(
            "link_id, value"
        ).gte("created_at", since).execute()
        votes = resp.data or []

        if not votes:
            return {"tags": {}, "types": {}, "total_up": 0, "total_down": 0}

        total_up = sum(1 for v in votes if v["value"] == 1)
        total_down = sum(1 for v in votes if v["value"] == -1)

        # Aggregate by link to find which feeds/types are trending
        link_scores: dict = {}
        for v in votes:
            lid = v["link_id"]
            link_scores[lid] = link_scores.get(lid, 0) + v["value"]

        # Get feed types for voted-on links
        if link_scores:
            link_ids = list(link_scores.keys())
            links_resp = self.db.table("links").select(
                "id, feed_id"
            ).in_("id", link_ids).execute()

            feed_ids = set()
            link_feed_map = {}
            for l in (links_resp.data or []):
                if l.get("feed_id"):
                    feed_ids.add(l["feed_id"])
                    link_feed_map[l["id"]] = l["feed_id"]

            type_scores: dict = {}
            if feed_ids:
                feeds_resp = self.db.table("feeds").select(
                    "id, type"
                ).in_("id", list(feed_ids)).execute()
                feed_type_map = {f["id"]: f["type"] for f in (feeds_resp.data or [])}

                for lid, score in link_scores.items():
                    fid = link_feed_map.get(lid)
                    if fid and fid in feed_type_map:
                        ftype = feed_type_map[fid]
                        type_scores[ftype] = type_scores.get(ftype, 0) + score
        else:
            type_scores = {}

        return {
            "types": type_scores,
            "total_up": total_up,
            "total_down": total_down,
        }

    # --- Pool Selection -----------------------------------

    def _pick_pool(self) -> str:
        weights = [
            self.get_weight("pool_fresh", 0.6),
            self.get_weight("pool_rerun", 0.3),
            self.get_weight("pool_wildcard", 0.1),
        ]
        return random.choices(["fresh", "rerun", "wildcard"], weights=weights, k=1)[0]

    def _get_fatigue(self) -> list:
        lookback = int(self.get_weight("fatigue_lookback", 20))
        resp = self.db.table("director_log").select(
            "link_id"
        ).order("selected_at", desc=True).limit(lookback).execute()
        return [r["link_id"] for r in (resp.data or []) if r.get("link_id")]

    def _select_from_pool(self, pool: str, momentum: dict, fatigue: list) -> Optional[dict]:
        if pool == "fresh":
            return self._select_fresh(momentum, fatigue)
        elif pool == "rerun":
            return self._select_rerun(fatigue)
        elif pool == "wildcard":
            return self._select_wildcard(fatigue)
        return None

    def _select_fresh(self, momentum: dict, fatigue: list) -> Optional[dict]:
        """Select a link with 0 or few votes, preferring high-trust feeds."""
        # Get links not recently shown, ordered by feed trust
        resp = self.db.table("links").select(
            "id, title, url, feed_id, direct_score, times_shown, last_shown_at"
        ).eq("direct_score", 0).order("times_shown").limit(50).execute()

        candidates = [l for l in (resp.data or []) if l["id"] not in fatigue]

        if not candidates:
            # Fallback: low-score links
            resp = self.db.table("links").select(
                "id, title, url, feed_id, direct_score, times_shown, last_shown_at"
            ).order("times_shown").limit(50).execute()
            candidates = [l for l in (resp.data or []) if l["id"] not in fatigue]

        if not candidates:
            return None

        # Weight by feed trust score
        feed_ids = set(l.get("feed_id") for l in candidates if l.get("feed_id"))
        feed_trust = {}
        if feed_ids:
            feeds_resp = self.db.table("feeds").select(
                "id, trust_score"
            ).in_("id", list(feed_ids)).execute()
            feed_trust = {f["id"]: f.get("trust_score", 1.0) for f in (feeds_resp.data or [])}

        weights = [feed_trust.get(l.get("feed_id"), 1.0) for l in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    def _select_rerun(self, fatigue: list) -> Optional[dict]:
        """Select a proven classic -- high direct_score, not recently shown."""
        resp = self.db.table("links").select(
            "id, title, url, feed_id, direct_score, times_shown, last_shown_at"
        ).gt("direct_score", 0).order("direct_score", desc=True).limit(20).execute()

        candidates = [l for l in (resp.data or []) if l["id"] not in fatigue]
        if not candidates:
            return self._select_fresh({}, fatigue)  # fallback

        # Weight by score x recency (longer since shown = more likely)
        now = datetime.now(timezone.utc)
        weights = []
        for l in candidates:
            score = max(l.get("direct_score", 0), 0.1)
            last = l.get("last_shown_at")
            if last:
                hours_ago = (now - datetime.fromisoformat(
                    last.replace("Z", "+00:00")
                )).total_seconds() / 3600
            else:
                hours_ago = 999
            weights.append(score * min(hours_ago, 100))

        if not any(w > 0 for w in weights):
            weights = [1.0] * len(candidates)

        return random.choices(candidates, weights=weights, k=1)[0]

    def _select_wildcard(self, fatigue: list) -> Optional[dict]:
        """Random link from a different feed than recent selections."""
        # Get recent feed IDs to avoid
        recent_feeds = set()
        if fatigue:
            resp = self.db.table("links").select(
                "feed_id"
            ).in_("id", fatigue[:5]).execute()
            recent_feeds = set(l.get("feed_id") for l in (resp.data or []) if l.get("feed_id"))

        # Get all links, filter out fatigue + recent feeds
        resp = self.db.table("links").select(
            "id, title, url, feed_id, direct_score, times_shown, last_shown_at"
        ).limit(200).execute()

        candidates = [
            l for l in (resp.data or [])
            if l["id"] not in fatigue and l.get("feed_id") not in recent_feeds
        ]

        if not candidates:
            candidates = [l for l in (resp.data or []) if l["id"] not in fatigue]

        if not candidates:
            return None

        return random.choice(candidates)

    # --- Satellites ---------------------------------------

    def _generate_satellites(self, link_id: int, fatigue: list) -> list:
        sat_count = int(self.get_weight("satellite_count", 5))
        positions = ["top", "top-left", "top-right", "left", "right"]

        # Get current link's vector
        resp = self.db.table("links").select(
            "content_vector"
        ).eq("id", link_id).execute()

        if not resp.data or not resp.data[0].get("content_vector"):
            # No vector -- return random satellites
            return self._random_satellites(link_id, sat_count, positions, fatigue)

        # Use Supabase RPC for vector similarity (if available)
        # Fallback: random selection with position assignment
        # For now, use random selection until we set up the vector similarity RPC
        return self._random_satellites(link_id, sat_count, positions, fatigue)

    def _random_satellites(self, exclude_id: int, count: int, positions: list, fatigue: list) -> list:
        resp = self.db.table("links").select(
            "id, title, url"
        ).neq("id", exclude_id).limit(100).execute()

        candidates = [l for l in (resp.data or []) if l["id"] not in fatigue]
        if len(candidates) < count:
            candidates = resp.data or []

        selected = random.sample(candidates, min(count, len(candidates)))

        satellites = []
        for i, link in enumerate(selected):
            pos = positions[i] if i < len(positions) else "top"
            satellites.append({
                "link_id": link["id"],
                "title": link.get("title", ""),
                "url": link.get("url", ""),
                "position": pos,
                "label": self._satellite_label(i),
            })

        return satellites

    def _satellite_label(self, index: int) -> str:
        labels = ["Deep Dive", "Deep Dive", "Pivot", "Pivot", "Wildcard"]
        return labels[index] if index < len(labels) else "Related"

    # --- Score Propagation --------------------------------

    def _propagate_scores(self):
        print("[Director] Propagating scores...")
        try:
            # 1. Recalculate links.direct_score from votes
            links_resp = self.db.table("links").select("id").execute()
            for link in (links_resp.data or []):
                lid = link["id"]
                votes_resp = self.db.table("votes").select(
                    "value"
                ).eq("link_id", lid).execute()
                score = sum(v["value"] for v in (votes_resp.data or []))
                self.db.table("links").update(
                    {"direct_score": score}
                ).eq("id", lid).execute()

            # 2. Recalculate feeds.avg_link_score and trust_score
            feeds_resp = self.db.table("feeds").select("id").execute()
            for feed in (feeds_resp.data or []):
                fid = feed["id"]
                feed_links = self.db.table("links").select(
                    "direct_score"
                ).eq("feed_id", fid).execute()
                scores = [l["direct_score"] for l in (feed_links.data or []) if l.get("direct_score") is not None]
                avg = sum(scores) / len(scores) if scores else 0
                # Trust stays 1.0 (neutral) when no votes exist; only shifts with actual interactions
                if not scores:
                    trust = 1.0
                else:
                    # sigmoid centered at 1.0: range [0.5, 1.5], neutral at avg=0
                    trust = 0.5 + 1.0 / (1 + math.exp(-avg))
                self.db.table("feeds").update({
                    "avg_link_score": avg,
                    "trust_score": trust,
                }).eq("id", fid).execute()

            # 3. Recalculate tag scores via feed_tags
            weight = self.get_weight("vote_to_tag", 0.3)
            tags_resp = self.db.table("tags").select("id").execute()
            for tag in (tags_resp.data or []):
                tid = tag["id"]
                # Get feeds with this tag
                ft_resp = self.db.table("feed_tags").select(
                    "feed_id"
                ).eq("tag_id", tid).execute()
                feed_ids = [ft["feed_id"] for ft in (ft_resp.data or [])]
                if not feed_ids:
                    continue
                # Sum direct_score of links from those feeds
                total = 0
                for fid in feed_ids:
                    fl_resp = self.db.table("links").select(
                        "direct_score"
                    ).eq("feed_id", fid).execute()
                    total += sum(l.get("direct_score", 0) for l in (fl_resp.data or []))
                self.db.table("tags").update(
                    {"score": total * weight}
                ).eq("id", tid).execute()

            print("[Director] Score propagation complete")
        except Exception as e:
            print(f"[Director] Propagation error: {e}")

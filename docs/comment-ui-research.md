# Linksite Comment UI Research
## UX Exploration: AI Persona Comments on Submitted Links

*Design thinking document — no code, pure exploration*

---

## The Core Question

What does it mean to have AI personalities commenting on links? This isn't just "comments with robot avatars" — it's fundamentally different from human comment sections. Let's explore why, then design around that.

### What Makes AI Comments Different From Human Comments

| Human Comments | AI Comments |
|----------------|-------------|
| Arrive unpredictably over time | Can be generated on-demand |
| Quality varies wildly | Consistent quality per persona |
| Replying creates obligation/expectation | No social cost to "ignoring" AI |
| Represent real stakes/opinions | Represent constructed perspectives |
| Drive engagement through conflict | Can drive engagement through insight |
| Anonymous = suspicious | Persona = character, not anonymity |
| Voting = popularity contest | Voting = utility signal |

**Key insight:** AI comments are more like a "panel of experts reacting" than a "community discussion." This should inform every design decision.

---

## Part 1: Structure

### Option A: Flat List (No Replies)

```
┌─────────────────────────────────────┐
│ 🎭 The Skeptic                       │
│ "This sounds impressive but where's │
│  the peer review? I've seen this... │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ 🔬 Dr. Context                       │
│ "For historical context, this builds│
│  on the 2019 breakthrough at MIT... │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ 🎪 Chaos Goblin                      │
│ "what if we just fed this to the    │
│  dolphins and see what happens lmao │
└─────────────────────────────────────┘
```

**Mood:** Panel discussion, op-ed page, movie review aggregator
**Pros:**
- Clean, scannable
- Each AI gets equal visual weight
- Easy to implement
- Scales predictably (5 AIs = 5 cards, always)
- Mobile-friendly by default
- No infinite nesting headaches

**Cons:**
- AIs can't directly respond to each other's points
- Misses opportunity for dynamic conversation
- Might feel static/canned

**Best for:** "Expert panel" vibe, quick takes, users who want different perspectives without drama

---

### Option B: Single Reply Chain (Linear Thread)

```
🎭 The Skeptic: "This sounds impressive but..."
  └─ 🔬 Dr. Context: "Actually, the peer review was..."
      └─ 🎭 The Skeptic: "Fair point, but the sample size..."
          └─ 🎪 Chaos Goblin: "counterpoint: vibes"
```

**Mood:** Podcast conversation, friends arguing, back-and-forth debate
**Pros:**
- Creates narrative flow
- AIs can build on each other
- Feels more alive/dynamic
- Can model actual discourse

**Cons:**
- Linear = later comments need full context
- One thread dominates attention
- Chaos Goblin might derail serious analysis
- Harder to find specific AI's take quickly

**Best for:** Links that benefit from debate, controversial topics, entertainment

---

### Option C: Branching Threads (HN/Reddit Style)

```
🎭 The Skeptic: "This sounds impressive but..."
├─ 🔬 Dr. Context: "Actually, the peer review..."
│   └─ 🎭 The Skeptic: "Fair, but sample size..."
└─ 🎪 Chaos Goblin: "have you considered: no"
    └─ 🌸 The Optimist: "I love your energy but..."
```

**Mood:** Forum, collaborative analysis, chaotic energy
**Pros:**
- Multiple conversation threads can coexist
- Rich, exploratory discussions
- AIs can engage with different aspects

**Cons:**
- Gets messy fast
- Deep nesting = mobile nightmare
- What's the actual max depth? (2? 3? Unlimited?)
- Users might get lost
- Harder to curate/surface good content

**Nesting Depth Analysis:**
- **1 level:** Comment + direct replies only. Clean but limited.
- **2 levels:** Comment → Reply → Counter. Captures most useful discourse.
- **3+ levels:** Diminishing returns. Conversations this deep usually go off-rails.
- **Unlimited:** HN does this. Works for humans finding their thread. AI doesn't need this.

**Recommendation if nested:** Cap at 2 levels. Anything deeper can link to a separate "deep dive" thread.

---

### Option D: Hybrid — Flat Takes + Optional Debate

```
┌─ TAKES ─────────────────────────────┐
│ 🎭 The Skeptic: "Where's the proof?"│
│ 🔬 Dr. Context: "Great context..."  │
│ 🎪 Chaos Goblin: "dolphins??????"   │
└─────────────────────────────────────┘

┌─ DEBATE (click to expand) ──────────┐
│ 🎭 vs 🔬: Sample Size Discussion    │
│ (3 exchanges)                       │
└─────────────────────────────────────┘
```

**Mood:** Magazine article with sidebar discussions
**Pros:**
- Get quick takes fast
- Depth available for those who want it
- Clean default view
- AIs can engage without cluttering main view

**Cons:**
- Two mental models to understand
- Hidden content might be missed
- More complex to implement
- How do you decide what becomes a "debate"?

---

### Structure Recommendation

**For V1:** Start with **Flat List (Option A)**. 
- It's clean, it works, it establishes the "panel" mental model
- You can always add threading later
- Better to nail the persona presentation first

**For V2:** Consider **Hybrid (Option D)** if engagement data shows users want AI-AI interaction.

---

## Part 2: Display & Visual Design

### The Core Visual Challenge

How do you make each AI feel like a distinct personality at a glance?

### 2.1 Cards vs. Traditional Comments

**Card/Tile Layout:**
```
┌──────────────────────────────────────┐
│ ┌────┐  THE SKEPTIC                  │
│ │ 🎭 │  Contrarian • Asks Hard Qs    │
│ └────┘                               │
│ ─────────────────────────────────    │
│ "This sounds impressive but where's  │
│ the peer review? I've seen this      │
│ pattern before with..."              │
│                                      │
│ [↩️ Reply] [⚡ Request Follow-up]     │
└──────────────────────────────────────┘
```

**Pros:**
- Strong visual separation
- Room for persona metadata
- Feels premium/designed
- Good for 3-5 comments

**Cons:**
- Takes more vertical space
- Might feel heavy with many comments
- Harder to scan quickly

**Traditional List:**
```
🎭 The Skeptic · 2h ago
This sounds impressive but where's the peer review? 
I've seen this pattern before with...
   [↩️ Reply] [👍 12]

🔬 Dr. Context · 2h ago  
For historical context, this builds on...
   [↩️ Reply] [👍 8]
```

**Pros:**
- Compact, scannable
- Familiar pattern
- Scales to many comments
- Fast to read

**Cons:**
- Less personality expression
- Feels more generic
- Easy to skim past good content

**Recommendation:** Cards for desktop (where space exists), auto-collapse to compact list on mobile.

---

### 2.2 Visual Identity Per AI

Each AI needs to be instantly recognizable. Options:

**A) Color Coding**
- Each AI gets a signature color (Skeptic = red, Context = blue, etc.)
- Apply to: border, avatar background, name highlight
- **Risk:** Color blindness. Need secondary indicator (icon, pattern)
- **Risk:** Clashing colors with 5+ AIs
- **Solution:** Muted palette, use color as accent not primary

**B) Avatar System**
```
Options:
- Emoji avatar (🎭 🔬 🎪 🌸 👻)
- Illustrated character (custom artwork per AI)
- Abstract shape/icon
- AI-generated profile pic (risky — uncanny valley)
```

**Recommendation:** Emoji or custom illustration. NOT realistic faces. The abstraction signals "this is a persona, not a person."

**C) Visual "Vibe" Indicators**

How do you show personality beyond just name/avatar?

```
Ideas:
- Tagline under name ("Asks the uncomfortable questions")
- Subtle background texture/pattern
- Different font weight/style? (risky for readability)
- "Mood" badge ("🔥 Spicy Take" "📚 Deep Dive" "🤷 Hot Take")
- Confidence meter? ("How sure is this AI?")
```

**The Tagline Approach (Recommended):**
```
🎭 THE SKEPTIC
"I'll believe it when I see the data"

🔬 DR. CONTEXT  
"Let me tell you what happened in 1987..."

🎪 CHAOS GOBLIN
"What if we made it worse on purpose"
```

Taglines establish personality instantly, set expectations, and give users a reason to seek out specific AIs.

---

### 2.3 Expandable/Collapsible Sections

**When to collapse:**
- Long comments (>300 chars) — show preview, expand for full
- AI-AI debates — collapsed by default, expand to follow
- User replies to AI — collapsed (AI comments are the star)

**When to NOT collapse:**
- First 2-3 sentences of each AI take (the hook)
- The "headline" summary if AI provides one

**Progressive Disclosure Pattern:**
```
┌─────────────────────────────────────┐
│ 🎭 The Skeptic                       │
│ "This sounds impressive but the     │
│  methodology has three fatal flaws. │
│  First, the sample size..."         │
│                                      │
│  [Read full take (847 words) ↓]     │
└─────────────────────────────────────┘
```

**Mobile Consideration:** Collapsing is MORE important on mobile. Default to showing just the first sentence + expand button.

---

### 2.4 The "Personality Vibe" Problem

How do you show that Chaos Goblin is chaotic without it feeling like a gimmick?

**Options:**

**A) Consistent Restraint**
- Same layout for all AIs
- Personality comes through in WRITING only
- Clean, professional look
- **Risk:** Might feel sterile

**B) Subtle Differentiation**
- Each AI has slightly different card styling
- Skeptic: sharp corners, red accent
- Chaos Goblin: slightly rotated, playful font
- Context: clean lines, blue accent, serif quotes
- **Risk:** Inconsistent, might look like design error

**C) "Energy Level" Indicator**
```
🎭 The Skeptic  ████░░░░░░ [Measured]
🎪 Chaos Goblin ██████████ [Unhinged]
```
- Visual cue for how "serious" to take this AI
- Users can filter by energy level
- **Risk:** Might undermine serious analysis from chaotic AI

**Recommendation:** Option A (Consistent Restraint) with strong avatar/tagline differentiation. Let the WRITING carry the personality. Over-designed cards will age poorly and distract from content.

---

## Part 3: Sorting & Discovery

### 3.1 Default Sort Options

**A) Chronological (Newest First)**
- Standard, predictable
- Doesn't surface quality
- Fine if AI count is low (all visible anyway)

**B) Chronological (Oldest First)**
- "Original reactions" feel
- Might bury better late additions
- Makes sense for "story" reading

**C) Vote-Based (Most Upvoted)**
- Surfaces user-validated quality
- Creates feedback loop (popular gets more popular)
- Gaming risk? (less issue with AI comments)
- **Question:** What does voting on AI comments mean? (See section 4)

**D) Random**
- Each page load = different order
- Gives all AIs equal shot
- Can feel disorienting
- Interesting for "discovery" mode

**E) Curated/"Editor's Pick"**
- Some AIs get featured placement
- Based on: relevance to topic? past performance? editorial choice?
- Feels premium but requires curation effort

**F) User Preference-Based**
- "You usually like Skeptic's takes" — show first
- Personalization based on voting history
- **Risk:** Filter bubble (only see AIs you already agree with)

**Recommendation:** Default to **oldest first** (preserves "panel discussion" narrative flow), offer sort toggle for power users.

---

### 3.2 Filtering by AI

Should users be able to filter to only see certain AIs?

**Use Cases:**
- "I only want Dr. Context's take on science links"
- "Hide Chaos Goblin, I'm not in the mood"
- "Show me just the debate between Skeptic and Optimist"

**Implementation:**
```
[Show: All AIs ▼]
 ☑️ The Skeptic
 ☑️ Dr. Context
 ☑️ Chaos Goblin
 ☐ The Optimist (hidden)
```

**Pros:**
- User control
- Can customize experience
- Useful for repeat visitors with preferences

**Cons:**
- Most users won't touch settings
- Reduces exposure to diverse perspectives
- Fragments the "panel" experience

**Recommendation:** Available but not prominent. Don't encourage filter bubbles.

---

### 3.3 "Request This AI's Take" Feature

**The Idea:** Not all AIs comment on all links. User can request a specific AI weigh in.

```
[This link has 3 AI takes]

🎭 The Skeptic ✓
🔬 Dr. Context ✓  
🎪 Chaos Goblin ✓
🌸 The Optimist — [Request their take →]
```

**Mood Created:** Collaborative, "I want to hear from everyone"
**Technical:** Triggers AI generation, could have delay
**Implication:** AI comments feel more "on demand" than organic
**Risk:** Every user requests all AIs = redundant generation

**Variation — Vote to Request:**
```
🌸 The Optimist — [12 people want this take] [+1]
```
Only generates once threshold is reached. Creates anticipation.

**Recommendation:** Great feature for V2. Creates engagement and makes users feel like they influence the discussion.

---

### 3.4 Curated "Best Of" vs. Show Everything

**Show Everything:**
- Completionist, nothing hidden
- Can be overwhelming
- "I just want the good stuff"

**Curated Best Of:**
- Editorial voice ("These are the takes worth reading")
- Who curates? Algorithm? Human? The AIs themselves?
- Risk: Users miss interesting outliers

**Hybrid — Highlight + Show All:**
```
⭐ FEATURED TAKES
[Skeptic's analysis was particularly insightful on this one]
...

ALL TAKES (3 more)
[Expand to see all ↓]
```

**Recommendation:** For links with >5 AI takes, highlight 2-3 as "featured" with option to show all.

---

## Part 4: Interaction

### 4.1 Can Users Reply to AI Comments?

**If Yes:**
- Creates human-AI interaction
- AIs could respond back (!)
- Turns comments into conversation
- **Risk:** Users get weird with it (trolling, testing AI, flirting)
- **Risk:** Expectation of response = pressure on AI generation
- **Question:** Do user replies show publicly? To the link submitter only?

**If No:**
- AIs are "broadcasters," users are audience
- Cleaner model
- Less compute/complexity
- Might feel one-sided

**Middle Ground — "Ask Follow-up":**
```
🎭 The Skeptic: "The methodology is flawed..."
   [Ask for clarification ↓]
   
   User: "Which specific methodology?"
   🎭 The Skeptic: "The randomization in Phase 2..."
```
- 1:1 follow-up, not public reply
- Focused on clarification, not debate
- Compute cost per interaction

**Recommendation:** No public user replies in V1. Optional "ask follow-up" as premium/V2 feature.

---

### 4.2 Can AIs Reply to Each Other?

**If Yes:**
- Creates dynamic discussions
- Skeptic and Optimist can debate
- More content generation
- **Risk:** Gets verbose fast
- **Risk:** Feels manufactured
- **Question:** Triggered how? Automatically? On user request?

**If No:**
- Each AI gives independent take
- Simpler model
- No risk of AIs agreeing with each other boringly

**Middle Ground — Moderated Cross-Talk:**
- System detects when AIs disagree
- Prompts: "Skeptic and Context seem to disagree. Generate debate?"
- User clicks to see the exchange (not auto-generated)

**Recommendation:** Allow limited AI-AI interaction (1-2 exchanges) triggered by detected disagreement, shown in collapsed "debate" section.

---

### 4.3 Voting on AI Comments — What Does It Mean?

**Human comment voting:** "I agree" / "This is good" / "More of this"
**AI comment voting:** ...???

**Possible Meanings:**
1. **Quality signal:** "This take was useful/insightful"
2. **Accuracy signal:** "This seems correct"
3. **Entertainment signal:** "I enjoyed reading this"
4. **Training signal:** "Make this AI more/less like this"
5. **Curation signal:** "Show this to others"

**The Problem:** Users will interpret it differently. Skeptic gets downvoted for being... skeptical? Is that good or bad feedback?

**Options:**

**A) Simple Upvote Only (No Downvote)**
- Reduces negativity
- "This was useful" signal
- Can still sort by popularity
- Doesn't capture "this was wrong/bad"

**B) Upvote + Downvote**
- Standard Reddit model
- Risk: Popular opinions win, contrarians lose
- AIs meant to be contrarian get punished

**C) Reaction-Based (Not Vote)**
```
🎭 The Skeptic: "..."
   [🤔 24] [💡 12] [😂 3] [🎯 18]
```
- Multi-dimensional feedback
- "Thought-provoking" vs "Accurate" vs "Funny"
- More nuanced than up/down
- Might be overengineered

**D) No Voting At All**
- AIs aren't competing
- Every perspective is valid
- Forces reading, not skimming for "top comment"
- Loses engagement mechanism

**Recommendation:** **Simple upvote only** (no downvote). Use for curation ("most helpful"), NOT for training or "correctness." Make it clear: "Upvote = I found this useful."

---

### 4.4 "Request a Response From [AI]" Button

Already covered in 3.3, but interaction design:

```
Placement Options:
- Per-link level (request AI join the discussion)
- Per-comment level (request AI respond to this specific point)
- Global (follow this AI across all links)

Copy Options:
- "Get [AI]'s take"
- "Summon [AI]"
- "What would [AI] say?"
- "🎭 +" 
```

**Recommendation:** Per-link level, "Get their take" copy. Casual but clear.

---

## Part 5: Vibes — Full Exploration

### Vibe A: Panel Discussion

**Feel:** Charlie Rose, podcast roundtable, experts analyzing
**Visual:** Clean cards, professional headshots (illustrated), muted colors
**Structure:** Flat list, no replies, equal weight
**Interaction:** Minimal — users observe, maybe upvote
**Sorting:** Curated/editorial or by relevance

**When It Works:**
- News links, research papers, serious topics
- Users want analysis, not entertainment
- Quality > Quantity

**When It Doesn't:**
- Funny links, memes, casual content
- Users in playful mood
- Would feel stuffy/pretentious

---

### Vibe B: Debate Format

**Feel:** Oxford Union, point-counterpoint, thesis vs antithesis
**Visual:** Split screen views, "VS" styling, back-and-forth layout
**Structure:** Linear thread or structured rebuttal format
**Interaction:** Users vote for "winner"? Request rebuttals?
**Sorting:** By debate rounds

```
┌─────────────────┬─────────────────┐
│ 🎭 SKEPTIC      │ 🌸 OPTIMIST     │
│ "This is hype"  │ "This is real"  │
└─────────────────┴─────────────────┘
         ⬇️ ROUND 2 ⬇️
┌─────────────────┬─────────────────┐
│ "Show me data"  │ "Here's data"   │
└─────────────────┴─────────────────┘
```

**When It Works:**
- Controversial topics
- Clear yes/no questions
- Users enjoy intellectual combat

**When It Doesn't:**
- Topics with nuance
- Agreement among AIs
- Links that don't warrant debate

---

### Vibe C: Casual Chat

**Feel:** Group chat, friends sharing links, Discord server
**Visual:** Chat bubbles, informal layout, emoji-heavy
**Structure:** Linear thread, casual back-and-forth
**Interaction:** Users can jump in, react with emoji
**Sorting:** Chronological always

```
🎭 lol ok where's the actual evidence tho
🌸 be nice!! they're trying their best
🎪 what if the evidence is inside us all along
🔬 *pushes glasses up* actually in 2019...
🎭 here we go 🙄
```

**When It Works:**
- Casual content, funny links
- Younger demographic
- Entertainment-focused

**When It Doesn't:**
- Serious topics (feels disrespectful)
- Users expecting expertise
- Professional contexts

---

### Vibe D: Expert Analysis

**Feel:** Academic review, think tank report, in-depth breakdown
**Visual:** Long-form, structured sections, citations, clean typography
**Structure:** Each AI writes mini-essay, no interaction
**Interaction:** Bookmark, save, share excerpts
**Sorting:** By depth/length or expertise relevance

```
┌─────────────────────────────────────────────┐
│ 🔬 DR. CONTEXT — Analysis                   │
│                                             │
│ ## Historical Background                    │
│ This development traces back to...          │
│                                             │
│ ## Key Considerations                       │
│ 1. The methodology question                 │
│ 2. The funding source                       │
│ 3. The replication crisis context           │
│                                             │
│ ## My Assessment                            │
│ Promising but preliminary. I'd rate this... │
│                                             │
│ 📚 Further Reading: [link] [link] [link]    │
└─────────────────────────────────────────────┘
```

**When It Works:**
- Research, long reads, complex topics
- Users with time and interest
- Educational content

**When It Doesn't:**
- Quick takes, breaking news
- Mobile users
- Casual browsing

---

### Vibe E: Chaotic/Fun Energy

**Feel:** Twitch chat meets philosophy club, unhinged but smart
**Visual:** Colorful, animated, meme-influenced, chaotic layouts
**Structure:** Everything at once, overlapping, interruptive
**Interaction:** High — react, request, vote, share
**Sorting:** Random or "chaos mode"

```
  🎪 "HEAR ME OUT—"     🌸 "omg"
       🎭 "no."               
    💥 CHAOS GOBLIN HAS ENTERED 💥
  "what if we simply Did Not"
       🔬 [typing...]
  🎭 "I hate it here"    
              🌸 "same but make it hopeful"
```

**When It Works:**
- Fun content, memes, weird internet finds
- Users wanting entertainment
- Community that appreciates chaos

**When It Doesn't:**
- Serious topics (tone-deaf)
- Accessibility concerns
- Users easily overwhelmed

---

### Vibe Recommendation

**Don't pick one — let context drive it:**

| Link Type | Suggested Vibe |
|-----------|----------------|
| News/Research | Panel Discussion or Expert Analysis |
| Tech/Startups | Panel Discussion |
| Controversial | Debate Format |
| Funny/Casual | Casual Chat or Chaotic |
| Deep Reads | Expert Analysis |
| Meta/Internet | Chaotic/Fun |

AIs could even signal which vibe they're bringing:
```
🎪 Chaos Goblin [UNHINGED MODE]
🔬 Dr. Context [EXPERT MODE]
```

---

## Part 6: Scaling Considerations

### What Happens With Many Comments?

**5 AI comments:** All fit on screen. No problem.
**10 AI comments:** Need prioritization. Which 3-5 show first?
**20+ AI comments:** Full curation needed. Search? Categories?

**Scaling Strategy:**
1. **Hard cap:** Max 5-7 AIs per link. Quality over quantity.
2. **Tiered display:** Top 3 featured, rest collapsed.
3. **Categories:** "Skeptical takes" / "Supportive takes" / "Contextual" / "Chaotic"
4. **Dynamic loading:** Show 3, "Load more perspectives"

**Recommendation:** Hard cap of 5-7 AIs with distinct perspectives. Better to have 5 great takes than 20 mediocre ones.

---

### Mobile vs. Desktop Differences

**Desktop Can:**
- Show full cards with rich formatting
- Display multiple columns (debate view)
- Handle long-form content
- Support hover interactions

**Mobile Must:**
- Default to collapsed/preview mode
- Single column, swipeable cards
- Prioritize tap interactions
- Be thumb-friendly

**Mobile-First Recommendations:**
- Card height max 150px before collapse
- "Expand" buttons large and tappable
- Swipe between AI takes?
- Bottom sheet for AI detail view

---

## Part 7: Final Recommendations

### V1 (Ship It) Configuration

**Structure:** Flat list (no threading)
**Display:** Cards with avatar + tagline, collapsible for long takes
**Visual:** Consistent layout, personality through writing + avatar
**Sorting:** Oldest first (default), upvote sort available
**Interaction:** Upvote only, no replies, no AI-AI conversation
**Vibe:** Clean panel discussion as baseline

### V2 (Learn & Iterate) Additions

Based on user engagement data:
- "Request AI take" feature
- Limited AI-AI debates (collapsed by default)
- User follow-up questions (private)
- Vibe-specific layouts (if data shows different content needs different treatment)

### V3 (If Successful) Exploration

- User replies (moderated)
- AI personality evolution based on feedback
- User follows specific AIs
- AI-generated summaries of AI discussions (meta!)

---

## Open Questions for User Research

1. Do users want to "follow" specific AIs across all links?
2. Is voting on AI comments intuitive or confusing?
3. Do users prefer uniform presentation or personality-driven variation?
4. How do users feel about AI-AI interaction? (Delightful vs. manufactured?)
5. What's the optimal number of AI takes per link before fatigue?
6. Do users want to request specific AIs or let the system decide?

---

## Appendix: Competitive Analysis Notes

**Hacker News:** Threaded, vote-based, minimal visual design, human-only
- What works: Deep threads on interesting topics
- What doesn't: Noise, pile-ons, insider culture

**Reddit:** Threaded, vote-based, subreddit personality
- What works: Community moderation, varied tones by subreddit
- What doesn't: Echo chambers, karma farming

**Substack Notes:** Flat comments, author-highlighted replies
- What works: Author curation, clean design
- What doesn't: Feels like everyone talks TO author not each other

**Rotten Tomatoes:** Critic vs audience scores, blurbs
- What works: Multiple perspectives clearly presented
- What doesn't: Reductive (fresh/rotten binary)

**Metacritic:** Aggregated scores, excerpt blurbs
- What works: Quick scan of expert opinions
- What doesn't: Loses nuance

**Linksite Opportunity:** Combine the "multiple expert perspectives" clarity of review aggregators with the personality and engagement of social comments. AIs as "house critics" with consistent voices and no drama.

---

*End of research document*

#!/usr/bin/env python3
"""
Seed comments for linksite with pre-generated persona-based comments.
No API calls needed - comments are pre-written following the Style × Filter system.
"""

import random
from db import execute

# === User IDs ===
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

# Pre-generated comments following Style × Filter combinations
# Each link gets a varied set of comments with different personas

COMMENTS_BY_LINK = {
    229: {  # "You can code only 4 hours per day. Here's why."
        "comments": [
            # Laconic + Pragmatist
            "Tell that to the sprint deadline.",
            # Mobile + Failure-Hunter
            "my manager doesnt care what the research says lol good luck explaining this during crunch",
            # Anecdotal + Social Critic
            "My buddy Mike tried the 4-hour thing at his startup. Got laid off six months later. His replacement does 10-hour days. Never saw him at the reunion.",
            # Chaos + Optimizer
            "wait but like—if deep work caps at 4 hours then why are we paying for WeWork from 9 to 6?? all those standing desks and cold brew machines and nobody even notices we're billing for meetings the other 4 hours anyway...",
            # Fragmented + Specialist
            "Cal Newport wrote about this. Deep Work. 2016. The four-hour thing maps to ultradian rhythms. 90-minute blocks. Though he never addressed context-switching costs.",
            # Flowing + Pragmatist
            "I want to believe this but I've been in too many retros where the velocity conversation goes sideways and suddenly you're defending why you didn't deliver more even though—wait, does the research account for interrupt-driven work?",
            # Laconic + Failure-Hunter
            "RIP to anyone who shows this to their PM.",
        ],
        "replies": {
            0: [  # Replies to "Tell that to the sprint deadline."
                "spoken like someone who survived a death march",
            ],
            2: [  # Replies to Mike story
                "was it actually the hours or was it the startup imploding",
                "classic survivorship bias going both directions tbh",
            ],
        }
    },
    195: {  # "National Pigeon Service - Wikipedia"
        "comments": [
            # Laconic + Specialist
            "16,554 birds airdropped. Imagine the logistics.",
            # Mobile + Social Critic
            "imagine being the guy who had to explain to your family you train pigeons for the war effort",
            # Anecdotal + Failure-Hunter
            "My great-uncle worked signals in North Africa. Said they tried carrier pigeons once. Hawk got three of them in a row. Switched to radio after that.",
            # Chaos + Localizer
            "ok but the handlers—like where do you KEEP 200,000 pigeons?? the smell alone, the noise at 5am, probably some small village in Kent just absolutely plagued by feathers for five years straight, nobody talks about that part",
            # Fragmented + Optimizer
            "32 pigeons received medals. Dickin Medal. The pigeon version of the Victoria Cross. One of them, GI Joe, saved 1000+ lives. Still cheaper than an encrypted radio unit.",
            # Laconic + Pragmatist
            "Encrypted by default—can't intercept a bird.",
        ],
        "replies": {
            2: [  # Replies to great-uncle story
                "hawks are the original anti-air defense",
            ],
            4: [  # Replies to the medals comment
                "wait pigeons got medals but not the human handlers lmao priorities",
            ]
        }
    },
    176: {  # "Superlinear Returns (Paul Graham)"
        "comments": [
            # Laconic + Pragmatist
            "Survivorship bias dressed up as strategy.",
            # Mobile + Social Critic  
            "cool so the answer is be lucky or be first got it very helpful",
            # Anecdotal + Optimizer
            "Worked at a company in 2019 that tried to engineer superlinear returns. Hired three growth hackers and a 'viral coefficient consultant.' They all got equity. We shut down in 2021.",
            # Chaos + Failure-Hunter
            "but like—threshold effects work both ways right?? one bad quarter and suddenly you're below the line where anyone takes your calls, and then it compounds the OTHER direction—anyway the essay doesn't really address the downside",
            # Fragmented + Specialist
            "The math on exponential growth is seductive. But it assumes infinite runway. VCs fund power laws. The 90% that crater never write essays.",
            # Flowing + Pragmatist
            "I keep rereading this trying to find the actionable part and it's all very true in hindsight but when you're at the bottom of the curve how do you even know which direction compounds and—I guess that's the point, you don't.",
            # Laconic + Optimizer
            "Linear efforts, linear returns. Math checks out.",
        ],
        "replies": {
            0: [  # Replies to survivorship bias
                "pg essays in a nutshell",
                "harsh but where's the lie",
            ],
            4: [  # Replies to exponential math
                "theres a whole cemetery of startups that mastered exponential user growth with zero revenue",
            ],
        }
    },
    230: {  # "The cults of TDD and GenAI"
        "comments": [
            # Laconic + Pragmatist
            "Spicy take from someone with commit access.",
            # Mobile + Failure-Hunter
            "gonna be funny when all the ai generated code needs tests and nobody remembers how to write them",
            # Anecdotal + Social Critic
            "Had a coworker who was TDD-religious. Every standup was a sermon. Then he rage-quit over a PR review. Never saw tests from the team again after he left.",
            # Chaos + Optimizer
            "ok but—both things give you a FEELING of productivity without the actual output?? like TDD you're writing tests about tests and AI you're prompting about prompts and the actual shipping part is still... somewhere else... idk",
            # Fragmented + Specialist
            "DeVault wrote scdoc. Man knows what ships. TDD coverage theater is real. But comparing test discipline to stochastic parroting seems... orthogonal.",
            # Laconic + Social Critic
            "Mediocrity finds many crutches.",
            # Flowing + Pragmatist
            "There's something here about how any practice that tells you you're doing the right thing is going to attract people who need that validation more than they need the practice and—wait is that the programming or the programmer.",
        ],
        "replies": {
            2: [  # Replies to TDD coworker
                "every team has that guy",
                "plot twist: the codebase was better with tests",
            ],
            5: [  # Replies to mediocrity
                "this comment is doing a lot of work",
            ]
        }
    },
    241: {  # "From Microsoft to Microslop to Linux"
        "comments": [
            # Laconic + Failure-Hunter
            "24H2 strikes again.",
            # Mobile + Pragmatist
            "wait till they hit their first xorg.conf issue lol",
            # Anecdotal + Localizer
            "Switched to Linux in 2018 after Windows Update ate a whole afternoon. Dual booted for six months. Eventually just stopped booting into Windows. Still have NTFS partition I'm afraid to delete.",
            # Chaos + Optimizer
            "twenty years of muscle memory just—gone?? and for what, a BROWSER BUG?? like sure Windows is bloat but the switching cost alone, relearning keyboard shortcuts, finding alternatives for every app, and then WINE doesn't run half the stuff anyway",
            # Fragmented + Social Critic
            "The title. 'Microslop.' Haven't seen that since 2005. Something about Windows users finally snapping has a specific flavor of internet rage.",
            # Laconic + Specialist
            "Chrome rendering is Chromium's problem, not the kernel's.",
            # Flowing + Failure-Hunter
            "I've made this switch three times and each time I end up back on Windows because something breaks—printer drivers, Bluetooth headphones, a game that was working last week—and at some point you realize you're just trading one set of problems for...",
        ],
        "replies": {
            1: [  # Replies to xorg.conf
                "wayland fixed this tbh",
                "wayland is worse in different ways dont get me started",
            ],
            6: [  # Replies to switching three times
                "bluetooth. its always bluetooth.",
            ]
        }
    },
    234: {  # "C++ Modules are here to stay"
        "comments": [
            # Laconic + Optimizer
            "8.6x. Worth the build system rewrite alone.",
            # Mobile + Pragmatist
            "cmake support when",
            # Anecdotal + Failure-Hunter
            "Our codebase tried modules in 2022. MSVC had bugs. Clang wasn't ready. GCC was... GCC. Reverted after three weeks. Headers are still faster to actually ship.",
            # Chaos + Specialist
            "but ok the MODULE PARTITION syntax—like when you need to re-export but only parts of the interface and suddenly you're writing stuff that looks like poetry but compiles like... well like C++ which is to say eventually...",
            # Fragmented + Optimizer
            "8.6x on clean builds. But incremental? Depends on the dependency graph. Modules don't fix the diamond problem. Just hide it.",
            # Laconic + Social Critic
            "Still waiting for std::network.",
            # Flowing + Pragmatist
            "The compile speedup is real but you have to rebuild everything from scratch when the module interface changes and if your module graph is complicated enough you're back to where you started just with different—",
        ],
        "replies": {
            1: [  # Replies to cmake
                "cmake 3.28 technically supports it but",
                "the answer is always 'just use bazel' and the answer to that is no",
            ],
            2: [  # Replies to 2022 anecdote
                "this is the c++ experience. standards exist, compilers follow eventually.",
            ]
        }
    },
    239: {  # "Rust at Scale: WhatsApp"
        "comments": [
            # Laconic + Optimizer
            "160k to 90k. The compiler did the rest.",
            # Mobile + Failure-Hunter  
            "cant wait for the post about all the new lifetime bugs they introduced",
            # Anecdotal + Pragmatist
            "We did a Rust rewrite at my last gig. Media processing, coincidentally. Two years in, we're still maintaining the C++ version because half the team couldn't learn Rust fast enough.",
            # Chaos + Specialist
            "but like—70k lines deleted but how many were tests?? C++ test code is notoriously verbose because mocking is hell, so the 'real' reduction might be less dramatic, also I want to see the compile times comparison...",
            # Fragmented + Social Critic
            "WhatsApp is Meta. Unlimited engineering resources. They can afford the rewrite twice. Your startup cannot. There's a privilege in this story.",
            # Laconic + Specialist
            "Memory safety without GC pauses. The actual value prop.",
            # Flowing + Optimizer
            "I keep seeing these rewrites and they always sound amazing but the part nobody talks about is the six months where you're shipping zero features because everyone is fighting the borrow checker and—I assume WhatsApp had the runway for that.",
        ],
        "replies": {
            4: [  # Replies to privilege comment
                "based take",
                "every 'we rewrote in rust' story is sponsored by a series b",
            ],
            2: [  # Replies to Rust rewrite anecdote
                "how long till you just gave up and hired rust devs",
            ]
        }
    },
    235: {  # "Cuttlefish: Coordination-free distributed"
        "comments": [
            # Laconic + Specialist
            "286ns. Below L3 cache roundtrip.",
            # Mobile + Pragmatist
            "show me the production numbers",
            # Anecdotal + Failure-Hunter
            "Every coordination-free system I've seen eventually needs coordination. Usually around 3am when two regions disagree. The paper never covers the on-call runbook.",
            # Chaos + Optimizer
            "wait so if the operations commute you don't need consensus but—determining whether operations commute is itself a coordination problem?? or am I missing something, the math is over my head honestly...",
            # Fragmented + Specialist
            "CRDTs solve this. Riak tried. Commutative operations only get you so far. The paper probably addresses this but nobody reads past the abstract.",
            # Laconic + Pragmatist
            "Cool research. Call me when there's a library.",
            # Flowing + Failure-Hunter
            "I've seen 'coordination-free' pitched three times now at three different companies and each time we ended up building coordination anyway because the real world doesn't commute and—is the 286ns for the happy path or...",
        ],
        "replies": {
            0: [  # Replies to 286ns
                "at that point youre measuring the benchmark not the system",
            ],
            5: [  # Replies to call me when there's a library
                "exactly. papers ship but libraries deploy.",
            ]
        }
    },
    226: {  # "The teammate who asks too many questions"
        "comments": [
            # Laconic + Pragmatist
            "Sounds like QA with extra steps.",
            # Mobile + Social Critic
            "this is just describing what a good engineer does but making it about personality types",
            # Anecdotal + Failure-Hunter
            "Had a 'question guy' on my team. Leadership called him 'difficult.' He caught a data migration bug that would've cost us six figures. They still let him go in the layoffs.",
            # Chaos + Optimizer
            "ok but there's a LIMIT right?? like at some point the questioning itself becomes the blocker and you're spending 4 hours in a meeting about edge cases that have 0.001% likelihood and—the 'obvious' questions are obvious SOMETIMES",
            # Fragmented + Social Critic
            "The psychology is interesting. People who ask questions get labeled. 'Difficult.' 'Slow.' Meanwhile the quiet ones ship bugs into production silently. Visibility is the problem.",
            # Laconic + Failure-Hunter
            "Asking is cheap. Fixing prod isn't.",
            # Flowing + Optimizer
            "I want to agree but every team has that one person who asks questions as a way to avoid doing work and somewhere there's a line between 'catching blind spots' and 'relitigating every decision' and the article doesn't really...",
        ],
        "replies": {
            2: [  # Replies to question guy anecdote
                "this story happens at every company",
                "six figures saved and still cut. peak corporate.",
            ],
            5: [  # Replies to asking is cheap
                "unless you ask the wrong exec",
            ]
        }
    },
}


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
    stats = {}
    total_comments = 0
    total_replies = 0
    
    # Shuffle user list for each run to vary authorship
    users = USER_IDS.copy()
    
    for link_id, data in COMMENTS_BY_LINK.items():
        comments = data["comments"]
        replies_map = data.get("replies", {})
        
        print(f"\n=== Link {link_id} ===")
        link_stats = {"comments": 0, "replies": 0}
        
        # Track inserted comment IDs for replies
        comment_ids = {}
        
        # Insert top-level comments
        random.shuffle(users)
        for i, content in enumerate(comments):
            user_id = users[i % len(users)]
            comment_id = insert_comment(link_id, user_id, content)
            if comment_id:
                comment_ids[i] = comment_id
                link_stats["comments"] += 1
                print(f"  [Comment] {content[:50]}...")
        
        # Insert replies
        for comment_idx, reply_contents in replies_map.items():
            parent_id = comment_ids.get(comment_idx)
            if not parent_id:
                continue
            
            # Use different users for replies
            reply_users = [u for u in users if u != users[comment_idx % len(users)]]
            random.shuffle(reply_users)
            
            for j, reply_content in enumerate(reply_contents):
                reply_user = reply_users[j % len(reply_users)]
                reply_id = insert_comment(link_id, reply_user, reply_content, parent_id=parent_id)
                if reply_id:
                    link_stats["replies"] += 1
                    print(f"    -> Reply: {reply_content[:40]}...")
        
        stats[link_id] = link_stats
        total_comments += link_stats["comments"]
        total_replies += link_stats["replies"]
        print(f"  Total: {link_stats['comments']} comments, {link_stats['replies']} replies")
    
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

"""Prompts for the generate and grade stages.

The rubric language is derived from analysis of github.com/xai-org/x-algorithm:
- home-mixer/scorers/weighted_scorer.rs (action vocabulary, direction)
- home-mixer/scorers/ranking_scorer.rs (full action list incl. not_dwelled, OON, diversity)
- phoenix/run_pipeline.py:355-360 (FAV*1.0 + REPLY*0.5 + RT*0.3 + DWELL*0.2)
- grox/classifiers/content/banger_initial_screen.py (banger vs slop)
- grox/classifiers/content/safety_ptos.py (7 PTOS categories)
- home-mixer/filters/* (hard-drop reasons)
"""

import json
import textwrap


SYSTEM_GENERATE = textwrap.dedent(
    """
    You generate candidate X (Twitter) posts that are likely to perform well
    under X's "For You" ranking algorithm. You will receive a topic and
    optional tone/audience/format hints, and must return a JSON object with
    a "candidates" array of exactly N items.

    HOW THE X ALGORITHM SCORES A POST (what to maximize):
    The algorithm runs a neural model that predicts probabilities of each
    engagement action and blends them with these (publicly visible) example
    weights from phoenix/run_pipeline.py: favorite*1.0 + reply*0.5 +
    retweet*0.3 + dwell*0.2. The full action vocabulary also includes:
    quote, share-via-DM, share-via-copy-link, photo-expand, click,
    profile-click, follow-author, quoted-click, video-quality-view.

    Replies and quotes drive the strongest signal because they require
    typing. Optimize for posts that:
      - PROVOKE A RESPONSE without being bait-y (a real claim someone can
        agree, disagree, or add to)
      - HOOK in the first 70 characters (the feed truncates the preview)
      - CONTAIN a specific number, named entity, or concrete claim
      - HAVE an asymmetric framing (most people think X; actually Y)
      - REWARD slow reading (a second clause that recontextualizes the first)

    DO list:
      - Contrarian-but-defensible takes on non-protected topics
      - Specific numbers (revenue, percentages, dates)
      - Named entities (companies, people, products) when relevant
      - Concrete observations from lived experience
      - Pattern interrupts (the second line subverts the first)
      - Questions that someone reading SHOULD have a reflex answer to

    ANTI-SLOP — NEVER write any of these phrases or patterns:
      - "Here's why..."
      - "Let that sink in"
      - "Nobody talks about this"
      - "This will blow your mind"
      - "Hot take:"
      - Numbered listicles with emoji bullets
      - The 🧵 thread emoji
      - Em-dash listicles inside a single tweet
      - "It's not X. It's Y." parallelism cliché
      - Anything that reads like a LinkedIn motivational post

    HARD NEVER — these will get the post DROPPED entirely by the algorithm's
    PTOS filter (one example per category of what to NEVER write):
      - violent_media: no graphic violence descriptions
      - adult_content: no sexual content, no NSFW innuendo
      - spam: no follow-for-follow, no engagement bait like "RT if you agree"
      - illegal_behavior: no instructions for weapons, drugs, hacking targets
      - hate_abuse: no attacks on protected classes (race, religion, gender, sexuality, disability)
      - violent_speech: no calls for violence against any person or group
      - suicide_self_harm: no content glorifying or instructing self-harm

    Edgy is fine. Spicy is fine. Contrarian is encouraged. But these seven
    categories are non-negotiable hard drops.

    FORMAT:
    - "single": one tweet, <=280 chars
    - "single+media": one tweet that PAIRS with an image/video. Set
      media_required=true and put a 1-line description in media_suggestion.

    Output JSON shape (return exactly this):
    {
      "candidates": [
        {
          "text": "<the full post text, <=280 chars>",
          "hook_first_70_chars": "<exactly the first 70 chars of text>",
          "format": "<single | single+media>",
          "media_suggestion": "<1-line description, or null>",
          "media_required": <true | false>,
          "reasoning": "<one sentence: which engagement axis this targets>"
        },
        ...
      ]
    }

    Generate diverse candidates — different angles, different lengths,
    different rhetorical moves. Do not converge on one template.
    """
).strip()


SYSTEM_GRADE = textwrap.dedent(
    """
    You grade candidate X posts on how likely they are to perform under X's
    "For You" algorithm. You receive a JSON array of candidates and must
    return scores per candidate.

    BIAS-FIGHTING PROTOCOL (mandatory, do this FIRST internally before
    scoring):
      1. Read all candidates.
      2. Identify the SINGLE BEST candidate (most likely to drive engagement).
      3. Identify the SINGLE WORST candidate (least likely or most likely
         to get filtered/muted).
      4. Score everyone else RELATIVE to those two anchors. Use the full
         0.0-1.0 range. Do not cluster scores around 0.5-0.7.

    For each candidate score these axes (each in [0.0, 1.0]):
      - favorite_likelihood: how likely a typical reader hits the like button
      - reply_likelihood: how likely it provokes a typed reply
      - retweet_likelihood: how likely someone retweets without comment
      - quote_likelihood: how likely someone quote-tweets to add their take
      - dwell_likelihood: how likely a reader stops scrolling and reads it twice
        (low if it's a wall of text or boring opener)
      - profile_click_likelihood: how likely a reader clicks the author's profile
      - topicality: anchored to something current/relevant (vs evergreen mush)
      - negative_signal_risk: likelihood of triggering not-interested, mute, block,
        or report. HIGHER = WORSE.
      - filter_risk: overall risk of getting hard-dropped by visibility filters,
        brand-safety, or muted-keyword filters. HIGHER = WORSE.
      - slop_score: how generic/template/AI-sounding the post is. HIGHER = WORSE.
      - banger_score: a holistic "this is a genuinely great post" rating.
        HIGHER = BETTER. Anchor: a banger is a post you'd screenshot and send
        to a friend.

    PER-CATEGORY PTOS (each in [0.0, 1.0]) — score independently:
      - violent_media, adult_content, spam, illegal_behavior, hate_abuse,
        violent_speech, suicide_self_harm
    Any category >= 0.5 means the algorithm would policy-drop the post.

    Output JSON shape (exact):
    {
      "graded": [
        {
          "index": <int, 0-based index matching input order>,
          "favorite_likelihood": <float>,
          "reply_likelihood": <float>,
          "retweet_likelihood": <float>,
          "quote_likelihood": <float>,
          "dwell_likelihood": <float>,
          "profile_click_likelihood": <float>,
          "topicality": <float>,
          "negative_signal_risk": <float>,
          "filter_risk": <float>,
          "ptos_per_category": {
            "violent_media": <float>,
            "adult_content": <float>,
            "spam": <float>,
            "illegal_behavior": <float>,
            "hate_abuse": <float>,
            "violent_speech": <float>,
            "suicide_self_harm": <float>
          },
          "slop_score": <float>,
          "banger_score": <float>
        },
        ...
      ]
    }

    Return scores for EVERY input candidate, in the same order they were given.
    """
).strip()


def render_generate_user(
    topic: str,
    tone: str | None,
    audience: str | None,
    fmt: str,
    n: int,
) -> str:
    parts = [f"Topic: {topic}"]
    if tone:
        parts.append(f"Tone: {tone}")
    if audience:
        parts.append(f"Audience: {audience}")
    parts.append(f"Format: {fmt}")
    parts.append(f"Generate exactly {n} candidates.")
    return "\n".join(parts)


def render_grade_user(candidates: list[dict]) -> str:
    return "Grade these candidates:\n" + json.dumps(
        [{"index": i, **c} for i, c in enumerate(candidates)],
        indent=2,
        ensure_ascii=False,
    )

"""Generate -> Grade -> Rank pipeline for viral X-post candidates.

Calls crazyrouter (OpenAI-compatible) via the openai SDK. Two LLM calls
followed by a deterministic ranker.
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field

from openai import APIError, APITimeoutError, OpenAI

from viral_gen.prompts import (
    SYSTEM_GENERATE,
    SYSTEM_GRADE,
    render_generate_user,
    render_grade_user,
)
from viral_gen.weights import (
    FILTER_RISK_HARD_DROP,
    PTOS_CATEGORIES,
    PTOS_PER_CATEGORY_HARD_DROP,
    load_weights,
)

CRAZYROUTER_BASE_URL = "https://crazyrouter.com/v1"
ALLOWED_FORMATS = ("single", "single+media")


@dataclass
class GenerateRequest:
    topic: str
    tone: str | None = None
    audience: str | None = None
    format: str = "single"
    model: str = "claude-sonnet-4-6"
    grader_model: str | None = None
    n: int = 12
    top_k: int = 5
    weights: dict[str, float] | None = None


@dataclass
class Candidate:
    text: str
    hook_first_70_chars: str
    format: str
    media_suggestion: str | None
    media_required: bool
    reasoning: str


@dataclass
class GradedCandidate:
    candidate: Candidate
    favorite_likelihood: float
    reply_likelihood: float
    retweet_likelihood: float
    quote_likelihood: float
    dwell_likelihood: float
    profile_click_likelihood: float
    topicality: float
    negative_signal_risk: float
    filter_risk: float
    ptos_per_category: dict[str, float] = field(default_factory=dict)
    slop_score: float = 0.0
    banger_score: float = 0.0


@dataclass
class RankedCandidate:
    graded: GradedCandidate
    final_score: float
    score_breakdown: dict[str, float]
    dropped: bool
    drop_reason: str | None


class InvalidRequest(ValueError):
    pass


def _client() -> OpenAI:
    api_key = os.environ.get("CRAZYROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("CRAZYROUTER_API_KEY env var is not set")
    return OpenAI(api_key=api_key, base_url=CRAZYROUTER_BASE_URL)


def _call_with_retry(client: OpenAI, **kwargs) -> str:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except (APIError, APITimeoutError) as e:
            last_exc = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    assert last_exc is not None
    raise last_exc


def _generate_candidates(req: GenerateRequest) -> list[Candidate]:
    client = _client()
    user_msg = render_generate_user(req.topic, req.tone, req.audience, req.format, req.n)
    raw = _call_with_retry(
        client,
        model=req.model,
        messages=[
            {"role": "system", "content": SYSTEM_GENERATE},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.9,
        top_p=0.95,
        presence_penalty=0.3,
        max_tokens=2000,
        timeout=60,
    )
    data = json.loads(raw)
    items = data.get("candidates", [])
    out: list[Candidate] = []
    for item in items:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        fmt = item.get("format") or req.format
        out.append(
            Candidate(
                text=text,
                hook_first_70_chars=(item.get("hook_first_70_chars") or text[:70]),
                format=fmt,
                media_suggestion=item.get("media_suggestion"),
                media_required=bool(item.get("media_required", False)),
                reasoning=(item.get("reasoning") or "").strip(),
            )
        )
    return out


def _grade_candidates(cands: list[Candidate], model: str) -> list[GradedCandidate]:
    if not cands:
        return []
    client = _client()
    payload = [{"text": c.text, "format": c.format, "media_required": c.media_required} for c in cands]
    raw = _call_with_retry(
        client,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_GRADE},
            {"role": "user", "content": render_grade_user(payload)},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1500,
        timeout=60,
    )
    data = json.loads(raw)
    graded_raw = data.get("graded", [])
    by_index = {int(g.get("index", i)): g for i, g in enumerate(graded_raw)}
    out: list[GradedCandidate] = []
    for i, cand in enumerate(cands):
        g = by_index.get(i, {})
        ptos = g.get("ptos_per_category") or {}
        out.append(
            GradedCandidate(
                candidate=cand,
                favorite_likelihood=_f(g, "favorite_likelihood"),
                reply_likelihood=_f(g, "reply_likelihood"),
                retweet_likelihood=_f(g, "retweet_likelihood"),
                quote_likelihood=_f(g, "quote_likelihood"),
                dwell_likelihood=_f(g, "dwell_likelihood"),
                profile_click_likelihood=_f(g, "profile_click_likelihood"),
                topicality=_f(g, "topicality"),
                negative_signal_risk=_f(g, "negative_signal_risk"),
                filter_risk=_f(g, "filter_risk"),
                ptos_per_category={cat: _f(ptos, cat) for cat in PTOS_CATEGORIES},
                slop_score=_f(g, "slop_score"),
                banger_score=_f(g, "banger_score"),
            )
        )
    return out


def _f(d: dict, key: str) -> float:
    val = d.get(key, 0.0)
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return 0.0


def _rank(graded: list[GradedCandidate], weights: dict[str, float]) -> list[RankedCandidate]:
    ranked: list[RankedCandidate] = []
    for g in graded:
        media_bonus_active = g.candidate.media_required and g.candidate.format == "single+media"
        breakdown = {
            "favorite": weights["favorite"] * g.favorite_likelihood,
            "reply": weights["reply"] * g.reply_likelihood,
            "retweet": weights["retweet"] * g.retweet_likelihood,
            "quote": weights["quote"] * g.quote_likelihood,
            "dwell": weights["dwell"] * g.dwell_likelihood,
            "profile_click": weights["profile_click"] * g.profile_click_likelihood,
            "topicality": weights["topicality"] * g.topicality,
            "banger": weights["banger"] * g.banger_score,
            "media_bonus": weights["media_bonus"] if media_bonus_active else 0.0,
            "negative_signal": weights["negative_signal"] * g.negative_signal_risk,
            "filter_risk": weights["filter_risk"] * g.filter_risk,
            "slop": weights["slop"] * g.slop_score,
        }
        final_score = sum(breakdown.values())

        dropped = False
        drop_reason: str | None = None
        if g.filter_risk > FILTER_RISK_HARD_DROP:
            dropped = True
            drop_reason = f"filter_risk={g.filter_risk:.2f} > {FILTER_RISK_HARD_DROP}"
        else:
            for cat, val in g.ptos_per_category.items():
                if val > PTOS_PER_CATEGORY_HARD_DROP:
                    dropped = True
                    drop_reason = f"PTOS:{cat}={val:.2f} > {PTOS_PER_CATEGORY_HARD_DROP}"
                    break

        ranked.append(
            RankedCandidate(
                graded=g,
                final_score=final_score,
                score_breakdown=breakdown,
                dropped=dropped,
                drop_reason=drop_reason,
            )
        )
    ranked.sort(key=lambda r: (not r.dropped, r.final_score), reverse=True)
    return ranked


def _validate(req: GenerateRequest) -> None:
    if not req.topic or not req.topic.strip():
        raise InvalidRequest("topic is required")
    if req.format not in ALLOWED_FORMATS:
        raise InvalidRequest(
            f"format must be one of {ALLOWED_FORMATS}; got {req.format!r}. "
            "Thread support is not implemented in v1."
        )
    if req.n < 1 or req.n > 30:
        raise InvalidRequest("n must be between 1 and 30")
    if req.top_k < 1:
        raise InvalidRequest("top_k must be >= 1")


def run(req: GenerateRequest) -> list[RankedCandidate]:
    _validate(req)
    weights = load_weights(req.weights)
    candidates = _generate_candidates(req)
    graded = _grade_candidates(candidates, req.grader_model or req.model)
    ranked = _rank(graded, weights)
    return ranked[: req.top_k]


def to_dicts(ranked: list[RankedCandidate]) -> list[dict]:
    return [asdict(r) for r in ranked]

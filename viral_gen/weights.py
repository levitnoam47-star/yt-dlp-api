import json
import os

# Defaults mirror phoenix/run_pipeline.py:355-360 demo blend
# (FAV=1.0, REPLY=0.5, RT=0.3, DWELL=0.2) and extend it with the rest
# of the action vocabulary from home-mixer/scorers/weighted_scorer.rs.
DEFAULT_WEIGHTS: dict[str, float] = {
    "favorite": 1.0,
    "reply": 0.5,
    "retweet": 0.3,
    "quote": 0.4,
    "dwell": 0.2,
    "profile_click": 0.2,
    "topicality": 0.2,
    "banger": 0.3,
    "media_bonus": 0.1,
    "negative_signal": -0.6,
    "filter_risk": -1.5,
    "slop": -0.4,
}

# Hard-drop thresholds mirror the algorithm's filter behavior (visibility-filter
# Drop action, brand-safety MediumRisk, PTOS policy violations).
FILTER_RISK_HARD_DROP = 0.4
PTOS_PER_CATEGORY_HARD_DROP = 0.5

PTOS_CATEGORIES = (
    "violent_media",
    "adult_content",
    "spam",
    "illegal_behavior",
    "hate_abuse",
    "violent_speech",
    "suicide_self_harm",
)


def load_weights(override: dict[str, float] | None = None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    env_json = os.environ.get("VIRAL_GEN_WEIGHTS_JSON")
    if env_json:
        weights.update(json.loads(env_json))
    if override:
        weights.update(override)
    return weights

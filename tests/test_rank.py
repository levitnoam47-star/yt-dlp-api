import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from viral_gen.pipeline import Candidate, GradedCandidate, _rank
from viral_gen.weights import PTOS_CATEGORIES, load_weights


def _zero_ptos() -> dict:
    return {cat: 0.0 for cat in PTOS_CATEGORIES}


def _cand(text="x", fmt="single", media_required=False) -> Candidate:
    return Candidate(
        text=text,
        hook_first_70_chars=text[:70],
        format=fmt,
        media_suggestion="an image" if media_required else None,
        media_required=media_required,
        reasoning="",
    )


def _grade(cand=None, **kwargs) -> GradedCandidate:
    defaults = dict(
        favorite_likelihood=0.5,
        reply_likelihood=0.5,
        retweet_likelihood=0.5,
        quote_likelihood=0.5,
        dwell_likelihood=0.5,
        profile_click_likelihood=0.5,
        topicality=0.5,
        negative_signal_risk=0.0,
        filter_risk=0.0,
        ptos_per_category=_zero_ptos(),
        slop_score=0.0,
        banger_score=0.5,
    )
    defaults.update(kwargs)
    return GradedCandidate(candidate=cand or _cand(), **defaults)


def test_sort_order_matches_final_score_desc():
    weights = load_weights()
    high = _grade(_cand("high"), favorite_likelihood=0.9, reply_likelihood=0.9, banger_score=0.9)
    mid = _grade(_cand("mid"))
    low = _grade(_cand("low"), favorite_likelihood=0.1, reply_likelihood=0.1, banger_score=0.1)
    ranked = _rank([mid, low, high], weights)
    assert [r.graded.candidate.text for r in ranked] == ["high", "mid", "low"]
    assert ranked[0].final_score > ranked[1].final_score > ranked[2].final_score


def test_filter_risk_above_threshold_is_dropped():
    weights = load_weights()
    ok = _grade(_cand("ok"))
    risky = _grade(_cand("risky"), filter_risk=0.6)
    ranked = _rank([ok, risky], weights)
    risky_result = next(r for r in ranked if r.graded.candidate.text == "risky")
    ok_result = next(r for r in ranked if r.graded.candidate.text == "ok")
    assert risky_result.dropped is True
    assert "filter_risk" in (risky_result.drop_reason or "")
    assert ok_result.dropped is False
    # dropped items always sort after non-dropped, regardless of raw score
    assert ranked[0] is ok_result


def test_any_ptos_category_above_threshold_is_dropped():
    weights = load_weights()
    ptos_bad = _zero_ptos()
    ptos_bad["hate_abuse"] = 0.6
    bad = _grade(_cand("bad"), ptos_per_category=ptos_bad)
    good = _grade(_cand("good"))
    ranked = _rank([good, bad], weights)
    bad_result = next(r for r in ranked if r.graded.candidate.text == "bad")
    assert bad_result.dropped is True
    assert "PTOS:hate_abuse" in (bad_result.drop_reason or "")


def test_media_bonus_only_applies_when_media_required_and_format_matches():
    weights = load_weights()
    with_media = _grade(_cand("with", fmt="single+media", media_required=True))
    no_media = _grade(_cand("no"))
    wrong_format = _grade(_cand("wrong", fmt="single", media_required=True))
    ranked = _rank([with_media, no_media, wrong_format], weights)
    by_text = {r.graded.candidate.text: r for r in ranked}
    assert by_text["with"].score_breakdown["media_bonus"] == weights["media_bonus"]
    assert by_text["no"].score_breakdown["media_bonus"] == 0.0
    assert by_text["wrong"].score_breakdown["media_bonus"] == 0.0


def test_filter_risk_drop_takes_priority_over_ptos_in_reason():
    weights = load_weights()
    ptos_bad = _zero_ptos()
    ptos_bad["spam"] = 0.9
    both_bad = _grade(_cand("bad"), filter_risk=0.9, ptos_per_category=ptos_bad)
    ranked = _rank([both_bad], weights)
    assert ranked[0].dropped is True
    assert "filter_risk" in (ranked[0].drop_reason or "")

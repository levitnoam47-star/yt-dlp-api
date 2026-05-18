import argparse
import json
import sys
from dataclasses import asdict

from viral_gen.pipeline import GenerateRequest, InvalidRequest, run


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="viral_gen",
        description="Generate ranked X-post candidates likely to perform under the For You algorithm.",
    )
    p.add_argument("topic", help="What the post should be about")
    p.add_argument("--tone", default=None, help="e.g. contrarian, funny, sincere, technical")
    p.add_argument("--audience", default=None, help="e.g. 'AI engineers', 'crypto traders'")
    p.add_argument("--format", default="single", choices=["single", "single+media"])
    p.add_argument("--model", default="claude-sonnet-4-6", help="crazyrouter model id")
    p.add_argument("--grader-model", default=None, help="grader model id; defaults to --model")
    p.add_argument("--n", type=int, default=12, help="how many candidates to generate")
    p.add_argument("--top-k", type=int, default=5, help="how many ranked candidates to return")
    p.add_argument("--json", action="store_true", help="output JSON instead of pretty text")
    return p.parse_args(argv)


def _pretty_print(ranked) -> None:
    for i, rc in enumerate(ranked, start=1):
        c = rc.graded.candidate
        marker = " [DROPPED]" if rc.dropped else ""
        print(f"\n#{i}  score={rc.final_score:+.3f}{marker}")
        if rc.dropped:
            print(f"    drop_reason: {rc.drop_reason}")
        print(f"    text: {c.text}")
        if c.media_required and c.media_suggestion:
            print(f"    media: {c.media_suggestion}")
        g = rc.graded
        print(
            "    grades: "
            f"fav={g.favorite_likelihood:.2f} "
            f"reply={g.reply_likelihood:.2f} "
            f"rt={g.retweet_likelihood:.2f} "
            f"quote={g.quote_likelihood:.2f} "
            f"dwell={g.dwell_likelihood:.2f} "
            f"banger={g.banger_score:.2f} "
            f"slop={g.slop_score:.2f} "
            f"filter_risk={g.filter_risk:.2f}"
        )
        top_breakdown = sorted(rc.score_breakdown.items(), key=lambda kv: abs(kv[1]), reverse=True)[:5]
        print("    top contribs: " + ", ".join(f"{k}={v:+.2f}" for k, v in top_breakdown))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    req = GenerateRequest(
        topic=args.topic,
        tone=args.tone,
        audience=args.audience,
        format=args.format,
        model=args.model,
        grader_model=args.grader_model,
        n=args.n,
        top_k=args.top_k,
    )
    try:
        ranked = run(req)
    except InvalidRequest as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps([asdict(r) for r in ranked], indent=2, ensure_ascii=False))
    else:
        _pretty_print(ranked)
    return 0


if __name__ == "__main__":
    sys.exit(main())

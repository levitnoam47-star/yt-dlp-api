# yt-dlp-api + viral_gen

A small Flask app that wraps `yt-dlp` for video URL/frame/composite endpoints, plus
a `viral_gen` package that generates ranked candidate X (Twitter) posts using LLM
calls routed through [crazyrouter](https://crazyrouter.com) (OpenAI-compatible).

The post-generator scores candidates against signals from the open-source
X "For You" algorithm (`github.com/xai-org/x-algorithm`) and hard-drops
anything that would fail the PTOS / visibility filters.

## Setup

```bash
pip install flask yt-dlp gunicorn openai
export CRAZYROUTER_API_KEY=sk-...           # get one from crazyrouter.com
```

Or with Docker:

```bash
docker build -t yt-dlp-api .
docker run -p 8080:8080 -e CRAZYROUTER_API_KEY=sk-... yt-dlp-api
```

## Usage — viral post generator

### CLI

```bash
python -m viral_gen.cli "your topic" \
    --tone contrarian \
    --audience "AI engineers" \
    --format single+media \
    --model claude-opus-4-7 \
    --top-k 5
```

Add `--json` for machine-readable output. `--model` accepts any crazyrouter
model id (e.g. `claude-sonnet-4-6`, `claude-opus-4-7`, `gpt-5.5`).

### HTTP endpoint

```bash
python server.py    # serves on :8080
```

```bash
curl -X POST http://localhost:8080/generate-posts \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "AI agents replacing junior devs",
    "tone": "contrarian",
    "audience": "AI engineers",
    "format": "single+media",
    "model": "claude-opus-4-7",
    "top_k": 5
  }'
```

Returns a JSON array of ranked candidates with full score breakdowns.
Each request takes ~30-90s (two LLM calls: generate + grade).

### Request fields

| Field          | Required | Default                | Notes                                  |
|----------------|----------|------------------------|----------------------------------------|
| `topic`        | yes      | —                      | What the post should be about          |
| `tone`         | no       | —                      | e.g. `contrarian`, `funny`, `sincere`  |
| `audience`     | no       | —                      | Niche/persona                          |
| `format`       | no       | `single`               | `single` or `single+media`             |
| `model`        | no       | `claude-sonnet-4-6`    | crazyrouter model id                   |
| `grader_model` | no       | same as `model`        | Use a cheaper model for grading        |
| `n`            | no       | `12`                   | How many candidates to generate (1-30) |
| `top_k`        | no       | `5`                    | How many to return                     |
| `weights`      | no       | defaults from algorithm | Override the ranking weights          |

`format=thread` returns 400 — thread support is deferred to v2.

## Tests

```bash
pytest tests/test_rank.py
```

## Existing yt-dlp endpoints (unchanged)

- `GET /health`
- `GET /extract-frame?url=…&time=…`
- `GET /composite?url=…&start=…&duration=…&corner=…`

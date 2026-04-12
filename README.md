# idea-council

A local-first CLI that surfaces the full argument landscape for a product idea - fast, before you spend time talking to humans who will. Every session produces an **inspectable JSON transcript** - version it in git, pipe it through `jq`, diff runs side-by-side, or feed it into downstream tooling. No SaaS dependency; data is sent only to the providers you configure.

Models argue from rotating assigned roles - Optimist, Critic, Devil's Advocate, Domain Expert - and a synthesizer produces a structured verdict with optional market-search grounding. The goal is enumerable, named arguments you can act on, not a substitute for expert feedback.

---

## Why

When you ask a single model to brainstorm and critique an idea, the critique is shallow. It's the same mind talking to itself.

Real ideation benefits from structured disagreement between models with different training data, sizes, and tendencies. `idea-council` assigns different roles to different providers, anonymizes their identities during reaction rounds to prevent deference bias, and produces a structured verdict you can act on.

---

## How it works

```
Domain / Seed idea
        ↓
Council lineup assigned  (roles shuffled randomly each run)
        ↓
Round 1 - Independent analysis  (all debaters run in parallel, no visibility into each other)
        ↓
Round 2 - First reaction  (no exit check yet - one exchange is not enough to judge convergence)
        ↓
Round 3+ - Reaction  (each debater sees others' responses, anonymized as Debater A/B/C)
        ↓   ↑
Synthesizer: continue or done?  (first check after Round 3; minimum 2 reaction rounds always run)
        ↓
Market verification  (GitHub + Tavily search, synthesizer scores openness 1–10)
        ↓
        ├── Market openness 7–10  →  proceed to synthesis
        ├── Market openness 4–6  →  ask user: proceed / reframe / abandon
        └── Market openness 1–3  →  auto-reframe (council finds the gap)
        ↓
Final synthesis  →  verdict + opportunity score + kill conditions
```

**Two input modes:**

At startup, if `--seed` is not provided, the CLI asks:

```
How would you like to start?
  [1] Mode A - council generates the seed idea
  [2] Mode B - provide your own seed idea
```

- **Mode A** - provide a domain, the council generates and selects the seed idea. After generation, the CLI shows the chosen seed and asks you to confirm or replace it before the debate starts.
- **Mode B** - enter a seed idea interactively (or pass `--seed` as a flag to skip the prompt)

---

## Providers

| Provider | Type | Role | Required |
|----------|------|------|----------|
| Anthropic | Cloud | Debater + Synthesizer | Yes |
| Ollama | Local | Debater | No |
| OpenAI | Cloud | Debater | No |
| Google Gemini | Cloud | Debater | No |

Ollama runs locally with no API cost. The synthesizer is always Anthropic - it is the only model that sees full attribution (role → provider → model) and produces the final verdict.

Role assignments are shuffled randomly each run. No provider is permanently anchored to a personality.

---

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ms-codehorizon/idea-council.git
cd idea-council
uv sync
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

---

## Configuration

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_FALLBACK_MODEL=claude-haiku-4-5

# Local models (no key required)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODELS=qwen3.5:35b
# if you have multiple ollama modelsyou can list them as well
# OLLAMA_MODELS=qwen2.5:7b,llama3.1:8b,mistral:7b

# Optional cloud providers
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

GOOGLE_API_KEY=
GOOGLE_MODEL=gemini-2.0-flash

# Market verification
GITHUB_SEARCH_ENABLED=true
GITHUB_SEARCH_MAX_RESULTS=10
TAVILY_API_KEY=          # optional - web search skipped if not set

# Session
MAX_TOKENS_PER_CALL=2048
OUTPUT_DIR=output
```

GitHub search uses the `gh` CLI token - no separate key required. Run `gh auth login` if you haven't already.

---

## Usage

```bash
# Generate a seed idea from a domain
uv run idea-council --domain "developer tools"

# Debate a specific idea
uv run idea-council --domain "fintech" --seed "a credit score API for gig workers"

# Exclude known projects from consideration
uv run idea-council --domain "developer tools" \
  --exclude "github.com/foo/bar, OpenRouter, LiteLLM"

# Provide personal context to guide generation
uv run idea-council --domain "developer tools" \
  --context "15 years in set-top box middleware, applying that to AI tooling"

# Show each debater's full response after every round
uv run idea-council --domain "healthcare AI" --verbose

# Cap the number of debate rounds (default: 3)
uv run idea-council --domain "fintech" --rounds 5
```

---

## Output

During the session, a live spinner shows the current phase and elapsed time. Each debater also gets its own row that spins while it is thinking and shows a checkmark when done:

```
⠋ Round 1 - independent analysis (4 debaters)...   0:00:18
  ✓ Optimist           anthropic/claude-sonnet-4-6   0:00:04
  ⠙ Critic             ollama/qwen3.5:35b             0:00:18
  ✓ Devils Advocate    ollama/mistral:7b              0:00:06
  ✓ Domain Expert      ollama/llama3.1:8b             0:00:05
```

At the start of each session (and before any reframe round), the council lineup is printed:

```
Council lineup:
  Optimist           anthropic/claude-sonnet-4-6
  Critic             ollama/qwen3.5:35b
  Devils Advocate    ollama/mistral:7b
  Domain Expert      ollama/llama3.1:8b
```

The final report panel shows:

```
Verdict: PURSUE

Opportunity Score: 8/10 (strong)

Strongest Argument:
...

Fatal Flaw:
...

Kill Conditions:
• ...

What Must Be True:
• ...
```

Market verification result:

```
Market Openness: 7/10 (open space)
  Web (12 results):
    https://...
```

Every session is saved to `output/<timestamp>_<domain>.json` regardless of outcome.

---

## Scores

Both scores use the same 1–10 scale where higher is always better:

| Score | Measures | High means | Low means |
|-------|----------|------------|-----------|
| **Market Openness** | How open the space is | Wide open, few competitors | Crowded, many similar products |
| **Opportunity Score** | How strong the idea is | Strong idea, pursue it | Weak idea, flawed framing |

---

## Market verification tiers

| Market Openness | Action |
|-----------------|--------|
| 7–10 (open space) | Proceed to synthesis automatically |
| 4–6 (moderate competition) | Pause - show findings, ask: proceed / reframe / abandon |
| 1–3 (crowded) | Auto-reframe - council finds the gap without user input |

When reframe is triggered, roles are reshuffled across providers and the new council receives the competitor list and is asked: *"These already exist. What angle is missing? What did none of them solve?"* The reframe lineup and a 2-line preview of the gap question are shown before the round starts.

---

## Final report schema

```
FinalReport
├── session_id
├── domain
├── seed_idea
├── seed_mode           "generated" | "user_provided"
├── exclusions
├── user_context
├── role_assignments    role → { provider, model }
├── rejected_seeds
├── rounds              list of DebateRound
├── rounds_completed
├── exit_reason         "synthesizer_done" | "max_rounds_reached"
├── verdict             "pursue" | "refine" | "abandon"
├── opportunity_score   1–10
├── strongest_argument
├── fatal_flaw
├── kill_conditions
├── what_must_be_true
├── market
│   ├── market_openness     1–10, null if skipped
│   ├── remaining_gap
│   ├── github_hits
│   ├── web_hits
│   └── competitor_hits
├── reframe_triggered
├── reframe_seed
├── user_choice         "proceed" | "reframe" | "abandon"
└── provider_events     fallback / repair events
```

---

## Degraded modes

| Condition | Behavior |
|-----------|----------|
| 1 debater available | Session aborts - minimum 2 required |
| 2 debaters available | Runs with Optimist + Critic only |
| 3 debaters available | Drops lowest-priority role |
| Ollama unreachable | Skipped at startup with a warning |
| Both search sources unconfigured | Market verification skipped |
| User selects abandon | Partial report written, session exits |

---

## Development

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=idea_council
```

Tests use mocked adapters - no real API calls required.

---

## Project structure

```
src/idea_council/
├── config/
│   └── settings.py        # Loads provider keys and model names from .env
├── models/
│   └── session.py         # RoleResponse, DebateRound, MarketVerification, FinalReport
├── providers/
│   ├── adapter.py         # Base adapter + Anthropic, Ollama, OpenAI, Google
│   └── registry.py        # Builds active provider list from settings
├── roles/
│   └── prompts.py         # System prompts for each role and the synthesizer
├── orchestrator/
│   ├── rotation.py        # Shuffles roles → providers each run
│   ├── seed.py            # Parallel seed generation and selection
│   ├── debate.py          # Round execution, fallback, repair
│   ├── market.py          # GitHub + Tavily search and interpretation
│   ├── synthesizer.py     # Exit check and final report generation
│   └── council.py         # Session orchestration
└── cli/
    └── cli.py             # Typer CLI entry point
```

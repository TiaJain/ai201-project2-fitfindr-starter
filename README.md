# FitFindr 🛍️

FitFindr is a multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it. You describe what you're after in plain language ("vintage graphic tee under $30"), and the agent searches a mock listings dataset, styles the top find against your existing wardrobe, and writes a shareable caption for the look. It's built around a planning loop that decides which tools to run based on what each step returns, and it handles the messy cases (no matches, empty wardrobe, missing input) without crashing.

Built for CodePath AI201, Project 2. The planning and design decisions live in [planning.md](planning.md).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the repo root (same free key from Project 1, get one at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

`.env` is gitignored, never commit it. Without a key, the two LLM tools still run but fall back to canned strings instead of generated text.

## Running it

```bash
python app.py          # Gradio UI at http://localhost:7860
python agent.py        # CLI: runs a happy-path query and a no-results query
python -m pytest tests/   # 11 tests covering each tool + every failure mode
```

## Tool Inventory

All three tools live in [tools.py](tools.py). The signatures below match the actual code exactly.

### 1. `search_listings(description, size, max_price) -> list[dict]`

**Purpose:** Find listings in the mock dataset (40 items) that match what the user described, filtered by size and price, ranked by relevance. This is pure Python, no LLM.

**Inputs:**
- `description` (`str`) — free-text keywords, e.g. `"vintage graphic tee"`. Scored by keyword overlap against each listing's `title`, `description`, `style_tags`, and `category`.
- `size` (`str | None`) — size to filter by, e.g. `"M"`. Case-insensitive substring match, so `"M"` matches a listing sized `"S/M"`. `None` skips size filtering.
- `max_price` (`float | None`) — inclusive price ceiling in dollars, e.g. `30.0`. `None` skips price filtering.

**Output:** A `list[dict]` of full listing dicts sorted by relevance score (highest first). Each dict has `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Listings that score 0 on keyword overlap are dropped. Returns `[]` when nothing matches — never raises.

### 2. `suggest_outfit(new_item, wardrobe) -> str`

**Purpose:** Given the found item and the user's wardrobe, ask the LLM (Groq `llama-3.3-70b-versatile`) for 1–2 complete outfits that pair the new piece with things the user already owns.

**Inputs:**
- `new_item` (`dict`) — a listing dict (the item being considered). The prompt uses its `title`, `category`, `colors`, and `style_tags`.
- `wardrobe` (`dict`) — shaped `{"items": [...]}`, where each item has `id`, `name`, `category`, `colors`, `style_tags`, and optional `notes`. May be empty.

**Output:** A non-empty `str`. With a stocked wardrobe it names specific pieces ("your baggy straight-leg jeans") and gives concrete styling moves (tuck, roll, layer). With an empty wardrobe it returns general styling advice for the item on its own.

### 3. `create_fit_card(outfit, new_item) -> str`

**Purpose:** Turn the outfit suggestion plus the item into a short, casual, shareable caption — an Instagram/TikTok OOTD post, not a product description. Runs at a higher LLM temperature so different inputs (and re-runs) read differently.

**Inputs:**
- `outfit` (`str`) — the outfit suggestion string from `suggest_outfit()`.
- `new_item` (`dict`) — the listing dict. Its `title`, `price`, and `platform` get worked into the caption once each.

**Output:** A 2–4 sentence `str` usable as a caption. Returns a descriptive message string (not an exception) when `outfit` is empty.

## How the Planning Loop Works

The loop lives in `run_agent(query, wardrobe)` in [agent.py](agent.py). It's a result-driven pipeline with one real branch point, not a fixed "always call all three tools" sequence. Each step writes to a shared `session` dict, and the next step reads from it.

1. **Initialize** a fresh `session` via `_new_session()`. Every result field starts `None`/empty; `error` starts `None`.
2. **Parse the query** with `_parse_query()` (regex). It extracts `max_price` (a number after "under/below/less than/<"), `size` (a token after "size", or a bare standalone token like `M`/`XXS`), and treats the leftover text as `description`. Result stored in `session["parsed"]`.
3. **Call `search_listings`** with the parsed params. Store the list in `session["search_results"]`.
4. **Branch on the result — this is the conditional logic that makes it a real planning loop:**
   - **If `search_results` is empty:** build a specific error message that names the failed constraints, store it in `session["error"]`, and **return immediately**. `suggest_outfit` and `create_fit_card` are never called.
   - **If there are results:** set `session["selected_item"] = search_results[0]` (top-ranked) and continue.
5. **Call `suggest_outfit(selected_item, wardrobe)`**, store in `session["outfit_suggestion"]`. (The tool decides internally whether to use the wardrobe-aware or empty-wardrobe prompt, so no branch is needed in the loop here.)
6. **Call `create_fit_card(outfit_suggestion, selected_item)`**, store in `session["fit_card"]`.
7. **Return the session.** The caller (`app.py` / CLI) checks `session["error"]` first; if it's set, only the error is shown.

So the agent's behavior genuinely differs by input: an impossible query terminates at step 4 with three downstream fields left `None`, while a matchable query runs all three tools.

## State Management

A single `session` dict, created by `_new_session()`, is the only source of truth for one interaction. Each tool writes its output into a named field; the next tool reads from that field rather than from anything the user re-enters.

| Field | Written when | Read by |
|-------|--------------|---------|
| `query` | session init | parse step |
| `parsed` (`description`, `size`, `max_price`) | after parsing | `search_listings` |
| `search_results` (`list[dict]`) | after search | the empty-check branch |
| `selected_item` (`dict`) | after a non-empty search (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` (`dict`) | session init (from caller) | `suggest_outfit` |
| `outfit_suggestion` (`str`) | after styling | `create_fit_card` |
| `fit_card` (`str`) | after caption | returned to UI |
| `error` (`str \| None`) | any failing step | caller checks first |

The key property: the item `search_listings` returns is the *same object* that flows into `suggest_outfit` and `create_fit_card` via `session["selected_item"]` — verified with an identity check (`session["selected_item"] is session["search_results"][0]` returns `True`). The user never re-types the item. State is scoped to one `run_agent` call; nothing persists across sessions.

## Error Handling

Every tool owns its failure mode and returns something usable instead of raising. "Fail silently" and "crash" are both avoided.

| Tool | Failure mode | What happens |
|------|--------------|--------------|
| `search_listings` | No listing matches the query | Returns `[]` (never raises). The planning loop catches the empty list, sets a specific `error`, and stops before the LLM tools run. |
| `suggest_outfit` | Empty wardrobe (`items == []`) | Branches to a general-styling-advice prompt and still returns useful text. On any LLM/API error it catches the exception and returns a safe fallback string. |
| `create_fit_card` | Empty/whitespace `outfit` | Returns `"Can't make a fit card yet, no outfit suggestion was provided."` before any API call. On an LLM/API error it returns a minimal hand-built caption from the item fields. |

**Concrete example from testing.** Running the impossible query through the full agent:

```bash
$ python -c "from agent import run_agent; from utils.data_loader import get_example_wardrobe; \
s = run_agent('designer ballgown size XXS under \$5', get_example_wardrobe()); \
print('error:', s['error']); print('fit_card:', s['fit_card'])"

error: No listings found matching 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords.
fit_card: None
```

The error tells the user *what* failed and *what to try*, and `fit_card` stays `None` — proof the downstream tools never ran on empty input. The other two failure modes are exercised by `test_suggest_outfit_empty_wardrobe` and `test_create_fit_card_missing_outfit` in [tests/test_tools.py](tests/test_tools.py).

## Spec Reflection

**One way the spec helped:** Writing the tool signatures and failure modes in `planning.md` *before* coding meant the empty-results branch in the planning loop was designed in from the start, not bolted on. Because `search_listings` was specced to return `[]` (never raise), the loop's branch logic was obvious: check the list, set an error, return early. The state table in `planning.md` also mapped directly onto the `session` dict fields, so wiring the tools together was mostly mechanical.

**One way implementation diverged:** The spec described query parsing loosely ("regex for the structured bits"). In practice I had to make the size regex more careful than planned — a naive `\b[SML]\b` match would strip the "m" out of unrelated words, so the final version only matches a token after the literal word "size" or a whitelist of standalone size tokens (`XXS|XS|S|M|L|XL|XXL`). The divergence was about robustness the paper spec didn't anticipate, not a change in approach.

## AI Usage

**Instance 1 — implementing `search_listings`.** I gave the AI the Tool 1 block from `planning.md` (the three parameters with types, the ranked-list return contract, and the empty-list failure mode) plus the `load_listings()` signature from `utils/data_loader.py`, and asked for a pure-Python implementation. It produced a function that filtered and scored correctly, but its first version scored by total keyword *occurrences*, which let a long description outweigh a genuinely better match. I overrode that to count each unique keyword once (`set(keywords)` in `_relevance_score`) so relevance reflects coverage, not verbosity. I verified the result against three queries, including the deliberate no-match case, before trusting it.

**Instance 2 — the planning loop and state flow.** I gave the AI the Architecture diagram and the Planning Loop + State Management sections from `planning.md` and asked it to implement `run_agent()` to match. The generated loop was close, but I tightened two things: I made it store the parsed params in `session["parsed"]` (the draft parsed into local variables that weren't visible in the returned state, which the milestone explicitly wanted observable), and I had the error message echo the *actual* parsed constraints rather than a generic "no results" string, so the user gets something actionable. I confirmed the branch behavior by checking that the no-results path leaves `outfit_suggestion` and `fit_card` as `None`.

## Project Structure

```
ai201-project2-fitfindr-starter/
├── agent.py              # run_agent() planning loop + query parser
├── tools.py              # search_listings, suggest_outfit, create_fit_card
├── app.py                # Gradio UI + handle_query()
├── planning.md           # design spec (written before code)
├── data/
│   ├── listings.json         # 40 mock listings
│   └── wardrobe_schema.json  # wardrobe format + example/empty wardrobes
├── utils/
│   └── data_loader.py    # load_listings, get_example_wardrobe, get_empty_wardrobe
└── tests/
    └── test_tools.py     # 11 pytest tests (tools + failure modes)
```

# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock listings dataset (40 items from `load_listings()`) for pieces matching what the user described. It filters out anything over the price ceiling or in the wrong size, then ranks whatever's left by how well its text matches the user's keywords, and returns the best matches first.

**Input parameters:**
- `description` (str): Free text keywords describing the desired item, like `"vintage graphic tee"`. Used to score listings by keyword overlap against each listing's `title`, `description`, `style_tags`, and `category`.
- `size` (str | None): Size string to filter by, like `"M"`. Matching is case insensitive and substring based, so `"M"` matches a listing sized `"S/M"`. Pass `None` to skip size filtering entirely.
- `max_price` (float | None): Inclusive maximum price in dollars, like `30.0`. Listings priced above this get dropped. Pass `None` to skip price filtering.

**What it returns:**
A `list[dict]` of full listing dicts, sorted by relevance score with the highest first. Each dict has: `id` (str), `title` (str), `description` (str), `category` (str: tops/bottoms/outerwear/shoes/accessories), `style_tags` (list[str]), `size` (str), `condition` (str: excellent/good/fair), `price` (float), `colors` (list[str]), `brand` (str | None), `platform` (str: depop/thredUp/poshmark). Listings that score 0 on keyword overlap get excluded. When nothing matches it returns an empty list `[]`, it never raises.

**What happens if it fails or returns nothing:**
The tool returns `[]` instead of raising. The planning loop notices the empty list and sets `session["error"]` to a specific, actionable message that echoes back the parsed constraints, something like *"No listings found matching 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords."*, then returns early. It does **not** call `suggest_outfit` with an empty selected item.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the chosen listing plus the user's wardrobe and asks the LLM (Groq `llama-3.3-70b-versatile`) to put together 1–2 complete, wearable outfits that pair the new piece with things the user already owns, naming specific wardrobe pieces and giving concrete styling moves like tuck, roll, or layer.

**Input parameters:**
- `new_item` (dict): A single listing dict, the `selected_item` the planning loop picked. The prompt uses its `title`, `category`, `colors`, and `style_tags` so the LLM knows what it's styling.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [...]}`, where each item has `id`, `name`, `category`, `colors`, `style_tags`, and an optional `notes`. Comes from `get_example_wardrobe()` (10 items) or `get_empty_wardrobe()` (where `items == []`). It might be empty.

**What it returns:**
A non-empty string in plain language with the outfit suggestion(s), something like *"Pair this with your wide-leg khaki trousers and chunky white sneakers... roll the sleeves once and tuck the front corner."* When the wardrobe has items, the suggestion calls out specific pieces by name. When the wardrobe is empty it gives general styling advice instead (the vibe, what kinds of bottoms/shoes/layers pair well).

**What happens if it fails or returns nothing:**
- If the wardrobe is empty (`wardrobe["items"] == []`), the tool switches to a general styling advice prompt and still returns something useful. It doesn't error.
- If the LLM or API call fails (network error, empty completion), the tool catches it and returns a graceful fallback string like *"Couldn't generate a styling idea right now, but this [item] would pair well with neutral basics and your go-to shoes."* The planning loop treats any returned string as success so the flow can keep going to the fit card. A logged error in the string keeps the agent useful instead of crashing it.

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion plus the new item into a short, casual, shareable caption, the kind of thing you'd actually put on an Instagram or TikTok OOTD post. Uses a higher LLM temperature so different inputs (and re-runs) come out noticeably different.

**Input parameters:**
- `outfit` (str): The outfit suggestion string that came back from `suggest_outfit()`. Gives the caption its vibe and the pieces being worn.
- `new_item` (dict): The selected listing dict. The caption naturally works in its `title`, `price`, and `platform`, mentioning each once.

**What it returns:**
A 2–4 sentence string you can drop straight into a social caption. It mentions the item name, price, and platform naturally, captures the outfit vibe in specific terms, reads like a real post rather than a product description, and varies between runs thanks to the higher temperature.

**What happens if it fails or returns nothing:**
- If `outfit` is `None` or just whitespace, the tool bails out before calling the LLM and returns a descriptive message like *"Can't make a fit card yet, no outfit suggestion was provided."* It doesn't raise.
- If the LLM or API call fails, it catches the error and returns a simple fallback caption built from the item fields, like *"thrifted this [title] off [platform] for $[price] 🛍️"*, so the user always gets something shareable.

---

### Additional Tools (if any)

None for the required build. One candidate for a stretch tool (not built yet): `compare_price(item)`, which would estimate whether a listing's price is fair by comparing it against the median price of same-`category` listings in the dataset. I'll update this planning.md before building it.

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop lives in `run_agent(query, wardrobe)` in `agent.py` and is driven by what each tool returns, all stored in a single `session` dict. It's a linear pipeline with one real branch point (the empty-search guard), so the agent's behavior actually changes based on results instead of always running all three tools no matter what.

1. **Initialize.** `session = _new_session(query, wardrobe)`. All result fields start out as `None` or empty and `session["error"] = None`.
2. **Parse the query.** Pull `description`, `size`, and `max_price` out of the raw query and store them in `session["parsed"]`. I'm going with regex for the structured bits: `max_price` from a `$?(\d+)` pattern after "under/below/<", `size` from a `size\s+([A-Za-z0-9]+)` pattern (plus bare tokens like "size M"), and whatever's left over becomes the `description`. (Noting it here since the agent.py TODO asks me to document the choice.)
3. **Call `search_listings(description, size, max_price)`** and store the result in `session["search_results"]`.
   - If results are empty (`len == 0`): set `session["error"]` to a specific message that names the failed constraints and `return session` right away. Do **not** keep going. This is the visible error branch.
   - If results came back: set `session["selected_item"] = session["search_results"][0]` (the top-ranked one) and continue.
4. **Call `suggest_outfit(selected_item, wardrobe)`** and store it in `session["outfit_suggestion"]`. The tool decides internally whether to use the wardrobe-aware or empty-wardrobe prompt, so the loop doesn't branch here, it always gets a usable string back.
5. **Call `create_fit_card(outfit_suggestion, selected_item)`** and store it in `session["fit_card"]`.
6. **Return** the finished `session`. The caller (`app.py` or the CLI) checks `session["error"]` first: if it's set, show the message, otherwise render the listing, outfit, and fit card.

**How it knows it's done:** the pipeline ends either at the early `return` in step 3 (the error path) or once `fit_card` is filled in at step 5 (the success path). There's no open-ended re-planning here, the "loop" is the staged, result-driven flow above.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session()`) is the one source of truth for the whole interaction. Each tool writes its output into a named field, and the next tool reads from that field instead of from anything the user re-types. The tracked fields:

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | `_new_session` | parse step |
| `parsed` (`description`, `size`, `max_price`) | parse step | `search_listings` |
| `search_results` (list of listing dicts) | `search_listings` | empty-check branch |
| `selected_item` (top listing dict) | planning loop (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` (from caller) | `suggest_outfit` |
| `outfit_suggestion` (str) | `suggest_outfit` | `create_fit_card` |
| `fit_card` (str) | `create_fit_card` | returned to UI |
| `error` (str \| None) | any failing step | caller checks first |

So the item that `search_listings` finds flows into `suggest_outfit` and `create_fit_card` through `session["selected_item"]`, and the user never has to re-type it. The session is scoped to one `run_agent` call, nothing persists across sessions (cross-session memory is a stretch feature).

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Tool returns `[]` (never raises). The loop sets `session["error"]` to a specific message that echoes the parsed constraints and suggests fixes, like *"No listings matched 'designer ballgown' in size XXS under $5. Try dropping the size filter, raising your max price, or using broader keywords."*, then returns early without calling `suggest_outfit`. The UI shows this in the listing panel and leaves the other two blank. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Tool switches to a general styling advice prompt and returns useful guidance for the item on its own (the vibe plus the kinds of bottoms/shoes/layers that pair well) instead of naming pieces. If the LLM or API errors, it catches it and returns a safe fallback string so the flow still reaches the fit card. The agent never passes empty input forward. |
| create_fit_card | Outfit input is missing or incomplete | If `outfit` is `None`, empty, or just whitespace, the tool returns a descriptive message (*"Can't make a fit card yet, no outfit suggestion was provided."*) without ever calling the LLM. If the LLM or API errors, it returns a minimal hand-built caption from the item's `title`/`price`/`platform` so the user still gets something shareable. Never raises. |

---

## Architecture

```
                          User query  +  wardrobe choice (example / empty)
                                  │
                                  ▼
        ┌──────────────────────── Planning Loop (run_agent) ───────────────────────┐
        │                                                                           │
        │  parse query  ──►  session.parsed = {description, size, max_price}        │
        │                                  │                                        │
        │                                  ▼                                        │
        │   search_listings(description, size, max_price)                           │
        │                 │                                                         │
        │                 │  results == []                                          │
        │                 ├─────────────► [ERROR] session.error =                   │
        │                 │               "No listings found... try X" ──► return ──┼──► (early exit)
        │                 │                                                         │
        │                 │  results == [item, ...]                                 │
        │                 ▼                                                         │
        │   session.search_results = [...]                                          │
        │   session.selected_item  = results[0]                                     │
        │                 │                                                         │
        │                 ▼                                                         │
        │   suggest_outfit(selected_item, wardrobe)                                 │
        │       │  wardrobe empty ──► general styling advice                        │
        │       │  wardrobe has items ──► named-piece outfits                       │
        │       ▼                                                                   │
        │   session.outfit_suggestion = "..."                                       │
        │                 │                                                         │
        │                 ▼                                                         │
        │   create_fit_card(outfit_suggestion, selected_item)                       │
        │       │  outfit missing ──► descriptive message (no LLM call)             │
        │       ▼                                                                   │
        │   session.fit_card = "..."                                                │
        │                 │                                                         │
        └─────────────────┼─────────────────────────────────────────────────────  ┘
                          ▼
              return session  (caller checks session.error first)
                          │
                          ▼
        UI panels:  listing   |   outfit idea   |   fit card
                                   (or error message in the listing panel)

   ┌─────────────────────────────────────────────────────────────────────┐
   │ Session state (single dict, threads through every step):             │
   │ query · parsed · search_results · selected_item · wardrobe ·         │
   │ outfit_suggestion · fit_card · error                                 │
   └─────────────────────────────────────────────────────────────────────┘
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

I'll use **Claude (Claude Code)** for all three tools, building and testing one at a time in isolation before wiring anything into the agent.

- **`search_listings`**: What I'll give Claude is the *Tool 1* block above (the three params with their types, the ranked-list return contract, and the empty-list failure mode) plus the `load_listings()` signature and field list from `utils/data_loader.py`. What I expect back is a pure Python function (no LLM) that loads the listings, filters by `max_price` and case insensitive substring `size`, scores what's left by keyword overlap across `title`/`description`/`style_tags`/`category`, drops the zero-score items, and returns them sorted high to low. To check it before trusting it, I'll confirm it filters by **all three** params and returns `[]` (not an error) when nothing matches, then run 3 queries against the real data: `"vintage graphic tee" / "M" / 30` (expect tops under $30), `"black combat boots" / "8" / None`, and the deliberate miss `"designer ballgown" / "XXS" / 5` (expect `[]`).

- **`suggest_outfit`**: What I'll give Claude is the *Tool 2* block (both branches) plus the wardrobe schema fields and an example item dict. What I expect back is a function that checks `wardrobe["items"]`, formats the wardrobe (or switches to the general-advice prompt when it's empty), calls Groq `llama-3.3-70b-versatile`, and returns the string, with a try/except fallback. To check it, I'll run it once with `get_example_wardrobe()` and confirm it names real pieces (like "wide-leg khaki trousers"), then once with `get_empty_wardrobe()` and confirm it still returns non-empty general advice without crashing.

- **`create_fit_card`**: What I'll give Claude is the *Tool 3* block (the style rules plus the missing-outfit guard). What I expect back is a guarded function that returns a 2–4 sentence caption at a higher temperature. To check it, I'll confirm the empty-`outfit` guard returns the descriptive message without any API call, then run it twice on the same item and outfit and confirm the two captions actually **differ** and that title/price/platform each show up once.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the **Architecture diagram**, the **Planning Loop** section, and the **State Management** table above, and ask it to implement `run_agent()` in `agent.py` to match that control flow exactly, plus `handle_query()` in `app.py`. What I expect back: code that parses the query into `session["parsed"]`, calls the three tools in order, branches to the early `return` when `search_results` is empty, and threads everything through the `session` dict. How I'll check it before trusting it: trace it against the diagram branch by branch, then run the CLI in `agent.py` and confirm (a) the happy-path query fills in `selected_item`, `outfit_suggestion`, and `fit_card` with `error is None`, and (b) the `"designer ballgown size XXS under $5"` query sets `error` and leaves `outfit_suggestion`/`fit_card` as `None`, which proves `suggest_outfit` never got called on empty input.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1: Parse and search.**
`run_agent` sets up the session and parses the query into `description="vintage graphic tee"`, `size=None` (no size mentioned), and `max_price=30.0` (from "under $30"). It calls `search_listings("vintage graphic tee", None, 30.0)`. The tool drops anything over $30, scores the rest on keyword overlap ("vintage", "graphic", "tee"), and returns a ranked list of matching tops (like the Y2K butterfly baby tee at $18 and other graphic/vintage tees under $30). `session["search_results"]` comes back non-empty.

**Step 2: Select and suggest an outfit.**
Since the results aren't empty, the loop sets `session["selected_item"] = search_results[0]` (the top-ranked tee). It calls `suggest_outfit(selected_item, wardrobe)` with the example wardrobe (10 items). The wardrobe has items, so the LLM returns something like: *"Pair this tee with your baggy dark-wash jeans and chunky white sneakers for an easy streetwear look. Throw the vintage black denim jacket over it and tuck the front hem for shape."* That goes into `session["outfit_suggestion"]`.

**Step 3: Fit card.**
The loop calls `create_fit_card(outfit_suggestion, selected_item)`. At the higher temperature the LLM returns a casual caption that works in the item name, the $18 price, and the Depop platform once each, like: *"found the cutest vintage tee on depop for $18 🦋 styled it with my baggy jeans + chunky sneakers and it's officially my new go-to fit. full look in stories 🤍"* That goes into `session["fit_card"]`.

**Final output to user:**
`run_agent` returns the session with `error=None`. The UI shows three panels: the top listing (title, price, condition, platform), the outfit idea from Step 2, and the fit card from Step 3, all built from the single item found in Step 1, with nothing re-entered by the user.

**(Error variant)** For `"designer ballgown size XXS under $5"`, Step 1's `search_listings` returns `[]`. The loop sets `session["error"]` to a specific message ("No listings matched... try dropping the size filter or raising your price") and returns early. `suggest_outfit` and `create_fit_card` never get called, and the UI shows the error in the listing panel with the other two blank.

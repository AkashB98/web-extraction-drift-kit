# web-extraction-drift-kit

**Web extraction breaks silently in production — a site redesign renames one class and your pipeline keeps running, now returning the wrong price with no error anywhere. This kit detects the break: it extracts saved HTML pages into a strict schema and diffs the extraction field by field, so structure drift alarms loudly instead of shipping wrong data quietly.**

Forward-deployed and integration teams live on other people's pages and payloads, and those change without notice. The dangerous failures are not crashes — they are the **silent wrong values** (extractions that succeed, pass type checks, and are simply the wrong node's data). This project builds the detection half of that problem end to end: a **declarative schema** (a written list of fields, where each lives, and what type it must be), strict typed parsing, a field-level **drift diff** (a field-by-field comparison of two extractions that names exactly what moved), a labelled **mutation suite** (a set of deliberately broken page versions, each tagged with the damage it should cause), and a CI gate that turns breaking drift into an exit code.

> **Synthetic data only.** Every page is a saved fixture for a fictional store (**Helios Home**). No live site is fetched, no real company or customer data is used anywhere in this project.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies. Detection only — deliberately no fetching, no crawling, no self-healing (see Scope).

## Quickstart

```bash
# 1. Extract a saved product page into the strict schema (JSON)
python3 cli.py extract --page product --input fixtures/product_baseline.html

# 2. Diff a mutated page against its baseline (field-level drift)
python3 cli.py diff --page product --baseline fixtures/product_baseline.html \
    --current fixtures/product_b6_silent_price_move.html

# 3. CI gate: exit 0 = clean, 1 = breaking drift, 2 = error
python3 cli.py check --page pricing --baseline fixtures/pricing_baseline.html \
    --current fixtures/pricing_c2_unrelated_copy.html

# 4. One-command end-to-end demo (extract -> full mutation suite
#    -> check gate -> serve)
python3 demo.py

# 5. Tiny localhost API: POST /extract, POST /diff, GET /health
python3 cli.py serve --port 8765
```

## The headline result (pinned by golden evals)

The mutation suite ships 18 labelled page versions across two page types (product, pricing):

| Set | Count | Result |
|---|---|---|
| Breaking mutations (renamed hook, moved node, removed field, price format change, date locale swap, int replaced by a word, values swapped) | 12 | **12/12 caught** |
| …of which **silent** (extraction returns a clean, plausible, *wrong* value — no error at all) | 3 | **3/3 flagged silent** |
| Cosmetic-only changes (whitespace, unrelated copy edits, attribute changes) | 6 | **0 false alarms** |

The three silent cases are the point of the project:

- **Renamed class, wrong price (PB1).** The product price's class is renamed `price` → `cost`. The price **hook** (the id or class an extractor looks up) is document-wide first-match, so extraction doesn't fail — it falls through to the related item's `$499.00` price and returns it as the product price.
- **Moved node, wrong price (PB6).** The product price node is moved below the related-items section; first-match now lands on the related price again — $499.00 returned where $1,299.00 belongs.
- **Swapped values (RB5).** Monthly and annual prices trade places in the template; both parse perfectly, both are wrong.

A checker that only asks "did extraction throw?" misses all three. A baseline diff catches them because it compares *values and formats*, not just success.

## How it works

**The schemas.** Two page types, five fields each, declared in `extract.py`. Each field names a hook (by `id` or by `class`), an optional container scope (a `within` id — a field whose node is moved outside its container counts as missing), and a type: `string`, `int`, `price`, or `date`.

**Strict typed parsing.** Parsers accept exact formats and record a **format signature** (a short label describing the format a value arrived in, e.g. `USD|prefix-$|thousands=,|decimal=.`):

- **price** — a money value parsed to integer cents. `$1,299.00` → `129900`. The European `1.299 €` is *recognised* (also `129900` cents) but carries a different signature, so the diff reports **format-changed** instead of silently accepting a format the downstream system never agreed to. A naive parser that strips non-digits would read `1.299` as `1299`, `1.299`, or `1` depending on its mood — that ambiguity is the bug this design refuses.
- **date** — a calendar date value. ISO `2026-01-15` is canonical; `15/01/2026` (EU order) and `Feb 1, 2026` (US long form) are recognised, converted, and signature-flagged as format changes.
- **int** — a whole-number value. `42` and `1,200` parse; `unlimited` in an int field is a **type-changed** drift, not a zero.
- **string** — plain text, whitespace-normalised so re-indentation can never look like a change.

**The drift diff.** Comparing two extractions of the same page yields, per field, one of: **missing** (the field is no longer found), **type-changed** (found, but no longer parses as its type), **format-changed** (parses, but under a new format signature — value may be identical), or **value-changed** (parses cleanly, same format, different value — flagged `silent`, because nothing but the baseline comparison could have caught it). All four are severity **breaking** (enough to fail the CI gate). Cosmetic page changes never reach the field level, so they produce an empty diff by construction, not by a threshold someone tuned.

**Extraction is `html.parser`-only.** Pages are parsed with the stdlib **HTML parser** (the Python standard library's built-in page reader — no browser, no JavaScript execution) into a small inspectable tree. Saved fixtures only: the kit is handed HTML text, never a URL.

## Architecture

| Module | Job |
|---|---|
| `extract.py` | The two declarative schemas, the `html.parser` tree builder, scoped hook lookup, and the strict typed parsers (price / date / int / string) with format signatures |
| `drift.py` | Field-level diff (missing / type-changed / format-changed / value-changed, silent flag, breaking severity) + the labelled mutation-suite runner |
| `cli.py` | `extract` / `diff` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /extract`, `POST /diff`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: baseline extraction, all 18 mutations, check exit codes, live localhost serve round-trip |
| `fixtures/` | 20 saved Helios Home pages (2 baselines + 18 mutations) and `manifest.json`, the label file naming each mutation's category, silence, and expected fields/kinds |

## Evals

`python3 evals/run_evals.py` → **9/9 golden evals**, report committed at `evals/eval_report.json` (md5 `74114a3ad2a7dd2e9aac745f664cb481`, byte-identical across 3 verified runs):

- **E1** baseline extraction pinned on both page types (every field found, typed, error-free)
- **E2** the price format trap — `$1,299.00` and `1.299 €` are the same cents under different signatures, and the diff flags format-changed
- **E3** headline pinned — 12/12 breaking caught, 3/3 silent flagged, 0/6 cosmetic false alarms
- **E4** every breaking mutation's diffed fields and kinds match its manifest label exactly — no extra noise, none missing
- **E5** missing (`found=False`, no error) stays distinct from type-changed (found, parse error)
- **E6** CLI `check` exit codes 0 / 1 / 2
- **E7** serve round-trip matches local extract + diff exactly
- **E8** mutation-suite determinism — canonical JSON identical across independent runs
- **E9** fixture inventory pinned (20 HTML files, 18 labelled mutations, baselines self-clean)

Unit tests: `python3 -m unittest discover -s tests` → **31 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-checked price/date/int parsing, the format trap, every labelled mutation asserted field-by-field, CLI exit codes, and serve round-trips.

## Development loop — what the checks actually caught

1. **Real bug: the first label for the renamed-class mutation was wrong, and the suite proved it.** PB1 was designed and labelled as a *missing* field: rename the price class, the hook fails, the field disappears. The test failed immediately — the diff said **value-changed, silent**, not missing. The extractor wasn't buggy: because the price hook is document-wide first-match (the fictional template reuses `class="price"` for related items), renaming the product's price class makes extraction fall through to the related item's $499.00 and return it, cleanly, as the product price. The *label* was the bug. Fix: PB1 is now labelled and pinned as the third silent case, with a dedicated test (`test_renamed_class_falls_through_silently`). The mislabel turned out to be the most instructive mutation in the suite — a renamed hook on a shared class doesn't fail loudly, it fails *silently*, which is the exact failure this kit exists to catch.
2. **Design decision, validated by E2: equal values can still be drift.** `1.299 €` and `$1,299.00` are the same number of cents, so a value-only diff would pass PB4. The format signature exists precisely because downstream consumers parse the *format*, not the number — E2 pins that the same-value format change still alarms, and that the EU form is recognised-and-flagged rather than misparsed or rejected as garbage.
3. **Design decision, validated by the cosmetic set: silence is structural, not tuned.** Cosmetic fixtures never reach a field (whitespace is normalised at parse time; marketing copy is not a schema field; unknown attributes are ignored by hook lookup), so the 0-false-alarm result follows from the extraction design rather than from an alarm threshold — there is no threshold in the codebase to tune.

## Scope and honest limits

- **Detection only.** No live fetching, no crawling, no JavaScript rendering, and **no self-healing selectors** (automatically guessing a replacement hook when one breaks) — healing is the obvious next project; silently "fixing" a selector can silently pick the wrong node, which is PB1's failure wearing a helpful hat.
- **Saved pages only.** The kit consumes HTML text (fixtures, or HTML a caller already has). Anything about retrieving pages — sessions, rendering, rate limits — is out of scope by design.
- **First-match hooks are intentionally naive.** The extractor takes the first node matching a hook; the baseline diff is the safety net, and PB1/PB6 document exactly how first-match fails. A production version would add uniqueness assertions per hook — the diff output already contains what that check would need.
- **Value-changed needs a baseline judgement.** A legitimate price change and a swapped template variable look identical to a diff. The kit reports the change as breaking and lets the CI owner decide — it detects, it does not adjudicate.
- **Two page types, five fields each.** Enough to exercise every drift kind and both failure modes; the schema format extends by adding entries, not code.
- **The API is a demo surface.** It binds 127.0.0.1 only, is stateless, and accepts HTML in the request body.

## Why this project

It takes the author's day-job craft — analytics pipelines fed by other teams' pages, tags, and exports, where a quiet upstream change corrupts a report nobody questions for weeks — and builds the reliability layer that work always needs: declare what you expect, parse it strictly, and diff against a baseline so change arrives as an alarm with a field name on it, not as a wrong number in a dashboard. The same discipline a forward-deployed engineer brings to a customer integration: make the contract explicit, make the failure modes exit codes, and never let "it ran without errors" stand in for "it returned the right data."

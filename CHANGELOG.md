# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Changed

#### `feat: direct_fact synthesis — show full tool output in a table with sections`

**Commit:** `0a37163`  
**File changed:** `backend/main.py` — `_build_synthesis_prompt()`

**What the problem was:**

When the LLM routing classified a user query as `direct_fact` (a single factual
lookup, e.g. *"which process is using the most memory?"*), the synthesis prompt
previously told the model to summarise the tool output and highlight the top 3–5
entries. This caused the model to collapse long lists into a single vague sentence
such as *"Firefox is using 11.6 GB; other processes also use memory"* with no
further detail.

**What changed:**

The `is_direct_fact=True` branch of `_build_synthesis_prompt()` in `backend/main.py`
was rewritten to produce a **structured three-section response** instead of a
free-form summary:

| Section | Purpose |
|---|---|
| `## Top Result` | Reports the #1 entry with **all** available fields from the raw tool output (PID, user, RES, VIRT, MEM%, CPU%, command). |
| `## Full List` | Renders **every** row returned by the tool as a Markdown table with no truncation, and converts units in every row (kB → MB/GB, seconds → days/hours/minutes, Hz → MHz/GHz). |
| `## Observations` *(omit if nothing notable)* | Optional bullet notes on clearly abnormal conditions (e.g. one process dominating memory). Unsolicited maintenance advice and speculative commentary are explicitly suppressed. |

**Why it matters:**

- Users who ask for a list (e.g. top memory consumers, open connections) now see the
  **complete** list, not a truncated summary invented by the model.
- All numeric fields are human-readable in every row, not just the headline figure.
- The *Observations* section is conditional (`omit if nothing notable`) so simple
  single-value queries stay clean and do not generate spurious warnings.
- Unsolicited maintenance advice remains suppressed — the model may only note
  conditions that are **clearly** abnormal (e.g. a single process consuming an
  extreme share of total memory).

**Scope of the change:**

Only the `is_direct_fact=True` code path inside `_build_synthesis_prompt()` was
modified. All other request modes (`targeted_status`, `full_diagnostic`,
`follow_up`) are unaffected.

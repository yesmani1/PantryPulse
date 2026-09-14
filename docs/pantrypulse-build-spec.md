# PantryPulse — Build Specification

**AWS Agents for Humans Hackathon | Everyday Agents track**
Strands Agents SDK · Amazon Bedrock · 2-person team
Target submission Sep 11 · Hard deadline Sep 14, 5:00pm PT · Judging until Oct 8

---

## 1. How to use this document

Work is organised as **numbered action items**, not dates. Each item has an owner, explicit dependencies, and a done-when condition. Work down your own list; check the dependency before starting.

**Two roles:**

| Role | Owner | Scope |
|---|---|---|
| **BACKEND** | mani | Strands agents, tools, AWS, persistence, scheduling, evals, deployment |
| **INTERFACE** | karthi | Telegram bot, ingestion UX, message design, demo assets, documentation |
| **SHARED** | both | Contract, integration, testing, submission |

**Item IDs:** `S-n` shared · `BE-n` backend · `IF-n` interface.

**The dependency rule that matters:** `S-2` (schemas.py) unblocks almost everything. Until it is committed, INTERFACE is blocked on BACKEND. After it is committed, both roles work in parallel against the same contract with zero coupling.

### Status column

Every action-item table carries a `Status` column. **This document is the ledger** — the single authoritative record of what is done and what is pending. `README.md` summarises the current state for readers; it does not duplicate this table.

| Status | Meaning |
|---|---|
| `DONE` | Integrated to the team's shared branch, tests passing there |
| `BUILT` | Done-when condition met on a working branch, not yet integrated |
| `PARTIAL` | Started and usable, but the done-when condition is not fully met — say what is missing |
| `BLOCKED` | Waiting on a dependency that is not `DONE` or `BUILT` |
| `PENDING` | Waiting on an external party (AWS, Anthropic, a third-party review) rather than on another action item or on either of us |
| `NEXT` | The item this role picks up next |
| `?` | Status unverified — someone needs to check |
| `—` | Not started |

`BUILT` and `DONE` are separate on purpose: work that runs on one person's branch is not yet work the team has. Do not mark an item `DONE` because it works on your machine.

**Update the status in the same commit that changes it.** If a commit starts, finishes, blocks or unblocks an item, that commit edits this table too. Commits that do not move an item — refactors, copy edits, fixes — leave it alone.

### Branching

Handled manually by the team, out of band. Deliberately not documented here or in `CLAUDE.md` — a written branch process that drifts from what people actually do is worse than none.

Done-when conditions in this document that say "pushed" or "integrated" mean the work has reached the shared branch the team is currently integrating on, whichever that is. Ask before assuming.

---

## 2. Product definition

### One-line

An autonomous household agent that reads your groceries, understands what expiry dates actually mean, and sends one message a day. Not a pantry app you have to maintain.

### The differentiator

Every existing expiry app counts down to the printed date and tells you to throw food out. Roughly a fifth of consumer food waste comes from people misreading quality dates as safety deadlines. **The category is automating the mistake.**

PantryPulse classifies *what kind of date* it is reading:

| `date_type` | Meaning | Agent behaviour |
|---|---|---|
| `use_by` | Safety date | Conservative warning. Firm on high-risk categories. |
| `best_by` | Quality date, manufacturer-set | **No alert on approach.** Alert *after*, with reassurance + rescue recipe. |
| `sell_by` | Retailer stock rotation | Not a consumer deadline at all. Suppress. |
| `estimated` | Inferred from shelf-life table | Widest tolerance, flagged low confidence. |
| `none` | Non-perishable (honey, salt, spices) | Never counted down. |

### Trust mechanism

Every item carries `expiry_source` — `gs1_barcode` / `ocr` / `shelf_life_table` / `user_confirmed` — and it is **visible in the UI**. Never present an estimate as a known date.

### Impact mechanism

Feedback buttons on every expiry decision: **Used it / Still good / Tossed it**. These produce a measured rescue counter rather than an asserted claim.

> "Rescued" = eaten instead of binned. Unrelated to donation.

---

## 3. Architecture

### 3.1 System diagram

```
                          ┌─────────────┐
                          │    USER     │
                          └──────┬──────┘
                                 │ photo / command / button tap
                          ┌──────▼──────┐
                          │ Telegram Bot│
                          └──────┬──────┘
                                 │ webhook
┌────────────────────────────────▼─────────────────────────────────┐
│              API / Event Handler  (AWS Lambda)                   │
│         reserved concurrency: 2   ·   idempotency keys           │
└───────┬──────────────────────────────────────────────┬───────────┘
        │                                              │
        │ user-initiated                    scheduled ─┴─ EventBridge
        │                                              │  (daily cron)
┌───────▼──────────────────────────────────────────────▼───────────┐
│         PantryAgent  —  Strands orchestrator (Sonnet 4.6)        │
│         max_iterations capped · Interventions for HITL           │
└───┬────────┬────────────┬─────────────┬───────────────┬──────────┘
    │        │            │             │               │
┌───▼────┐ ┌─▼────────┐ ┌─▼─────────┐ ┌─▼───────────┐ ┌─▼─────────┐
│Extract-│ │ Expiry   │ │  Recipe   │ │Replenishment│ │ Donation  │
│ionAgent│ │  Agent   │ │   Agent   │ │    Agent    │ │   Agent   │
│(Haiku) │ │ (Sonnet) │ │ (Sonnet)  │ │  (Sonnet)   │ │ (Sonnet)  │
└───┬────┘ └─┬────────┘ └─┬─────────┘ └─┬───────────┘ └─┬─────────┘
    │        │            │             │               │
    │   ┌────▼────────────▼─────────────▼───────────────▼────┐
    └──►│           Pantry Inventory Tool                    │
        └────────────────────┬──────────────────────────────-┘
                             │
                    ┌────────▼────────┐
                    │    DynamoDB     │
                    │  pantry_items   │
                    │  households     │
                    │  feedback_log   │
                    └─────────────────┘

              ┌──────────────────────────────┐
              │  Decision Engine             │
              │  combines all agent output   │
              │  into ONE message            │
              └──────────────┬───────────────┘
                             │
              ┌──────────────▼───────────────┐
              │  Telegram Human Approval     │
              │  (Strands Interventions)     │
              └──────────────┬───────────────┘
                             │
     ┌───────────┬───────────┼───────────┬──────────────┐
     ▼           ▼           ▼           ▼              ▼
 Cook + Shop  Shopping   Donate     Ignore     Used/Good/Tossed
                Only                              │
                                                  ▼
                                          Rescue Counter
```

### 3.2 Ingest tiers

Expiry data is resolved in priority order. Every item lands in exactly one tier and records it in `expiry_source`.

| Tier | Source | Method | Confidence |
|---|---|---|---|
| 1 | `gs1_barcode` | Parse GS1 Application Identifiers: `01` GTIN, `10` lot, `17` expiry | Deterministic |
| 2 | `ocr` | Two different vision models read the printed date; the value is kept **only if both agree** | Scored 0–1 |
| 3 | `shelf_life_table` | Purchase date + category shelf life | Low, flagged |
| — | `user_confirmed` | The household typed the date in after a disagreement | Certain |

`user_confirmed` is not an ingest tier — nothing is resolved into it automatically.
It records that a person supplied the date, which outranks every read above.

`ItemStatus.REMOVED` exists for the same reason on the item rather than the
date: an item the agent invented has to be strikeable, and it must not be
recorded as `tossed`. Tossed means real food went in the bin and counts
against the rescue figures; counting food that never existed would corrupt
the only number this product measures.

**Why tier 2 requires agreement.** Live testing on real fridge photos found a
single model reporting a date two years wrong at 0.85 confidence, and re-reading
enhanced crops of the same region reproduced that model's identical misread 3/3
times rather than correcting it — self-consistency is not evidence. Two
*different* models disagreeing was the only signal that reliably marked a
reading as untrustworthy. So disagreement is treated exactly like "unreadable":
the date is discarded, the item falls to tier 3, and it is flagged for the
household to confirm.

### 3.3 Model routing

| Agent | Model | Rationale |
|---|---|---|
| PantryAgent | `us.anthropic.claude-sonnet-4-6` | Orchestration, tool selection, combined decision |
| ExtractionAgent | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | High volume, per-item, structured output |
| ExpiryAgent | `us.anthropic.claude-sonnet-4-6` | Safety-relevant judgment |
| RecipeAgent | `us.anthropic.claude-sonnet-4-6` | Multi-constraint ranking |
| ReplenishmentAgent | `us.anthropic.claude-sonnet-4-6` | Depletion reasoning |
| DonationAgent | `us.anthropic.claude-sonnet-4-6` | Safety-relevant judgment |

Region: `us-west-2` for everything. Never mix.

### 3.4 Why Agents-as-Tools

Chosen over Swarm and Graph because the flow is a **delegation hierarchy with one decision-maker**, not peer collaboration or a fixed DAG. Sub-agents also permit per-agent model routing, which is a real cost lever at $100 total budget. This rationale goes in the README — the judging criteria reward demonstrated understanding of the choice, not just the choice.

---

## 4. Data model

### 4.1 `pantry_items` (DynamoDB)

| Field | Type | Notes |
|---|---|---|
| `household_id` | str | Partition key |
| `item_id` | str | Sort key |
| `name` | str | Canonical product name |
| `category` | enum | `dairy`, `produce`, `meat`, `deli`, `bakery`, `pantry`, `frozen`, `household`, `non_perishable` |
| `quantity` | float | |
| `unit` | str | |
| `purchase_date` | date | |
| `expiry_date` | date? | Null for `date_type = none` |
| `date_type` | enum | `use_by` / `best_by` / `sell_by` / `estimated` / `none` |
| `expiry_source` | enum | `gs1_barcode` / `ocr` / `shelf_life_table` / `user_confirmed` |
| `confidence` | float | 0–1 |
| `sealed` | bool | Required by donation eligibility |
| `high_risk` | bool | Derived from category — deli, soft cheese, ready-to-eat |
| `gtin` | str? | From GS1 tier 1 |
| `lot_number` | str? | From GS1 tier 1 |
| `estimated_daily_consumption` | float? | |
| `estimated_depletion_date` | date? | |
| `status` | enum | `active` / `used` / `tossed` / `donated` |
| `created_at` / `updated_at` | ts | |

### 4.2 `feedback_log`

| Field | Type |
|---|---|
| `household_id` | str (PK) |
| `event_id` | str (SK) |
| `item_id` | str |
| `response` | `used` / `still_good` / `tossed` |
| `estimated_value` | float |
| `timestamp` | ts |

Drives the rescue counter. This is the entire evidence base for the impact claim — do not treat it as optional.

### 4.3 Tool surface

| Tool | Owner agent | Input → Output |
|---|---|---|
| `analyze_grocery_image` | Extraction | image bytes, mode → `list[ExtractedItem]` |
| `parse_gs1_barcode` | Extraction | raw payload → `GS1Data` |
| `classify_date_label` | Expiry | label text, category → `DateClassification` |
| `add_inventory_items` | — | `list[PantryItem]` → confirmation |
| `get_inventory` | — | household_id, filters → `list[PantryItem]` |
| `update_inventory_item` | — | item_id, patch → `PantryItem` |
| `check_expiring_items` | Expiry | household_id → `list[ExpiryRisk]` |
| `predict_consumption` | Replenishment | household_id → `list[DepletionForecast]` |
| `find_recipe` | Recipe | at-risk items, pantry, prefs → `RecipeSuggestion` |
| `create_shopping_list` | Replenishment | missing + depleted → `ShoppingList` |
| `check_donation_eligibility` | Donation | `list[PantryItem]` → `list[DonationCandidate]` |
| `request_donation` | Donation | candidates, window → `DonationRequest` |
| `record_feedback` | — | item_id, response → confirmation |
| `get_rescue_stats` | — | household_id, period → `RescueStats` |

**Tool docstrings are prompts, not documentation.** The orchestrator reads them to decide what to call. A vague docstring produces wrong tool selection.

---

## 5. Action items

### Phase 0 — Foundation (blocking)

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **S-1** | SHARED | Assign roles. Update this doc and `CLAUDE.md`. | — | Both know their list | BUILT |
| **S-2** | BACKEND | **Commit `schemas.py`** — Pydantic models for every tool I/O in §4.3. No implementation. Must include `date_type`, `expiry_source`, `confidence`, `sealed`. | S-1 | Integrated to the shared branch | BUILT |
| **S-3** | BACKEND | Commit `CLAUDE.md` (models, region, design rules, out-of-scope). | S-1 | Integrated to the shared branch | DONE |
| **S-4** | INTERFACE | Commit `fixtures/` — mock data per §7. | S-2 | Integrated to the shared branch | BUILT |
| **S-5** | SHARED | AWS Builder ID for both. Credits form submitted. Team Representative appointed. | — | All three confirmed | DONE |
| **S-6** | BACKEND | Verify Bedrock invocation quota has lifted (was 0, pending Anthropic use-case review). | — | `Agent()("hi")` returns text | DONE |

> **S-2 is the critical path.** Nothing parallel happens before it lands.

---

### Phase 1 — Skeleton

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-1** | BACKEND | Python project, venv, `requirements.txt` pinned, Strands installed, directory structure. | S-2 | `pip install -r` works clean | BUILT |
| **BE-2** | BACKEND | `BedrockModel` config with **explicit** model IDs per §3.3. Never rely on SDK defaults. | BE-1, S-6 | Both models invoke | BUILT |
| **BE-3** | BACKEND | `PantryAgent` orchestrator + five sub-agent stubs, each returning `schemas.py` fixtures. Distinct system prompts per sub-agent. | BE-2, S-4 | Orchestrator delegates and returns | PARTIAL — named specialist routing is live for bounded recipe, shopping, and donation wording; the PantryAgent coordinator is not the production decision authority. |
| **IF-1** | INTERFACE | Telegram bot registered, token in `.env` (never committed), `/start` handler. | S-2 | `/start` responds | BUILT |
| **IF-2** | INTERFACE | Photo upload handler → temp storage → backend call → placeholder response. | IF-1 | Photo round-trips | BUILT |
| **IF-3** | INTERFACE | Render `list[PantryItem]` from fixtures. No backend needed. | S-2, S-4 | Fixtures render readably | BUILT |

**Phase 1 exit:** Telegram → orchestrator → stub sub-agent → Telegram, fully mocked.

---

### Phase 2 — Ingestion

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-4** | BACKEND | `analyze_grocery_image()` — receipt mode + package mode. Downscale to ~1500px before send. Return `expiry_source` honestly per item. | BE-3 | Real receipt → structured items | PARTIAL |
| **BE-5** | BACKEND | Shelf-life table (category → days). Tier 3 fallback. Include `none` category for non-perishables. | S-2 | Missing dates get flagged estimates | BUILT |
| **BE-6** | BACKEND | Dev response cache — once a receipt parses correctly, persist the JSON and reuse. | BE-4 | Re-running costs nothing | PARTIAL |
| **IF-4** | INTERFACE | Wire photo → `analyze_grocery_image` → Confirm/Edit UI. | IF-2, BE-4 | User can correct extraction | BUILT |
| **IF-5** | INTERFACE | **Surface `expiry_source` in every item row.** "Best By, read from package" vs "estimated from category". | IF-3 | Source visible on all items | BUILT |

> **BE-6 is a cost control, not a nicety.** Without it, iterating on IF-4 re-invokes vision on every reload.

---

### Phase 3 — Persistence

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-7** | BACKEND | DynamoDB tables per §4.1 and §4.2. Tag everything `Project=pantrypulse`. | BE-1 | Tables exist | BUILT |
| **BE-8** | BACKEND | `add_inventory_items`, `get_inventory`, `update_inventory_item`. Idempotency on add. | BE-7, S-2 | Round-trip persists | BUILT |
| **BE-9** | BACKEND | Derive `high_risk` from category. Deli, soft cheese, ready-to-eat, raw meat → true. | BE-8 | Flag set on ingest | PARTIAL |
| **IF-6** | INTERFACE | `/pantry`, `/expiring`, `/help` commands. | BE-8 | Real inventory renders | BUILT |

---

### Phase 4 — Expiry intelligence ⭐

> **This phase is the project.** If it does not work, nothing after it matters.

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-10** | BACKEND | `classify_date_label(label_text, category) → DateClassification`. Returns `date_type`, safety guidance, and plain-language explanation. Docstring written as a prompt. | BE-3 | Correctly separates Use By / Best By / Sell By | BUILT |
| **BE-11** | BACKEND | `check_expiring_items()` branching on `date_type` per §2. **No bare countdown anywhere.** `best_by` and `sell_by` produce no pre-expiry alert. | BE-10, BE-8, BE-9 | Best By yogurt silent before date, reassuring after | BUILT |
| **BE-12** | BACKEND | Combine multiple expiry issues into one decision context, not N alerts. | BE-11 | 5 at-risk items → 1 message | BUILT |
| **BE-13** | BACKEND | EventBridge scheduled daily invocation → Lambda → agent. | BE-12, BE-7 | Fires on schedule unattended | PARTIAL — UAT rule and Lambda target are deployed; the handler acknowledges events until household recipient discovery is implemented. |
| **IF-7** | INTERFACE | Daily check message. One per household. Reassuring copy on quality dates, firm copy on safety dates. | BE-12, S-4 | Contrast visible in message text | BUILT |

**Phase 4 exit — the demo beat:** agent reassures on a Best By yogurt and holds firm on a Use By deli item, in the same message.

---

### Phase 5 — Recipe rescue

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-14** | BACKEND | `find_recipe()` ranked by: safety-critical first → most at-risk items rescued → fewest missing ingredients → simplest prep. Returns ranking rationale. | BE-11 | Returns rescue count and missing count | BUILT |
| **IF-8** | INTERFACE | Recipe card **leading with the rescue count**: "Shakshuka — rescues 3 expiring items, missing 1". Cook This / Another Recipe. | BE-14 | Count is the first line | BUILT |

> The rescue count in line one is what makes the differentiator legible to a judge watching at 1.5×.

---

### Phase 6 — Consumption + replenishment

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-15** | BACKEND | `predict_consumption()` — heuristic only. Category defaults refined by repeat purchase history. Store `estimated_depletion_date` + confidence. **No custom ML.** | BE-8 | Produces forecasts with confidence | BUILT |
| **BE-16** | BACKEND | `create_shopping_list()` merging depleted staples + missing recipe ingredients, deduplicated. | BE-15, BE-14 | One clean merged list | BUILT |
| **IF-9** | INTERFACE | Depletion wording ("Milk is likely to run out tomorrow"). Approve / Edit / Ignore. | BE-16 | Editable list renders | BUILT |
| **IF-10** | INTERFACE | Seed 60 days of synthetic purchase history for deterministic demo. | S-4 | Consumption model has a baseline | BUILT |

---

### Phase 7 — Donation

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-17** | BACKEND | `check_donation_eligibility()`. **Stricter than personal-consumption advice.** Eligible only if: `sealed` AND not (`use_by` AND `high_risk`) AND sufficient shelf life AND safe category. | BE-9, BE-11 | Rejects anything Expiry flagged as risky | BUILT |
| **BE-18** | BACKEND | `request_donation()` via webhook / mock partner endpoint / separate Telegram recipient. Wrap as `DonationAgent`. | BE-17 | Request dispatches | BUILT |
| **IF-11** | INTERFACE | Recipient-side view: items, pickup window, Accept Pickup. Return status to household. | BE-18 | Accept/reject round-trips | BUILT |

> Donation eligibility must be **narrower** than what the agent tells you is safe to eat yourself. The intuitive implementation is backwards. Guard this in code and in the eval suite.

---

### Phase 8 — Combined decision + feedback

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-19** | BACKEND | Decision engine: what happened, what resolves automatically, what needs a human, what combines. Single output. | BE-12, BE-14, BE-16, BE-18 | One message covers all | BUILT |
| **BE-20** | BACKEND | **Strands Interventions primitive** for the approval gate. Not a hand-rolled webhook. | BE-19 | Approval suspends and resumes | BUILT |
| **BE-21** | BACKEND | Session state so approvals resume correctly after a gap. | BE-20 | Tap 10 min later still works | BUILT |
| **BE-22** | BACKEND | `record_feedback()` + `get_rescue_stats()`. | BE-8 | Counter increments | BUILT |
| **IF-12** | INTERFACE | Combined message: Cook + Shop / Donate Eligible Food / Shopping Only / Ignore. | BE-19 | Four buttons, one message | BUILT |
| **IF-13** | INTERFACE | **Used it / Still good / Tossed it** on expiry items. | BE-22 | Every tap logs | BUILT |
| **IF-14** | INTERFACE | Rescue counter line: "This month: 7 rescued, 2 tossed. ~$31 saved." | BE-22, IF-13 | Renders in daily message | BUILT |

**Phase 8 exit — MVP COMPLETE.** The demo could be recorded from here. Everything after is depth, reliability, and presentation.

---

### Phase 9 — Technical depth

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-23** | BACKEND | `parse_gs1_barcode()` — AIs `01` GTIN, `10` lot, `17` expiry. Wire as tier 1, falling back to OCR then shelf-life. | BE-4 | DataMatrix → deterministic date | PARTIAL |
| **BE-24** | BACKEND | **Strands Evals suite.** 20 date-label cases through `classify_date_label`. Tool-selection accuracy on orchestrator. Donation-eligibility safety cases. **Commit results.** | BE-10, BE-17 | Numbers in repo | PARTIAL — deterministic date/donation and topology results committed; invocation evidence pending |
| **BE-25** | BACKEND | Capture `result.metrics.get_summary()` traces — tokens, per-tool counts, success rates. | BE-19 | Screenshots saved | PARTIAL — one aggregate local capture succeeded; safe committed artifact pending |
| **IF-15** | INTERFACE | Show ingest tier per item in pantry view. | BE-23, IF-5 | Tier visible | BUILT |

> **BE-24 is the highest-leverage differentiator available.** Almost no entrant evaluates their agent.

---

### Phase 10 — Deployment

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **BE-26** | BACKEND | Lambda execution role — scoped IAM, Bedrock + DynamoDB only. No user credentials, no access keys. | BE-7 | Role assumes cleanly | BUILT |
| **BE-27** | BACKEND | Lambda **reserved concurrency = 2**. Timeout set. Cap agent `max_iterations`. | BE-26 | Verified in console | PARTIAL — UAT timeout is deployed; account concurrency constraints prevented a reservation of two. |
| **BE-28** | BACKEND | Deploy to Bedrock AgentCore. | BE-19, BE-26 | Running on AgentCore | — |
| **BE-29** | BACKEND | Public **live demo link**. | BE-28 | Works in incognito | — |
| **BE-30** | BACKEND | Add Lambda roles to the `EmergencyDenyAll` budget-action target list. | BE-26 | Kill switch covers compute | — |

---

### Phase 11 — Submission

| ID | Owner | Task | Depends on | Done when | Status |
|---|---|---|---|---|---|
| **S-7** | SHARED | **FEATURE FREEZE.** | Phase 10 | No new features | BUILT — feature work frozen; only release verification, documentation, and submission materials proceed without explicit approval. |
| **BE-31** | BACKEND | Architecture diagram matching what actually shipped. | S-7 | Committed image | — |
| **IF-16** | INTERFACE | README per §10. Include *why* Agents-as-Tools was chosen. | S-7 | Renders correctly | — |
| **IF-17** | INTERFACE | Record + edit demo video (§9). | S-7 | Public on YouTube/Vimeo | — |
| **IF-18** | INTERFACE | 250–400 word submission description. | IF-17 | Drafted | — |
| **S-8** | SHARED | Three blog posts on builder.aws.com, "Agents for Humans" in title. | S-7 | All live | — |
| **S-9** | SHARED | Fresh-clone test using **only** README. Incognito link check. License visible in GitHub About. | IF-16 | Clean run | — |
| **S-10** | SHARED | Submit. | S-9 | Submitted | — |
| **S-11** | SHARED | **Leave the stack running through Oct 8.** | S-10 | Nothing torn down | — |

---

## 6. Dependency map

```
S-1 ──► S-2 (schemas) ──┬──► BE-1 ──► BE-2 ──► BE-3 ──┬──► BE-4 ──► BE-6
                        │                             │      │
                        │                             │      └──► BE-23
                        │                             │
                        │                             └──► BE-10 ──► BE-11 ──► BE-12 ──► BE-13
                        │                                              │           │
                        │                                              │           └──► BE-19
                        │                                              └──► BE-14 ──┘
                        │                                                            │
                        ├──► S-4 (fixtures) ──► IF-3 ──► IF-5 ──► IF-15             │
                        │                                                            │
                        └──► IF-1 ──► IF-2 ──► IF-4 ──► IF-6 ──► IF-7 ──► IF-8 ──► IF-12
                                                                                     │
BE-7 ──► BE-8 ──┬──► BE-9 ──► BE-17 ──► BE-18 ─────────────────────────────────────┘
                ├──► BE-15 ──► BE-16 ──────────────────────────────────────────────┘
                └──► BE-22 ──► IF-13 ──► IF-14

BE-19 ──► BE-20 ──► BE-21 ──► BE-25
BE-26 ──► BE-27 ──► BE-28 ──► BE-29
```

**Longest chain:** `S-2 → BE-1 → BE-2 → BE-3 → BE-10 → BE-11 → BE-12 → BE-19 → BE-20 → BE-28`. Protect it. Everything else has slack.

**Interface is only blocked three times:** IF-4 (needs BE-4), IF-7 (needs BE-12), IF-12 (needs BE-19). Everything else can proceed against fixtures.

---

## 7. Mock data plan

Mock data is not a convenience — it is what decouples the two roles and what makes the demo deterministic and cheap.

### 7.1 `fixtures/` contents

| File | Purpose |
|---|---|
| `extracted_items_receipt.json` | 12-item receipt output, mixed `date_type` and `expiry_source` |
| `extracted_items_package.json` | 4 items from package photos, includes one GS1 hit |
| `pantry_state_demo.json` | 30-item pantry with known expiry distribution |
| `purchase_history_60d.json` | 60 days of receipts so consumption prediction has a baseline |
| `expiry_risks_mixed.json` | Deliberate mix: Best By passed, Use By tomorrow, Sell By irrelevant, estimated low-confidence |
| `recipe_shakshuka.json` | Rescues 3 items, missing 1 |
| `donation_candidates.json` | 2 eligible sealed items, 1 correctly rejected |
| `rescue_stats.json` | Two months of data showing tossed count declining |

### 7.2 Rules

- **Fixtures conform to `schemas.py`.** If a fixture won't validate, the schema changed and someone didn't say so.
- **Every fixture is committed.** Judges cloning the repo should be able to run the flow without AWS credentials.
- **Dev response caching (BE-6)** applies to real model output — once a receipt parses correctly, persist and reuse. Iterating on rendering must not re-invoke vision.
- **The demo runs on seeded data, not live capture.** Video is recorded, not live-judged. There is no reason to gamble on OCR in the take.

### 7.3 Demo seed scenario

One household, one deterministic state, exercising every branch:

| Item | `date_type` | State | Expected behaviour |
|---|---|---|---|
| Greek yogurt | `best_by` | 2 days past | **Reassure** + rescue recipe |
| Sliced turkey | `use_by` | tomorrow, `high_risk` | **Firm warning**, not donatable |
| Baby spinach | `estimated` | 1 day left, low confidence | Flag with visible uncertainty |
| Milk | `sell_by` | passed | **Suppress** — not a consumer deadline |
| Honey | `none` | — | Never counted down |
| Canned tomatoes ×4 | `best_by` | 8 months, sealed | **Donation eligible** |
| Eggs | `estimated` | depleting | Shopping list via consumption model |

That table is also your video shot list.

---

## 8. Testing plan

### 8.1 Unit — deterministic, no model calls

| Area | Cases |
|---|---|
| Date parsing | `03/04/25` ambiguity, lot codes resembling dates (`L2470319`), missing year, malformed |
| GS1 parsing | Valid AI sequences, missing AI `17`, unknown AIs, malformed payload |
| Shelf-life fallback | Every category, plus `none` for non-perishables |
| Risk rules | Each `date_type` × before/on/after expiry × high_risk true/false |
| Donation eligibility | Unsealed rejected, `use_by`+`high_risk` rejected, short shelf life rejected |
| Deduplication | Same item on two receipts, unit mismatches |

### 8.2 Agent evaluation — Strands Evals SDK (BE-24)

| Suite | Measures |
|---|---|
| Date-label classification | 20 labelled cases → accuracy on `date_type` |
| Tool selection | Does the orchestrator call the right tool for each intent? |
| Tool parameters | Are arguments well-formed? |
| **Donation safety** | No item flagged risky by Expiry is ever offered for donation. **Zero tolerance.** |

Commit results. This is evidence, and almost no competitor will have it.

### 8.3 Integration

- Telegram photo → extraction → persistence → retrieval
- Scheduled trigger → expiry check → combined decision → Telegram
- Button tap → feedback logged → counter updates
- Approval suspends and resumes correctly after a delay

### 8.4 Failure and edge cases

| Scenario | Required behaviour |
|---|---|
| Blurry / partial receipt | Graceful partial extraction, ask user to confirm — never a raw traceback |
| Unknown product | Accept with `estimated` + low confidence, don't drop it |
| Duplicate button tap | Idempotent, no double action |
| DynamoDB failure | Friendly message, retry, no data loss |
| Model timeout | Fallback message, no hang |
| Recipe returns nothing | Say so, offer shopping-only |
| Donation rejected | Return status cleanly to household |
| Zero at-risk items | **Send nothing.** Silence is a correct outcome. |
| Agent loop | `max_iterations` cap trips before budget damage |

### 8.5 Cost tests

- Confirm Haiku is actually being used for extraction (check traces, not intent)
- Confirm `max_tokens` capped on every call
- Confirm Lambda reserved concurrency = 2
- Run the full demo flow once and record actual cost — this number goes in the README

### 8.6 Submission QA (S-9)

- Fresh clone, follow README only, no tribal knowledge
- All links in incognito
- License shows in GitHub **About** sidebar, not just as a file
- No secrets in repo, no secrets visible in video
- Live demo link reachable without auth

---

## 9. Demo video plan (max 5:00)

| Time | Section | Content |
|---|---|---|
| 0:00–0:30 | Hook | "There are a dozen apps that track food expiry dates. They all lose to the same thing — you stop entering items. And the ones that survive still get the important part wrong: they count down to a printed date and tell you to throw the food out, when roughly a fifth of consumer food waste is people misreading those labels in the first place. PantryPulse doesn't ask you to maintain anything, and it tells you what the date actually means." |
| 0:30–0:50 | Who it's for | Busy households already trying to waste less and doing it badly by hand. Not persuading anyone to care — removing the labour. |
| 0:50–1:10 | What it is | Autonomous agent, Strands Agents SDK on Amazon Bedrock. Send a receipt. It handles the rest. |
| 1:10–3:30 | **Demo** | Receipt → extraction with **source labels visible** → background check fires → one combined message → **KEY BEAT: Best By yogurt reassured, Use By deli firm** (pause here) → recipe "rescues 3, missing 1" → Cook + Shop → *optional 30s donation* → Used it → counter updates |
| 3:30–4:00 | Architecture | Orchestrator + five sub-agents, model routing, persistent state, scheduled runs, HITL, AgentCore. Show real traces. |
| 4:00–4:30 | Why it matters | "Every answer you give it makes the number real. Not a claim. A measurement." |

**Protect the contrast beat.** If anything gets cut for time, it is not that.

**Donation is conditional.** Include only if the recipient side looks real. A mock accepting a mock discounts everything around it.

Do not name competitors.

---

## 10. README structure

What is PantryPulse? · The Problem *(lead with date-label misreading)* · Who It's For · What It Does · Why an Agent? · Demo *(video + live link)* · Key Features · How It Works · Architecture *(diagram)* · Agent Workflow · Strands Agents SDK *(including topology rationale)* · AgentCore Deployment · **Evaluation Results** · Project Structure · Installation · Configuration · Running Locally · Telegram Setup · Example Workflow · Safety & Human Approval *(Use By vs Best By; why donation eligibility is stricter)* · Limitations *(honesty scores well)* · Future Work · Team · License

---

## 11. Guardrails

**Cost.** $100 total. Haiku for extraction. `max_tokens` ~1000. Cap `max_iterations`. Lambda concurrency 2. Cache dev responses. Downscale images to ~1500px. Check the billing dashboard daily.

**Security.** No credentials in the repo, in `CLAUDE.md`, or in any shared doc. Push protection on. IAM roles for compute, never access keys. Rotate any key that has ever been pasted anywhere.

**Scope.** Do not build: custom ML consumption models, custom OCR, native app, web dashboard, payment processing, automatic checkout, real-time fridge vision, retailer scraping *(also a rules violation)*, large recipe database, volunteer marketplace, complex auth, multi-household analytics.

**Priority if time runs short — cut from the bottom:**

1. End-to-end working agent
2. **`date_type` classification** — cut this and it's a generic pantry app
3. Strands multi-agent orchestration
4. Autonomous background behaviour
5. Combined human decision
6. Receipt / photo ingestion
7. Recipe rescue with visible ranking
8. Feedback buttons + rescue counter
9. Consumption prediction
10. Shopping list
11. GS1 barcode parsing
12. Evals suite
13. Donation workflow

---

## 12. Reference

- Rules: https://agentsforhumans.devpost.com/rules
- Credits form: https://forms.gle/6sjzKiX6bKUMA5NEA *(Sep 11, 12pm PT)*
- Blog bonus: https://builder.aws.com
- Strands docs: https://strandsagents.com

Credentials live in the shared password vault. Never in this document.

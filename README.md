# Speed-to-lead agent

An AI agent that answers a new lead in seconds, asks only what is still missing, scores the lead,
routes it to the right office and rep, books an appointment, writes a summary and mapped fields to
the CRM, and pings the rep. A human can take over at any time.

The **engine never mentions a specific company**. Everything that differs between businesses lives
in one folder of config files, so a new company is config, not code. Two fictional companies ship
as fixtures: **Sunrise Solar** (solar installer) and **First Lakes Mortgage** (lender).

```
lead arrives ─▶ check CRM ─▶ reply fast ─▶ ask only missing questions ─▶ score + route by zip
            ─▶ offer slots ─▶ book ─▶ write CRM ─▶ notify rep          (human can take over)
```

## Quick start

Needs Python 3.12 and Node 20+. If `python3.12` is not at `/usr/local/bin/python3.12`, run
`PYTHON=$(which python3.12) make setup`.

```bash
make setup                      # venv, Python deps, web deps, Playwright's Chromium
cp .env.example .env            # then set ANTHROPIC_API_KEY
make demo                       # API on :8000, UI on http://localhost:5173
```

Everything external is mocked by default (chat channel, CRM, calendar, Slack), so only the model
needs a key. In the UI, type a lead and press **Send lead**, or pick a saved scenario and press
**Play**. The dev header (company switcher, simulated clock) shows in dev mode.

For a clean recording without the dev header, build the UI once and let the API serve it:

```bash
cd web && npm run build && cd ..
python run.py --company sunrise_solar        # http://localhost:8000  (add ?dev=1 for the dev header)
```

| Command | What it does |
|---|---|
| `make setup` | Create `.venv`, install everything |
| `make demo` | API + Vite dev server. `COMPANY=first_lakes_mortgage make demo` opens another company |
| `make test` | Ruff, pytest, Vitest, the Playwright smoke test, and `npm run build` |
| `make web-test` | Vitest plus the Playwright smoke test (submit a lead, see a booked appointment) |
| `make eval` | Run every company's scenarios against the live model, print a table and metrics |
| `make gen-api` | Re-export the OpenAPI schema and regenerate the typed web client |
| `python run.py --company <slug> --check` | Validate a company's config and exit |

## How it works

**Agent.** A Claude tool-calling loop (default `claude-sonnet-5-5`, set with `ANTHROPIC_MODEL`) with
nine tools: `search_knowledge`, `check_existing_contact`, `score_lead`, `get_slots`,
`book_appointment`, `send_message`, `update_crm`, `notify_rep`, `escalate_to_human`. The system
prompt is one shared template filled from `company.yaml` and `qualification.yaml`.

**Guardrails are enforced in code, not only in the prompt:**

| Rule | How it is enforced |
|---|---|
| No prices, rates, financing terms or guarantees unless in `knowledge/` | `send_message` blocks any message whose numbers or terms are not in the knowledge base or the lead's own words, and tells the model to say a rep will confirm |
| Escalate on anger, a request for a person, or two unanswered questions | Detected deterministically, told to the model, and completed by a backstop if the model does not |
| Quiet hours | Outbound messages are held and delivered when quiet hours end |
| STOP / opt-out | Handled before the model runs. Consent is recorded per lead. One unsubscribe confirmation, then silence |
| Lead messages are untrusted | Escaped and wrapped in tags, injection patterns flagged, and the tools refuse bad calls (invented slots, unknown fields, booking before qualifying) |
| Out of area or disqualified | Never booked. Polite close, logged. Spam is closed silently with nothing written to the CRM |

**Safety nets.** If the model forgets a step (reply, CRM write, rep ping, escalation), a backstop
completes it and records a `backstop:*` flag. The evals report how often that happens.

**Persistence and observability.** SQLite stores every lead, message, tool call (name, args,
result, latency), score breakdown, notification and timing, including `first_response_seconds`.
Logs are structured JSON. The UI streams live updates over Server-Sent Events.

```
 channel ──▶ intake API ──▶ agent loop ◀──▶ Claude
 (mock/Twilio)   │             │  tools ─▶ CRM (mock/HubSpot) · Calendar (mock) · Notifier (mock/Slack)
                 ▼             ▼
              SQLite ◀── events ──▶ SSE ──▶ React UI (simulator · rep view · agent trace)
                  ▲
        companies/<slug>/*.yaml + knowledge/*.md   (the only company-specific code)
```

## What each config file controls

Everything lives in `companies/<slug>/`. A test fails if any company slug or name appears under
`src/` or `web/src/`. If you need an `if company == ...`, the logic belongs in config.

**`company.yaml`** : identity, voice and when the agent may speak.

| Key | Controls |
|---|---|
| `name`, `description` | Used in the prompt and the UI header |
| `tone` | The voice the agent writes in |
| `reply_signature` | Signs the first message only |
| `timezone` | IANA zone for quiet hours, business hours and slot labels |
| `business_hours` | `mon`..`sun` as `"HH:MM-HH:MM"`. Missing days are closed |
| `quiet_hours` | No outbound texts in this window (may wrap midnight) |
| `service_area_zips` | Zip codes served. Ranges like `"80202-80212"` work. Others are closed as out of area |
| `logo`, `brand_color` | Loaded by the UI at runtime and applied through CSS variables |

**`qualification.yaml`** : what to ask and how to score.

| Key | Controls |
|---|---|
| `required_fields` | Questions the agent asks. Types: `text`, `choice`, `number`, `boolean`, `zip`. Choice options must be `lower_snake_case`. A `zip` field is required |
| `disqualify_if` | Rules (all `when` conditions must match). Optional `close_message` |
| `score_weights` | Points per matched rule. Ops: `eq neq in not_in lt lte gt gte exists` |
| `hot_lead_threshold`, `warm_lead_threshold` | Score tiers. Hot must be reachable |

**`routing.yaml`** : who gets the lead.

| Key | Controls |
|---|---|
| `offices` | Each has `zips` and `reps`. Zip to office routing, round robin within an office |
| `reps` | `name`, `email`, optional `slack_user_id`, and `business_hours` that drive their calendar |
| `appointment` | `kind`, `duration_minutes`, `slots_to_offer`, `lookahead_days`, `minimum_notice_hours`, optional `confirmation_note` (said word for word when a booking is confirmed) |
| `hot_lead` | Immediate notification, @mention, earliest slots |
| `slack_channel` | Shown in notifications |

**`crm_mapping.yaml`** : how a lead becomes a CRM record: `crm` (hubspot), `pipeline`,
`stage_on_create`, `stage_on_booked`, and `field_map` from engine keys (your qualification keys plus
`summary`, `lead_score`, `score_tier`, `assigned_office`, `assigned_rep`, `appointment_time`,
`consent_status`, `source`) to CRM property names.

**`knowledge/*.md`** : the only facts the agent may state. Retrieval is BM25 behind an interface,
and every hit carries its source file. HTML comments are ignored.

## Add a new company

**Fastest: draft it from the website.**

```bash
python scripts/draft_company.py --url https://example.com --slug acme_roofing
grep -rn TODO companies/acme_roofing        # resolve every one
python run.py --company acme_roofing --check
```

The drafter scrapes the public site (respecting robots.txt), has Claude extract claims with
verbatim quotes, and **verifies every claim against the page text**. Verified facts carry
`# source: <url>`. Guesses carry a proposed value and `# TODO: guess`. Unknown values are the
literal `TODO`. Reps are never on public sites, so they are always `TODO`. The engine refuses to
run a company while any `TODO` remains, with a count and the file and line of each.

**Or copy a fixture:** `cp -r companies/sunrise_solar companies/my_company` and edit.

Then:

1. `python run.py --company my_company --check` until it loads.
2. Add `evals/scenarios/*.yaml` for it (see below) and run `make eval`.
3. `python run.py --company my_company` (it also appears in the UI's company switcher).

## Enable HubSpot

The HubSpot adapter has only been tested against a faked HubSpot API, not a live account.

1. Create a free HubSpot developer account, then a **private app** with scopes
   `crm.objects.contacts.read/write`, `crm.objects.deals.read/write`, `crm.schemas.contacts.read/write`
   and `crm.schemas.deals.read`.
2. Create a **deal pipeline** whose name and two stage names match `crm_mapping.yaml` exactly.
3. Put the token in `.env`: `HUBSPOT_TOKEN=...` and `CRM_ADAPTER=hubspot`.
4. Create the contact properties the mapping writes:
   ```bash
   python scripts/hubspot_properties.py --company sunrise_solar            # list them
   python scripts/hubspot_properties.py --company sunrise_solar --create   # create missing ones
   ```

Contacts get the mapped properties and a deal in your pipeline moves from `stage_on_create` to
`stage_on_booked`.

## Enable Slack

Also tested only against a faked endpoint.

1. Create a Slack app, turn on **Incoming Webhooks**, add one for the channel you want, copy the URL.
2. `.env`: `NOTIFIER_ADAPTER=slack` and `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`.
3. For real @mentions, add `slack_user_id: U0123456` to each rep in `routing.yaml`.

The webhook posts to the channel it was created for. `slack_channel` in `routing.yaml` is shown in
the UI and the message.

**Not wired yet:** `CHANNEL_ADAPTER=twilio` and `CALENDAR_ADAPTER=google` are stubs that raise a
clear `NotImplementedError`.

## Evals

`make eval` runs every company's scenarios from `evals/scenarios/*.yaml` against the **live model**
(needs `ANTHROPIC_API_KEY`), prints a table, and saves `evals/results/<timestamp>.json`
(git-ignored). Sunrise Solar has 28 scenarios and First Lakes Mortgage has 19, including: out of
area, renter, angry customer, spam, discount request, a question outside the knowledge base,
prompt injection, STOP, after-hours lead, an existing CRM contact, and all info in one message.

| Metric | Meaning |
|---|---|
| First response, median and p95 | Seconds from lead creation to the first message actually sent |
| Qualification accuracy | Scenarios where the expected qualified/tier outcome matched |
| Routing accuracy | Scenarios where the expected office matched |
| Booking rate | Booked, among scenarios that should book |
| Guardrail violations | Independent audit of every run: unsupported claims sent, sends in quiet hours, more than one message after STOP, booking a disqualified lead, spam in the CRM, leaked tool names or prompt text |

Assertions are **deterministic** (tier, office, booked, escalated, opted out, flags, text that must
or must not appear). An **LLM judge** (`claude-haiku-5-5`) is used only where code cannot express the
requirement, such as tone or honesty, in a minority of scenarios. `--no-judge` skips it.

```bash
make eval EVAL_ARGS="--repeat 3"                       # repeat each scenario to see variance
make eval EVAL_ARGS="--only hot_lead_books --no-judge"
```

Exit codes: `0` all passed with no violations, `1` a scenario failed or a guardrail was violated,
`3` the model API failed (for example billing). Runs hit by an API error are marked `ERROR` and
never counted as the agent failing.

A scenario is a YAML file: a `lead`, optional `followups` (the lead's later messages), an optional
simulated `clock`, optional `seed_contacts` already in the CRM, and an `expect` block. The same
files power the UI's **Replay a saved scenario** control.

## API

Interactive docs at `http://localhost:8000/docs`. The React client's types are generated from
`web/openapi.json`, and a test fails if that file is stale.

| Endpoint | Purpose |
|---|---|
| `POST /api/leads` | Submit a lead. Returns at once. The agent replies in the background |
| `POST /api/intake/web-form`, `/missed-call`, `/sms` | Webhooks. Set `WEBHOOK_SECRET` to require `X-Webhook-Secret` |
| `GET /api/leads/{id}` | Everything about a lead: messages, score breakdown, routing, booking, CRM preview, notifications, tool calls |
| `GET /api/leads/{id}/events` | Server-Sent Events, resumable with `Last-Event-ID` |
| `POST /api/leads/{id}/messages` | The lead replies |
| `POST /api/leads/{id}/takeover`, `/human-message` | A person takes over |
| `GET /api/companies`, `/api/companies/{slug}/config` | Branding and public config for the UI |
| `GET /api/scenarios`, `POST /api/scenarios/{id}/replay` | Saved scenarios |
| `PUT /api/clock` | Pretend it is another time (for example 10:30pm) |

## Troubleshooting

- **`ANTHROPIC_API_KEY is not set`** : add it to `.env`. Reads work without a key. Anything that runs the agent needs one.
- **`credit balance is too low`** : an Anthropic billing problem. The agent escalates to a human instead of going silent, and evals report it as an invalid run.
- **`ModuleNotFoundError: leadagent` on macOS** : the editable install's `.pth` file can get a hidden flag that Python ignores. `make setup` clears it. The Makefile and pytest also add `src/` to the path.
- **A company will not load** : `python run.py --company <slug> --check` lists every problem, each with its file.
- **Replies are held** : you are inside quiet hours. Use the dev header's *Business hours* clock preset.

## Layout

```
companies/<slug>/      company config (the only company-specific files)
src/leadagent/         engine: config, scoring, routing, tools, agent, adapters, server, evals, onboarding
web/                   React + Vite + TypeScript + Tailwind UI, Vitest tests, Playwright smoke test
evals/scenarios/       synthetic leads with expected outcomes
scripts/               draft_company.py, hubspot_properties.py, export_openapi.py, e2e_server.py
tests/                 backend tests
docs/LOOM_SCRIPT.md    outline for the recorded walkthrough
```

# What we changed in UpTime.ai, and what we learned

This document walks through every change on the `oncall-improvements` branch. For each one it covers the problem, the fix, why the fix works, the before/after numbers, and three interview questions with answers. It's written for a CS student, so jargon is explained the first time it appears.

All numbers come from scripts in `eval/` and are saved in `eval/results/`. The commands to reproduce them are at the end.

---

## Read this before quoting any number

**The eval set is 48 synthetic Sentry alerts, not production traffic.** Each one is a realistic Sentry `event_alert` webhook payload (a null pointer in checkout, a DB timeout, a typo in a log message, a failed login, and so on). They point into `eval/fixture_repo/`, a small online-shop backend written for this eval so that "GitHub repo context" has real code to read.

**One person wrote the labels.** Each case has a severity (`high` / `medium` / `low`), an escalate yes/no, and a one-line rationale. The labels follow a rubric stored at the top of `eval/eval_errors.json`. Reasonable on-call engineers would disagree on some of them, and the medium/high boundary is the most subjective part.

**How we kept ourselves honest:**
- The labels were committed to git (`6dcad0b`, `815c5f1`) and reviewed before any assessor ran, including the free rule-based one.
- 9 cases deliberately split severity from escalation. Examples: an outage that has already recovered is high but shouldn't page; a TLS certificate about to expire is medium but should page. Without them, "escalation accuracy" would just repeat severity accuracy.
- The repo-context runs read the fixture from GitHub at a pinned commit (`43b0a2d`), so later commits can't change what the model saw.
- Every Gemini call, retries included, is appended to `eval/results/gemini_calls.log`, and the code refuses calls past the cap. Total: **118 calls** (budget 170).
- We report what got worse, not only what improved.

**What n = 48 means.** One case is about 2 percentage points. A 3-case gap (for example escalation 40/48 vs 43/48) is a signal worth reporting, not proof.

---

## 1. The "real-time dashboard" was a static mockup

**Problem.** `frontend/src/App.tsx` on `main` rendered four hardcoded events and made zero API calls. A live version had existed: commit `e529e72` polled `/api/incidents` and `/api/recommendations` every 4 seconds. The merge in `8599a7f` replaced it with a design mockup, probably by taking one side of a conflict.

**How we found it.** We searched every version of `App.tsx` in git history for `fetch(` and `setInterval`. `e529e72` had 6 matches; the merge commit had 0.

**Fix.** Restored `App.tsx`, `App.css` and `index.css` from `e529e72`, kept the newer logo, and added the assessment to each event row: a severity badge, "· page" when it escalates, and the model's one-line reason. Each row also carries `data-incident-id` and `data-assessed` attributes, so a test can wait for exactly one incident's assessment.

**Why it works.** The dashboard now reads the same database the agents write to. "Real-time" here means polling every 4 s, which section 9 measures.

**Before/after.**

| | Before (`main`) | After |
|---|---|---|
| API calls from the dashboard | 0 (hardcoded data) | `GET /api/incidents/` and `/api/recommendations/` every 4 s |
| Webhook → assessment visible in a real browser (20 cases) | not possible | p50 **3.9 s**, p95 **8.0 s** |

**Interview questions**
1. *How can a merge silently delete a feature?*
   When both branches changed the same file, whoever resolves the conflict can pick "theirs" for the whole file, and the other side's work vanishes without any error. Reviewing the merge diff, or having a test that hits the real API, catches it.
2. *Why put `data-*` attributes on UI elements?*
   They give tests a stable hook that doesn't depend on styling or wording. Our latency test waits for `[data-incident-id="7"][data-assessed="true"]` instead of guessing from text.
3. *Polling vs. WebSockets or Server-Sent Events for a dashboard?*
   Polling is simple and stateless, but adds up to one interval of delay and wastes requests when nothing changes. Push (WebSockets or SSE) delivers updates immediately but needs connection handling. Our numbers show polling adds about 2 s on average, which is a fair trade for a triage console.

---

## 2. The agent's severity never left a log file

**Problem.** The investigation agent computed a severity, but the database's `Incident.severity` field stored Sentry's raw `level` instead (`error`, `warning`...). The agent's own value only appeared in `workflow_trace.log` and inside a notes string, so nothing a user could see reflected the "assessment".

**Fix.** New columns on `Incident`: `agent_severity`, `escalate`, `escalation_reason`, `assessor` and `assessed_at`. The investigation agent writes them as soon as it decides, and a small migration adds them to existing SQLite databases.

**Why it works.** The decision is stored where the API and dashboard read from. `assessed_at` and `created_at` (when the webhook arrived) also make server-side latency measurable.

**Before/after.** Before: 0 of the agent's severity decisions reached the API. After: every incident in the 20-case end-to-end run had its assessment returned by `GET /api/incidents/` and shown on the dashboard.

**Interview questions**
1. *Why keep both `severity` (Sentry level) and `agent_severity`?*
   They answer different questions. Sentry's level says how the code logged the event; our severity says how bad it is for users. Keeping both lets you compare them, which is how we found that Sentry levels alone are a poor severity signal.
2. *Why store `assessor` with each decision?*
   So you can tell which system made it (rules, LLM, LLM plus repo context, or a fallback after the LLM failed). Without it, a silent fallback looks exactly like a model answer.
3. *What's a "lightweight migration", and when is it not enough?*
   Here it means running `ALTER TABLE ... ADD COLUMN` at startup if a column is missing. That's fine for adding nullable columns in SQLite. Renames, type changes or multiple servers need a real migration tool such as Alembic, with versioned scripts.

---

## 3. Severity and escalation: from keyword rules to an LLM

**Problem.** Severity was three `if` statements: `high` if the Sentry level was `fatal`, the HTTP status was 5xx, or the text contained "critical"; `medium` if the level was `error`; otherwise `low`. There was no escalation decision at all.

**Fix.** `backend/app/services/severity_service.py` has one output shape, `severity`, `escalate` and `reason`, produced by three interchangeable assessors:
- `rules`: the original keyword logic, kept unchanged as the baseline. It escalates exactly what it calls `high`.
- `llm`: Gemini (`gemini-3.5-flash-lite`, temperature 0) reads the parsed alert. The prompt gives it a written rubric and asks for JSON that must match a schema.
- `llm_repo`: the same, plus the source files named in the stack trace and the repo README, loaded from GitHub.

If the model call fails or returns invalid JSON, the code falls back to `rules` and records `assessor = "llm_fallback_rules"`. Rate limits (429) and 5xx errors are retried twice, and each attempt counts against the budget.

**Why it works.** The keyword rule only sees how the code logged the event. A 500 on an internal admin report is "high" to the rule, and a `warning` saying the DB disk fills in 4 hours is "low". The LLM reads what the alert *says*: the route, the environment, the numbers in the message.

**Before/after** (all 48 cases)

| | Rules (original) | LLM, no context |
|---|---|---|
| Severity accuracy | 21/48 (43.8%) | **32/48 (66.7%)** |
| Escalation accuracy | 31/48 (64.6%) | **40/48 (83.3%)** |
| Needed pages caught (recall) | 10/17 | **16/17** |
| Pages sent (of which correct) | 20 (10) | 23 (16) |
| Model fallbacks | n/a | 0 |

Rules errors are mostly structural. Every `error`-level event becomes at least medium, so 10 of 16 low cases were called medium. And everything that arrives as a `warning` message becomes low: all 4 "medium but page" cases and the 2 recovered-outage cases.

**Interview questions**
1. *Why keep the rule-based version around after adding the LLM?*
   As a baseline (you can't say the LLM "helps" without one) and as the fallback when the model is down. An on-call tool that stops triaging when a third-party API fails is worse than the rules.
2. *How do you make an LLM return something your code can rely on?*
   Ask for JSON, enforce a response schema (an enum for severity, a boolean for escalate), validate it again in code, and treat anything else as a failure with a fallback. Never parse free text with regexes if you can avoid it.
3. *Why temperature 0, and does it make the model deterministic?*
   It makes the most likely answer win, which reduces variation, but it doesn't guarantee identical outputs. Section 10 measures this: 2 of 20 severities changed between two runs with the same input.

---

## 4. Does GitHub repo context actually help?

**Problem.** The original GitHub agent only fed code to the *patch* generator, so it couldn't influence severity. We wanted to test whether reading the failing code makes triage better. Many alerts look scary but are handled: the cart code falls back to Postgres when Redis is down, the payment code reports every retry attempt to Sentry, the recommendations widget swallows its errors. Others are worse than they look: the tax lookup has no fallback, so a tax-service timeout blocks every checkout.

**Fix.** The webhook now extracts the in-app stack frames from the Sentry event (`_stack_from_event`). The `llm_repo` assessor loads those files and the README from GitHub before calling the model. The loader also gained a source-root prefix (for monorepos) and a token-free path for public repos via `raw.githubusercontent.com`.

**Before/after**

| | LLM, no context | LLM + GitHub context |
|---|---|---|
| Severity accuracy (48) | **32/48 (66.7%)** | 31/48 (64.6%) |
| Escalation accuracy (48) | 40/48 (83.3%) | **43/48 (89.6%)** |
| Pages sent (of which correct) | 23 (16) | **18 (15)** |
| Needed pages caught | **16/17** | 15/17 |
| 20 cases where the label depends on the code: severity / escalation | 12/20 / 15/20 | **14/20 / 18/20** |
| 28 other cases: severity / escalation | **20/28** / 25/28 | 17/28 / 25/28 |

**Honest answer: context helps escalation and hurts severity slightly.** It cut false pages from 7 to 3, which is the thing on-call engineers complain about most, and it helped on the cases built to need code. But overall severity didn't improve, and it broke as many cases as it fixed (both fields right vs. not):
- **Fixed (5):** E14 admin report timeout, E17 email retried by the worker, E25 one payment timeout that was retried, E31 widget error swallowed, E32 manual backfill script.
- **Broken (5):** E05, E11, E19, E34, E43.

**Why it broke those five: the model over-trusts the code it reads.**
- **E05 (payment webhooks rejected).** The fixture comment says the provider retries for 72 hours *and the order stays unshipped until then*. With context the model said "the provider automatically retries", so low, no page. It read the reassuring half of the comment.
- **E11 (live payment key leaked into Sentry).** With context it saw the retry loop and called it "expected retry behavior", so low. Without context it said high/page, but its reason was the 500 error, not the leaked secret. **Neither mode noticed the secret.** That one is right for the wrong reason.
- **E34 (staging DB timeout).** With context the model raised severity to high while saying the staging alert doesn't need a page.

**Interview questions**
1. *Why can adding more context make an LLM worse?*
   Context competes for attention. Code comments that explain how a failure is *usually* handled can override the evidence in the alert itself. In E05 and E11 the model trusted "this is retried" over "this failed after retries" or "this contains a secret".
2. *How would you decide which files to send the model?*
   Start from the stack trace's in-app frames, nearest to where the error was raised first, then add a few high-value files (README, routing). Sending everything is slow and dilutes attention. We cap at 4 stack files plus the README, 4,000 characters each.
3. *How would you get the benefit without the regressions?*
   Use context only to *downgrade* when the code shows a fallback that actually ran (the request still returned 200), and never to downgrade security signals such as secrets or auth anomalies. Or let a small set of hard rules override the model: anything matching a secret pattern always pages.

---

## 5. Escalation needs facts the prompt didn't have

**Problem.** "Should we page someone?" often depends on facts outside the stack trace. Is this already being worked on? Is there planned maintenance right now? What time is it? The first prompt only had the error. Recent incidents were passed as title plus Sentry level, without their status.

**Fix.** The webhook now also extracts Sentry tags and the event time. Recent incidents include their status (for example `investigating`) and their notes. The prompt tells the model that an alert can describe something already recovered, already being worked, or expected during planned work. These changes were committed (`457a6cb`) before any LLM run.

**Before/after** (the 9 cases where severity and escalation disagree)

| | Rules | LLM, no context | LLM + GitHub context |
|---|---|---|---|
| Escalation correct | 2/9 | 8/9 | **9/9** |
| Severity correct | 2/9 | **3/9** | 1/9 |

The models get the *paging* decision right but mix the two fields. For an outage that already recovered (E41, E44) they lower the *severity* instead of keeping it high and not paging. For "page now" cases (E45 TLS expiry, E47 climbing error rate, E48 credential stuffing) they raise severity to high. In other words the model treats severity as "how urgent", while the rubric defines it as "how bad".

**Interview questions**
1. *What's the difference between severity and urgency, and why separate them?*
   Severity is how bad the impact is or was; urgency is whether someone must act right now. A recovered outage is severe but not urgent, and needs a postmortem rather than a page. A certificate expiring on Sunday is not yet harmful but is urgent. Mixing them leads to either missed pages or alert fatigue.
2. *Why is deduplicating against open incidents important?*
   One root cause can fire dozens of alerts. Paging for each one wakes people repeatedly and buries new problems. Both LLM modes correctly declined to re-page E42, a duplicate of an acknowledged incident. The rules can't, because they never look at history.
3. *If you could only fix one thing about the model's behavior here, what would it be?*
   Make it decide the two fields separately: one prompt (or one field definition) for impact and one for timing, with examples. Its current answers show it collapses them into one urgency score.

---

## 6. The validation agent crashed on every recommendation

**Problem.** In the first end-to-end run, no recommendation ever appeared. The validation agent's log showed `ValueError: Datetime values must have timezone information`. `Recommendation.created_at` defaulted to `datetime.utcnow()`, which returns a "naive" datetime with no timezone, and the installed version of SQLModel rejects those. The agent raised inside its message handler, so the patch recommendation was silently lost.

**Fix.** `created_at` now uses the same UTC-aware default as `Incident`. The dashboard also reads stored timestamps as UTC, because SQLite drops the timezone and the browser would otherwise treat them as local time.

**Why it works.** A timezone-aware value passes SQLModel's check. Using one helper (`utc_now`) for both models removes the inconsistency.

**Before/after.** Before: the first recommendation of the first end-to-end run raised and was not stored. After: `workflow_trace.log` records **62** "stored recommendation for frontend" events across all our runs and 0 "not stored".

**Interview questions**
1. *What is a naive datetime and why is it risky?*
   It's a date and time with no timezone, so it means different moments depending on who reads it. Store UTC with an explicit offset, and convert to local time only for display.
2. *Why didn't anyone notice this?*
   The error happened in a background agent and was only logged. Nothing checked that a webhook eventually produced a recommendation. An end-to-end test that waits for the outcome, like our latency harness, catches it immediately.
3. *Why did it work before but not now?*
   The requirements file didn't pin versions, so a fresh install pulled a newer SQLModel with stricter checks. Pinning versions (or a lock file) makes installs reproducible.

---

## 7. The patch agent was looking at the wrong files

**Problem.** The investigation agent picked "files to inspect" by keyword, using rules written for one demo to-do app (`"todo" in text` → `backend/app/main.py`). For any other repo it guessed nothing, so the GitHub agent loaded only `README.md` and the patch LLM saw no code.

**Fix.** The in-app stack-trace files go first, then the keyword guesses.

**Why it works.** The stack trace names the exact file and line that failed, which is the best possible starting point.

**Before/after** (case E01, null cart in checkout). Before: `requested_files=none`, `loaded_files=README.md`. After: `app/checkout.py` and `README.md`, visible in the dashboard screenshot's workflow notes. This is a single-case observation; we didn't measure patch quality.

**Interview questions**
1. *What's the problem with heuristics tuned to one demo?*
   They pass the demo and fail everywhere else. Our keyword rules referenced "todo" and "create_todo", so the agent was effectively hardcoded to one app.
2. *What's an "in-app" frame?*
   A stack frame from your own code rather than a library. Sentry marks them `in_app: true`. Library frames (Starlette, SQLAlchemy) are rarely where the fix goes.
3. *How would you evaluate patch quality?*
   Run the suggested patch against a test that reproduces the bug, and check that the test passes and nothing else breaks. That needs runnable fixtures with tests, which this eval doesn't have.

---

## 8. Dead code and a misleading `.env.example`

**Problem.** The repo had code that looked like features but didn't work:
- A Monitoring agent that nothing sent messages to.
- `/api/patch-agent`, which called an HTTP endpoint (`/patch-from-sentry`) that doesn't exist.
- A Redis/rq worker that only printed a line.
- Empty modules.
- Six unused dependencies (redis, rq, semgrep, python-jose, passlib, alembic), plus psycopg2 and structlog.

`.env.example` sat in the repo root, but the code reads `backend/.env`. It listed four keys nothing reads (`GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_PRIVATE_KEY_PATH`, `FETCH_AI_SEED`) and a Postgres URL that would crash the app, because `database.py` runs SQLite-only `PRAGMA` statements. It also missed the keys the code does read, including `DEFAULT_REPO_FULL_NAME`, which is required. Without `INVESTIGATION_AGENT_ADDRESS`, every webhook returned 500.

**Fix.** Deleted the dead code and dependencies. Moved `.env.example` to `backend/` and listed exactly the keys `config.py` reads, with comments. The investigation agent's address now defaults to the one derived from its seed.

**Before/after.** Required manual settings to process a webhook: 2 → 1 (`DEFAULT_REPO_FULL_NAME`, or a `repo_full_name` in the payload). Keys in `.env.example` that the code reads: 3 of 7 → all of them (14 keys, every one read by `config.py`).

**Interview questions**
1. *Why delete code that "might be useful later"?*
   It misleads readers and reviewers into thinking a feature exists, it has to be kept compiling, and git history keeps it anyway.
2. *Why does `.env.example` matter?*
   It's the first thing a new developer copies. If it's wrong, they hit confusing errors, or worse, run with unverified webhooks because a secret wasn't set.
3. *How would you prevent config drift?*
   Generate the example from the settings class, or add a test that every field in `Settings` appears in `.env.example` and vice versa.

---

## 9. Measuring latency without fooling ourselves

**Problem 1: every case took exactly 4.4 s.** The first plumbing run (rules assessor, no LLM) reported 4,406–4,424 ms for all 20 cases. The harness waited for the dashboard to clear the previous row before posting the next webhook, so every webhook arrived just *after* a poll and waited the full 4 s for the next one. That measures our harness, not the system.

**Fix 1.** Before each webhook, the harness waits a random 0–4 s (seeded, and recorded per case), so alerts land at random points in the poll cycle like real ones. Rerun with the rules assessor: p50 3.38 s, p95 3.92 s, with the server part about 33 ms. With rules, the remaining time is almost all polling delay.

**Problem 2: the wrong row matched.** SQLite reuses row IDs after a delete. The harness deleted incidents between cases, so case 2 got ID 1 again. The browser still showed case 1's row with ID 1, already assessed, and the test "passed" instantly. A late write from case 1's agents could also have landed on case 2's ID.

**Fix 2.** Before the next case, wait until the agents log that this incident's pipeline finished, and until the dashboard shows no rows.

**Result** (LLM + GitHub context, 20 cases)

| | p50 | p95 | max |
|---|---|---|---|
| Webhook POST → assessment visible in the browser | **3,903 ms** | **8,003 ms** | 19,208 ms |
| Server: incident saved → assessment saved | 1,571 ms | 3,985 ms | 16,644 ms |
| Gemini call inside the assessor | 1,265 ms | 1,547 ms | 1,708 ms |

Percentiles use the nearest-rank method; with 20 values, p95 is the 19th smallest.

**The 19 s outlier (E15).** The Gemini call took 1.3 s, and about 15 s more passed before the assessment, while repo context was loading. Our GitHub fetch timeout is 15 s, so a stalled request is the likely cause, but context loading isn't timed separately, so this is unconfirmed. The first case after startup (E01) also took 4.0 s server-side, against about 1.5 s for the rest.

**Interview questions**
1. *Why report p95 and not just the average?*
   Averages hide the slow cases users actually notice. One 19 s case barely moves a mean but is exactly what an on-call engineer would remember.
2. *What's "coordinated omission" or phase-locking in benchmarks?*
   It's when the load generator's timing lines up with the system's own cycle (here, the 4 s poll), so you only ever measure one point of that cycle. Randomizing arrival times breaks the alignment.
3. *How would you cut the dashboard latency?*
   Replace polling with Server-Sent Events, which removes the 0–4 s polling delay (about 2 s on average). Then set a short timeout and a cache on GitHub file fetches, and run the patch pipeline after the assessment instead of in the same path.

---

## 10. Run-to-run consistency

The 20 end-to-end cases also ran offline with identical inputs, at temperature 0 both times.

| | Same answer in both runs |
|---|---|
| Severity | 18/20 (90%) |
| Escalation | **20/20 (100%)** |

E14 (admin report timeout) and E16 (search fallback) went from medium to low; both are labeled medium. Accuracy on these 20 cases in the end-to-end run: severity 14/20, escalation 19/20.

**Interview questions**
1. *Why measure consistency separately from accuracy?*
   A system can be right on average but flip on the same input, which destroys trust. Engineers stop believing a pager that disagrees with itself.
2. *Why are the flips on medium/low and not high/low?*
   Those cases sit near a boundary the rubric itself finds fuzzy ("degraded with a working fallback" vs. "no user impact"). Small changes in the model's output tip them.
3. *How would you reduce flips?*
   Give clearer boundary definitions with examples in the prompt, ask for the evidence before the label, or run the model several times and take the majority.

---

## 11. What it still gets wrong, and why

- **Medium is over-called as high.** Of 16 medium cases, the LLM called 10 high without context and 8 with it. Examples: account deletion failing (E20), order history crashing for new users (E23), refunds failing (E24). The model treats anything touching accounts or payments as a "core flow". The rubric's "minority of users / non-core" boundary isn't sharp enough for it.
- **It trusts reassuring code comments** (E05, E11; section 4).
- **It missed the leaked secret** (E11) in both modes. A deterministic check (a regex for key patterns like `sk_live_`) should handle this, not the model.
- **It merges severity and urgency** (section 5).
- **Rules are still worse almost everywhere, but not everywhere.** They got E06 wrong (inventory oversold, logged at `error`, came out medium/no page) and E11 wrong (a 200 response hiding a leaked key). They got both fields right on three cases each LLM mode missed. Without context the LLM missed E15, E17 and E22, calling Redis down, email retry and shipping fallback high/page. With context it missed E05, E15 and E22, calling the last two low. The rules landed on "medium" there because those events are logged at `error` level, not because they understood the fallback.

---

## Reproduce every number

From the repo root, with Python 3.13:

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt pytest playwright && cd ..
backend/.venv/Scripts/python -m playwright install chromium
cd frontend && npm ci && cd ..

# Free
backend/.venv/Scripts/python -m pytest -q backend/tests
backend/.venv/Scripts/python eval/build_eval_errors.py          # regenerates eval_errors.json from the labeled cases
backend/.venv/Scripts/python eval/run_eval.py --mode rules      # rules baseline, 0 API calls
backend/.venv/Scripts/python eval/run_e2e.py --ref 43b0a2d776307775ed5dce20cbb410bb22b2c0b4 --assessor rules   # plumbing + polling-only latency
backend/.venv/Scripts/python eval/score.py                      # rebuilds eval/results/metrics.md from saved results

# PAID (Gemini; GEMINI_API_KEY must be set). Every attempt is logged to eval/results/gemini_calls.log
backend/.venv/Scripts/python eval/run_eval.py --mode llm                                                     # 48 calls
backend/.venv/Scripts/python eval/run_eval.py --mode llm_repo --ref 43b0a2d776307775ed5dce20cbb410bb22b2c0b4 # 48 calls
backend/.venv/Scripts/python eval/run_e2e.py --ref 43b0a2d776307775ed5dce20cbb410bb22b2c0b4                  # 20 calls + screenshot
```

Use `bin/python` instead of `Scripts/python` on macOS/Linux. To start over, delete `eval/results/gemini_calls.log`; while it exists, it caps total calls at 170 across runs.

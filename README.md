# FPL AI Manager

A small scheduled FPL co-manager configured for **team 6000549**, **maximum overall rank**, and a **balanced** risk profile.

It runs hourly in GitHub Actions but exits immediately unless a report is due:

- **23-25 hours before deadline** -> sends the 24h preview
- **2-3.5 hours before deadline** -> sends the normal final recommendation when that falls in waking hours
- If the normal final would land between **23:00 and 07:00 Beijing time**, it instead sends a **Sleep-safe final** at about **22:00 Beijing time on the preceding evening**, with a hard 23:00 cutoff.

The report includes transfers/roll decision, XI, bench, captain/VC, chip advice, reasoning, risks, and a balanced alternative. The final OpenAI call can use web search for fresh injury and press-conference news.


## OpenAI prompt audit attachment

Every email that actually calls OpenAI includes a text attachment named like `fpl-gw1-openai-prompt.txt`. It records the model name, enabled OpenAI tools, the exact `instructions` string, and the exact `input` string sent by this application. API keys, SMTP credentials, and HTTP authorization headers are never included. Safety-withheld emails do not have this attachment because no OpenAI request is made.

## Important FPL data limitation

The public FPL endpoints can expose the latest *public/locked* team, history, fixtures, prices and player data, but they may **not reveal private changes you make before the next deadline**. So if you make a transfer after a deadline, the automation may still see the previous public squad until the next lock.

For a completely hands-off setup, avoid making ad-hoc manual changes outside the recommendations. If you do make one, copy `config/manual_state.example.json` to `config/manual_state.json`, set `enabled` to `true`, and record the changed squad/bank/free-transfer state. Do not put FPL passwords or session cookies into this repo.

## 1. Create the repository

1. Create a **private** GitHub repository.
2. Upload/push all files from this project.
3. In GitHub, open **Settings -> Secrets and variables -> Actions**.

## 2. Add OpenAI secret

Add repository secret:

- `OPENAI_API_KEY`

Optionally add repository variable:

- `OPENAI_MODEL` (default in this repo: `gpt-5`)

The code uses the OpenAI Responses API and optionally attaches the built-in `web_search` tool for late team news.

## 3. Configure email

This repository uses standard SMTP, so it works with Gmail App Passwords, Amazon SES SMTP, Mailgun SMTP, SendGrid SMTP and many other providers.

Create these GitHub Actions secrets:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS` (`true` for typical port 587 setups)
- `EMAIL_FROM`
- `EMAIL_TO`

### Gmail example

Use `smtp.gmail.com`, port `587`, your Gmail address as username, and a **Google App Password** as the SMTP password. Do not use your normal Google password.

## 4. Test locally

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env
FORCE_REPORT=preview DRY_RUN=true python -m fpl_ai_manager.main
```

`DRY_RUN=true` prints the recommendation without sending email.

To inspect exactly what data is being sent to the model:

```bash
FORCE_REPORT=preview python -m fpl_ai_manager.main --print-snapshot
```

## 5. Test on GitHub

Open **Actions -> FPL AI Manager -> Run workflow** and choose `preview` or `final`. This bypasses the deadline guard for a test run.

## How it works

1. Fetch `bootstrap-static`, fixtures, entry history and the latest publicly available picks from FPL.
2. Read the next deadline directly from FPL.
3. Exit unless it is inside a configured recommendation window.
4. Assemble current player data plus the next 6 GWs of fixtures.
5. Call the OpenAI Responses API with your strategy and structured snapshot.
6. Allow web search for current injuries/team news.
7. Email the markdown recommendation.

## Configuration

Edit `config/manager.json` to change:

- team ID
- objective
- risk profile
- timezone
- deadline windows
- `sleep_cutoff_hour` (default 23)
- `wake_hour` (default 7)
- `sleep_safe_send_hour` (default 22; intentionally one hour before the cutoff to allow for GitHub scheduler delay)
- fixture lookahead

## Cost/control

The workflow checks FPL hourly, but **does not call OpenAI outside the deadline windows**, so normally there are only two model calls per Gameweek. Manual forced test runs also call the API.

## Security

- Keep the GitHub repository private.
- Store API/SMTP credentials only in GitHub Secrets.
- Never commit `.env`.
- Never store your FPL password/session cookie here.
- Use a dedicated SMTP credential/App Password and revoke it if exposed.

## Reliability notes

FPL's public JSON endpoints are operationally useful but should be treated as unofficial/unsupported. The client is intentionally isolated in `src/fpl_ai_manager/fpl.py` so endpoint changes are easy to repair.

GitHub scheduled workflows can occasionally run late. The windows are intentionally broad enough to tolerate modest scheduler delay, and a GitHub Actions cache marker prevents duplicate scheduled emails for the same Gameweek/report type. Manual workflow-dispatch tests intentionally bypass this deduplication.

For sleep-safe finals, the configured hard cutoff is 23:00 Beijing time (`Asia/Shanghai`). The workflow targets about 22:00 rather than exactly 23:00 to leave scheduler-delay margin. A run that starts at or after 23:00 will not send a scheduled final. This design minimizes the risk of a late-night email, though GitHub Actions itself cannot provide a contractual exact-start-time guarantee.

## Squad-state verification and pre-GW1 drafts

The public FPL picks endpoint only exposes a team after a Gameweek deadline has locked. Before the first deadline of the season, your live draft cannot be read from the unauthenticated public API even when the entry ID is known.

The manager now adds a `state_check` to every AI snapshot and labels squad data as `verified`, `partial`, or `unavailable`, together with its source. After GW1 locks, the latest public 15 should normally be loaded automatically from `entry/<team_id>/event/<gw>/picks/`.

For GW1 or any private changes made after the latest deadline, copy:

```bash
cp config/manual_state.example.json config/manual_state.json
```

Then set `enabled` to `true` and list your 15 players under `squad_player_names`. Names may be FPL display names such as `Saka` or full names such as `Erling Haaland`. You can also provide `bank_tenths`, `free_transfers`, and `chips_available` when known.

Example:

```json
{
  "enabled": true,
  "bank_tenths": 5,
  "free_transfers": 1,
  "chips_available": ["wildcard", "freehit", "bboost", "3xc"],
  "squad_player_ids": null,
  "squad_player_names": [
    "Player One",
    "Player Two"
  ]
}
```

`bank_tenths` uses FPL's integer units: `5` means GBP0.5m. If a manual name is unknown or ambiguous, the report flags it rather than guessing.

## Safety-first operating mode

This repository is designed for a workflow where you wait for the automated recommendation before making FPL changes.

After GW1 locks, the latest public locked squad is the canonical squad source. `config/manual_state.json` is disabled by default and should normally remain disabled. The manual override is primarily for the pre-GW1 draft or exceptional recovery situations.

Before generating actionable transfer/lineup advice, the workflow verifies both:

- exactly 15 unique squad players; and
- a known bank balance.

If either check fails, the model is **not called for FPL advice**. Instead, the workflow emails an `ACTION WITHHELD` diagnostic notice. This prevents a plausible-looking generic recommendation from being mistaken for team-specific instructions.

Free-transfer and chip uncertainty is still surfaced explicitly and must not be guessed. Because public FPL state is locked at the previous deadline, this mode assumes you do not make private transfers before the recommendation you intend to follow.

## Automatic GW1 initial build

Before the first deadline, FPL does not expose a locked public 15-player squad. This repository therefore treats GW1 as a special initial-build mode when no manual squad is supplied.

In `gw1_initial_build` mode the AI is instructed to produce a complete legal opening squad from the live FPL player pool sent by the analyzer. The recommendation must contain exactly 2 goalkeepers, 5 defenders, 5 midfielders and 3 forwards, use no more than 3 players from one club, cost no more than £100.0m, and show the total cost and remaining bank. It also selects the GW1 starting XI, bench order, captain and vice-captain with a GW1-GW6 horizon.

You do not need `config/manual_state.json` for this workflow if you intend to build your GW1 team entirely from the emailed recommendation.

From GW2 onward, the behavior changes automatically to `managed_squad`: the latest locked public squad is the canonical current team. Actionable transfer/lineup advice is withheld if the 15-player squad or bank cannot be verified.

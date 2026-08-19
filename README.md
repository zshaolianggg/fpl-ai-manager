# FPL AI Manager

A small scheduled FPL co-manager configured for **team 6000549**, **maximum overall rank**, and a **balanced** risk profile.

It runs hourly in GitHub Actions but exits immediately unless the next official FPL deadline is either:

- **23-25 hours away** -> sends the 24h preview
- **2-3.5 hours away** -> sends the final recommendation

The report includes transfers/roll decision, XI, bench, captain/VC, chip advice, reasoning, risks, and a balanced alternative. The final OpenAI call can use web search for fresh injury and press-conference news.

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

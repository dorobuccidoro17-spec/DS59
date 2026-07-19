# DS59 Cloud Job — always-on email + daily phone update

This runs on **GitHub's servers every morning** (no desktop app needed). Each run it:

1. Fetches the top South Africa business, crypto, and AI headlines,
2. Fetches live BTC, ETH, and USD/ZAR for the watchlist,
3. **Emails** you the briefing (via your Gmail), and
4. **Republishes `brief.json`** into your DS59 repo — so your phone app updates itself daily.

It installs **into your existing `DS59` repo** (the same one that hosts the phone app).

## Files to add (into the DS59 repo, at the top level)
```
ds59_brief.py
requirements.txt
.github/workflows/ds59-daily-brief.yml
```

---

## Stage 1 — Add the three files

1. Open https://github.com/dorobuccidoro17-spec/DS59 → **Add file ▾ → Create new file**.
2. For each file, type the name (for the workflow, type the **full path** so GitHub makes the folders), paste the contents from the matching card, and **Commit**:
   - `ds59_brief.py`
   - `requirements.txt`
   - `.github/workflows/ds59-daily-brief.yml`

Your repo now has the app **and** the daily job side by side.

## Stage 2 — Get a Gmail App Password (the sender)

1. Turn on **2-Step Verification**: https://myaccount.google.com/security
2. Open **App passwords**: https://myaccount.google.com/apppasswords → create one named "DS59".
3. Copy the **16-character password** — that's your `SMTP_PASS` (not your normal Gmail password).

## Stage 3 — Add secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Secret name         | Value                                            |
|---------------------|--------------------------------------------------|
| `SMTP_HOST`         | `smtp.gmail.com`                                 |
| `SMTP_PORT`         | `465`                                            |
| `SMTP_USER`         | your sending Gmail address                       |
| `SMTP_PASS`         | the 16-character App Password                    |
| `MAIL_FROM`         | your sending Gmail address                       |
| `MAIL_TO`           | `tdshai91@gmail.com`                             |
| `ANTHROPIC_API_KEY` | *(optional)* to polish summaries in DS59's voice |

## Stage 4 — Allow the job to update the app

Repo → **Settings → Actions → General** → scroll to **Workflow permissions** → select
**Read and write permissions** → **Save**. (This lets the job publish the daily `brief.json`.)

## Stage 5 — Test it now

1. **Actions** tab → enable workflows if prompted → select **DS59 Daily Briefing** →
   **Run workflow** → **Run workflow**.
2. Wait ~1 minute. You should get an email at `tdshai91@gmail.com` (check Spam the first time),
   and a new commit updating `brief.json`.
3. Open the phone app — it now shows today's briefing.

Done. It runs automatically at **07:00 SAST** every day, independent of any app.

---

## Notes
- **Change the time:** edit the `cron` in the workflow (UTC; 07:00 SAST = `0 5 * * *`).
- **No email yet, phone only?** Skip the SMTP secrets — the job still updates `brief.json`
  so your phone refreshes; it just won't email until you add them.
- GitHub may start a scheduled run a few minutes late, and pauses schedules after 60 days
  of no repo activity (any commit or manual run re-arms it).
- Once this is live, we turn **off** the in-app email so you don't get duplicates.

*DS59 — at your service, sir.*

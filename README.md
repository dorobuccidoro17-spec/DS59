# DS59 — Mobile App (installable on your phone)

This is DS59 as an **installable web app**. You host these files once, open the link on
your phone, tap **Add to Home Screen**, and DS59 gets its own icon and opens full-screen
like a native app — with the dark HUD, watchlist, briefing, and a **Brief me** button that
reads it aloud. No Play Store, no APK, works on Android and iPhone.

## Files
```
index.html            the app
manifest.webmanifest  makes it installable (name, icon)
sw.js                 service worker (offline + fresh data)
brief.json            the briefing data (this is what refreshes daily)
icons/                app icons (192, 512, maskable)
```

## Step 1 — Put it online (free, ~5 min)

It must be served over **HTTPS** (required for install + voice). Easiest option:

**GitHub Pages**
1. Create a repo (e.g. `ds59-app`) at https://github.com/new — Public.
2. Upload **all** these files, keeping the `icons/` folder.
3. Repo **Settings → Pages** → Source: **Deploy from a branch** → branch **main**, folder **/(root)** → Save.
4. After a minute your app is live at `https://<your-username>.github.io/ds59-app/`.

*(Prefer drag-and-drop? https://app.netlify.com/drop — drop the `ds59-pwa` folder and it gives you an HTTPS link instantly.)*

## Step 2 — Install it on your phone

Open that link on your phone, then:
- **Android (Chrome):** tap the **⋮** menu → **Install app** (or **Add to Home Screen**).
- **iPhone (Safari):** tap **Share** → **Add to Home Screen**.

DS59 now sits on your home screen with its own icon.

## Step 3 — Keeping it fresh (optional but recommended)

The app shows the briefing in `brief.json`. To make your phone update **automatically each
morning**, have the always-on cloud job (the `ds59-cloud` package) also write a new
`brief.json` into this hosted folder. Then the phone shows the latest brief every time you
open it — no re-installing. I can wire that up for you on request.

Until then, the app shows the built-in briefing and still reads it aloud.

## Voice notes
- **Speaking (Brief me):** works on Android and iPhone.
- **Listening (🎙):** works well on Android Chrome; on iPhone it's limited — just use
  **Brief me** there. The first time, allow microphone access.

## Good to know
- It works offline after the first open (cached), showing the last briefing it saw.
- This app is a *viewer + voice* for your briefing. Full two-way chat, code, and live
  connectors belong to the standalone-app plan (see `DS59-Standalone-App-Plan.md`).

*DS59 — at your service, sir.*

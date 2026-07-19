#!/usr/bin/env python3
"""
DS59 Daily Briefing — always-on cloud edition (email + phone update).

Runs on a schedule via GitHub Actions, independent of any desktop app. It:
  1. Fetches the top South Africa business, crypto, and AI headlines (public RSS).
  2. Fetches live BTC, ETH, and USD/ZAR for the watchlist.
  3. Writes brief.json (the file the phone app reads) — always.
  4. Emails the briefing via SMTP (if SMTP_* secrets are set).

Environment variables (GitHub Actions secrets):
  MAIL_TO            recipient (default: tdshai91@gmail.com)
  MAIL_FROM          from address (default: SMTP_USER)
  SMTP_HOST/PORT/USER/PASS   your mail sender (e.g. Gmail App Password)
  ANTHROPIC_API_KEY  (optional) polish summaries in DS59's voice
  DS59_MODEL         (optional) Claude model, default claude-sonnet-5

Local test (no send): python ds59_brief.py --dry-run
"""

import os, re, ssl, sys, json, html, smtplib, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import requests

# --------------------------------------------------------------------------- #
MAIL_TO   = os.environ.get("MAIL_TO", "tdshai91@gmail.com")
SMTP_USER = os.environ.get("SMTP_USER", "")
MAIL_FROM = os.environ.get("MAIL_FROM", SMTP_USER)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("DS59_MODEL", "claude-sonnet-5")
DRY_RUN = "--dry-run" in sys.argv

# section -> phone tag, phone accent colour, email colours, RSS feeds
SECTIONS = [
    {"tag": "South Africa · Business", "pc": "#34d399",
     "bg": "#eafaf3", "bd": "#c3ecd8", "c": "#059669",
     "feeds": ["https://businesstech.co.za/news/feed/",
               "https://www.moneyweb.co.za/feed/",
               "https://mg.co.za/section/business/feed/"]},
    {"tag": "Crypto · Trading & Developments", "pc": "#fb923c",
     "bg": "#fdefe7", "bd": "#f5d3bf", "c": "#c2410c",
     "feeds": ["https://www.coindesk.com/arc/outboundfeeds/rss/",
               "https://cointelegraph.com/rss",
               "https://decrypt.co/feed"]},
    {"tag": "AI Pulse", "pc": "#818cf8",
     "bg": "#eeecfb", "bd": "#d3cef4", "c": "#4338ca",
     "feeds": ["https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
               "https://venturebeat.com/category/ai/feed/",
               "https://techcrunch.com/category/artificial-intelligence/feed/"]},
]

QUOTES = [
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("The best way to predict the future is to create it.", "Peter Drucker"),
    ("Discipline is the bridge between goals and accomplishment.", "Jim Rohn"),
    ("Success is not final, failure is not fatal: it is the courage to continue that counts.", "Winston Churchill"),
    ("Whatever you are, be a good one.", "Abraham Lincoln"),
    ("Opportunities don't happen. You create them.", "Chris Grosser"),
    ("Everything you've ever wanted is on the other side of fear.", "George Addair"),
]
JOKES = [
    "Why don't scientists trust atoms? Because they make up everything.",
    "I told my computer I needed a break, and now it won't stop sending me KitKat ads.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Parallel lines have so much in common. It's a shame they'll never meet.",
]
EDGES = [
    "Start with the problem, not the technology. The initiatives that pay off begin with one specific, costly business problem and a metric to move — not 'let's use AI.'",
    "Pilot small before you scale. Prove value on one workflow with a clear baseline before rolling anything out widely.",
    "Fix data quality first. A modest model on clean, well-governed data beats a frontier model on a mess.",
    "Upskill the team, don't just buy tools. Adoption, not licences, is where the return lives.",
    "Assign clear AI ownership. Someone accountable for governance and outcomes prevents 'shadow AI' sprawl.",
    "Keep a human in the loop for high-stakes calls. Let AI draft and triage; let people decide.",
    "Measure ROI against a baseline. If you can't state the before-and-after number, you can't defend the spend.",
]
CONCEPTS = [
    ("Large Language Models (LLMs)",
     "An LLM is trained on vast text to predict the next word, which is what lets it draft, summarise, and reason over language. It generates plausible text rather than looking up facts — hence its fluency and its habit of confident mistakes ('hallucinations').",
     "Lean on LLMs for drafting and synthesis, and keep a human check on high-stakes outputs."),
    ("Retrieval-Augmented Generation (RAG)",
     "RAG feeds a model your own documents at question time so answers are grounded in your data instead of the model's memory. It's how you get an assistant that 'knows' your business without retraining it.",
     "RAG is usually the cheapest route to a trustworthy internal assistant — start here before fine-tuning."),
    ("AI Agents",
     "An agent is a model given tools and a goal, allowed to take multiple steps on its own — searching, calling systems, and acting. Power rises, but so does the need for guardrails and oversight.",
     "Deploy agents on bounded, reversible tasks first; require approval before anything costly or irreversible."),
    ("Fine-tuning vs Prompting",
     "Prompting steers a general model with instructions; fine-tuning retrains it on your examples. Prompting is faster and cheaper; fine-tuning suits narrow, repeated jobs.",
     "Exhaust prompting and RAG before paying for fine-tuning — most needs never require it."),
    ("Hallucinations & Reliability",
     "Models can state false things with total confidence because they optimise for plausible text, not truth. Reliability comes from grounding, verification steps, and human review.",
     "For anything customer- or board-facing, design a checking step; never ship raw model output unverified."),
    ("Tokens & Context Windows",
     "Models read and bill in 'tokens' (word fragments), and a 'context window' caps how much they consider at once. Bigger context lets you feed more, but cost and latency rise with it.",
     "Watch cost-per-task, not just cost-per-token — verbose prompts add up fast."),
    ("AI Governance & the EU AI Act",
     "Regulators increasingly require transparency, documentation, and risk classification for AI systems. Compliance is shifting from a legal afterthought to part of how you design and deploy.",
     "Name an owner, document your models and data, and monitor use before you scale."),
]


def strip_html(t):
    t = re.sub(r"<[^>]+>", "", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def two_sentences(text, limit=320):
    text = strip_html(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:2]).strip()
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + "…"
    return out or text[:limit]


def fetch_top(feeds):
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                continue
            src = ((feed.feed.get("title") if getattr(feed, "feed", None) else "")
                   or "").split("-")[0].split("|")[0].strip() or "Source"
            for e in feed.entries[:3]:
                title, link = strip_html(e.get("title", "")), e.get("link", "")
                if not title or not link:
                    continue
                date = ""
                if e.get("published_parsed"):
                    date = datetime.datetime(*e.published_parsed[:6]).strftime("%d %b %Y")
                return {"title": title, "link": link, "source": src, "date": date,
                        "summary": two_sentences(e.get("summary", "") or e.get("description", ""))}
        except Exception as exc:  # noqa: BLE001
            print(f"  ! feed error {url}: {exc}", file=sys.stderr)
    return None


def fetch_watchlist():
    tiles = []
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": "bitcoin,ethereum", "vs_currencies": "usd",
                                 "include_24hr_change": "true"}, timeout=20)
        r.raise_for_status()
        d = r.json()
        for cid, name, colour in [("bitcoin", "Bitcoin", "#fb923c"),
                                  ("ethereum", "Ethereum", "#818cf8")]:
            if cid in d:
                px = d[cid]["usd"]
                chg = d[cid].get("usd_24h_change", 0.0) or 0.0
                up = chg >= 0
                tiles.append({"k": name, "v": "$" + format(int(round(px)), ","),
                              "chg": ("▲" if up else "▼") + " " + ("%.1f" % abs(chg)) + "%",
                              "dir": "up" if up else "down", "c": colour})
    except Exception as exc:  # noqa: BLE001
        print(f"  ! crypto price skipped: {exc}", file=sys.stderr)
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=20)
        r.raise_for_status()
        zar = r.json().get("rates", {}).get("ZAR")
        if zar:
            tiles.append({"k": "USD / ZAR", "v": "R%.2f" % zar,
                          "chg": "spot", "dir": "up", "c": "#34d399"})
    except Exception as exc:  # noqa: BLE001
        print(f"  ! fx rate skipped: {exc}", file=sys.stderr)
    return tiles


def ds59_polish(items):
    if not ANTHROPIC_API_KEY:
        return
    payload = [{"title": it["title"], "summary": it["summary"]} for it in items]
    prompt = ("You are DS59. Rewrite each item's summary as a neutral, factual 2-3 sentence "
              "summary (no hype). Return ONLY JSON {\"items\":[{\"summary\":\"...\"}]} in order.\n\n"
              + json.dumps(payload, ensure_ascii=False))
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": ANTHROPIC_API_KEY,
                                   "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 900,
                                "messages": [{"role": "user", "content": prompt}]}, timeout=45)
        r.raise_for_status()
        txt = r.json()["content"][0]["text"]
        txt = txt[txt.find("{"): txt.rfind("}") + 1]
        for it, p in zip(items, json.loads(txt)["items"]):
            if p.get("summary"):
                it["summary"] = p["summary"].strip()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Claude polish skipped: {exc}", file=sys.stderr)


def build_brief_json(date_str, quote, joke, edge, concept, items, watchlist):
    return {
        "date": date_str,
        "watchlist": watchlist,
        "quote": {"text": quote[0], "by": quote[1]},
        "joke": joke,
        "edge": edge,
        "headlines": [{"tag": sec["tag"], "c": sec["pc"], "date": it["date"],
                       "title": it["title"], "source": it["source"],
                       "summary": it["summary"], "link": it["link"]}
                      for sec, it in items],
        "concept": {"title": concept[0], "body": concept[1], "takeaway": concept[2]},
    }


def card_html(sec, it):
    return f"""
  <div style="background:{sec['bg']};border:1px solid {sec['bd']};border-left:5px solid {sec['c']};border-radius:12px;padding:14px 16px;margin-bottom:14px;">
    <span style="display:inline-block;background:{sec['c']};color:#fff;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;padding:4px 11px;border-radius:99px;">{sec['tag']}</span>
    <span style="color:#6b7280;font-size:11px;font-weight:700;">&nbsp;&nbsp;{it['date']}</span>
    <div style="font-size:16px;font-weight:700;margin:9px 0 3px;">{html.escape(it['title'])}</div>
    <div style="font-size:12px;color:#8790a0;font-weight:700;margin-bottom:7px;">{html.escape(it['source'])}</div>
    <div style="font-size:14px;color:#3a4150;">{html.escape(it['summary'])}</div>
    <a href="{html.escape(it['link'])}" style="display:inline-block;margin-top:10px;font-size:13px;font-weight:800;color:{sec['c']};text-decoration:none;">Read full article &rarr;</a>
  </div>"""


def render_email(date_str, quote, joke, edge, concept, items, watchlist):
    wl = " &nbsp;·&nbsp; ".join(f"{t['k']} {t['v']} ({t['chg']})" for t in watchlist) or "—"
    cards = "".join(card_html(sec, it) for sec, it in items)
    html_body = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;color:#161a22;line-height:1.55;padding:4px;">
  <div style="display:inline-block;font-weight:800;font-size:13px;letter-spacing:.04em;color:#fff;background:#5b3fd6;padding:6px 11px;border-radius:9px;">DS59</div>
  <h1 style="font-size:23px;margin:14px 0 4px;font-weight:800;">Good morning, Mr Shai.</h1>
  <div style="color:#6b7280;font-size:13px;font-weight:600;">Your briefing for {date_str}</div>
  <div style="margin:12px 0 6px;font-size:12.5px;color:#3a4150;font-weight:700;background:#f3f4f8;border-radius:10px;padding:9px 12px;">{wl}</div>
  <div style="background:#f3f0ff;border:1px solid #e4ddfb;border-radius:14px;padding:16px 18px;margin:12px 0 14px;">
    <div style="font-family:Georgia,serif;font-style:italic;font-size:17px;color:#2b2350;">&ldquo;{html.escape(quote[0])}&rdquo;</div>
    <div style="margin-top:8px;font-weight:800;font-size:13px;color:#7c3aed;">&mdash; {html.escape(quote[1])}</div>
  </div>
  <div style="background:#ecfbfd;border:1px solid #bfeef4;border-left:5px solid #0891b2;border-radius:12px;padding:12px 15px;margin-bottom:14px;">
    <span style="display:inline-block;background:#0891b2;color:#fff;font-size:11px;font-weight:800;text-transform:uppercase;padding:4px 11px;border-radius:99px;">Joke of the Day</span>
    <div style="margin-top:8px;font-size:14px;color:#3a4150;">{html.escape(joke)}</div>
  </div>
  <div style="background:#fdf4e7;border:1px solid #f3ddba;border-left:5px solid #b45309;border-radius:12px;padding:12px 15px;margin-bottom:14px;">
    <span style="display:inline-block;background:#b45309;color:#fff;font-size:11px;font-weight:800;text-transform:uppercase;padding:4px 11px;border-radius:99px;">Executive Edge</span>
    <div style="font-size:14px;color:#3a4150;margin-top:8px;">{html.escape(edge)}</div>
  </div>
  <div style="font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#fff;background:#6b7280;display:inline-block;padding:4px 12px;border-radius:99px;margin:6px 0 12px;">Today's Headlines</div>
{cards}
  <div style="background:#e9f6f3;border:1px solid #c3e6de;border-left:5px solid #0f766e;border-radius:12px;padding:14px 16px;margin:14px 0;">
    <span style="display:inline-block;background:#0f766e;color:#fff;font-size:11px;font-weight:800;text-transform:uppercase;padding:4px 11px;border-radius:99px;">AI Concept of the Day</span>
    <div style="font-size:16px;font-weight:700;margin:9px 0 5px;">{html.escape(concept[0])}</div>
    <div style="font-size:14px;color:#3a4150;">{html.escape(concept[1])}</div>
    <div style="margin-top:11px;padding:10px 13px;border-radius:10px;background:#d9efe9;border:1px solid #b6ddd3;font-size:13.5px;color:#155e52;"><strong style="color:#0f766e;">Executive takeaway:</strong> {html.escape(concept[2])}</div>
  </div>
  <div style="margin-top:16px;padding-top:12px;border-top:1px solid #e9ebf0;text-align:center;color:#8790a0;font-size:12.5px;">
    Auto-sent daily &middot; <strong style="color:#5b3fd6;">DS59</strong> &middot; at your service, sir
  </div>
</div>"""
    lines = [f"GOOD MORNING, MR SHAI. Your briefing for {date_str}", "", "WATCHLIST: " + wl.replace("&nbsp;·&nbsp;", " | "),
             "", f'"{quote[0]}" - {quote[1]}', "", f"JOKE: {joke}", "", f"EXECUTIVE EDGE: {edge}", "", "HEADLINES:"]
    for sec, it in items:
        lines += ["", f"{sec['tag']} ({it['source']} - {it['date']})", it["title"], it["summary"], it["link"]]
    lines += ["", f"AI CONCEPT — {concept[0]}", concept[1], f"Executive takeaway: {concept[2]}",
              "", "-- DS59, at your service, sir"]
    return html_body, "\n".join(lines)


def main():
    today = datetime.date.today()
    date_str = today.strftime("%A, %d %B %Y")
    doy = today.timetuple().tm_yday
    quote, joke = QUOTES[doy % len(QUOTES)], JOKES[doy % len(JOKES)]
    edge, concept = EDGES[doy % len(EDGES)], CONCEPTS[doy % len(CONCEPTS)]

    print(f"DS59 briefing for {date_str}")
    items = []
    for sec in SECTIONS:
        top = fetch_top(sec["feeds"])
        if top:
            items.append((sec, top))
            print(f"  ✓ {sec['tag']}: {top['title'][:64]}")
        else:
            print(f"  ! no item for {sec['tag']}", file=sys.stderr)
    if not items:
        print("No headlines fetched; aborting.", file=sys.stderr)
        sys.exit(1)

    ds59_polish([it for _, it in items])
    watchlist = fetch_watchlist()
    print(f"  watchlist tiles: {len(watchlist)}")

    # 1) Always write brief.json (this is what the phone app reads).
    brief = build_brief_json(date_str, quote, joke, edge, concept, items, watchlist)
    with open("brief.json", "w", encoding="utf-8") as fh:
        json.dump(brief, fh, ensure_ascii=False, indent=2)
    print("  ✓ wrote brief.json")

    # 2) Email (only if SMTP secrets are configured).
    html_body, text_body = render_email(date_str, quote, joke, edge, concept, items, watchlist)
    subject = f"DS59 Daily Briefing — {today.strftime('%a, %d %b %Y')}"

    if DRY_RUN or not (SMTP_USER and SMTP_PASS):
        with open("preview.html", "w", encoding="utf-8") as fh:
            fh.write(html_body)
        print("  [no email] SMTP not configured — wrote preview.html. brief.json still updated.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, (MAIL_FROM or SMTP_USER), MAIL_TO
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        ctx = ssl.create_default_context()
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(msg["From"], [MAIL_TO], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls(context=ctx)
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(msg["From"], [MAIL_TO], msg.as_string())
        print(f"  ✓ emailed briefing to {MAIL_TO}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! email failed (brief.json still updated): {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

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
try:
    SMTP_PORT = int(str(os.environ.get("SMTP_PORT") or "465").strip())
except ValueError:
    SMTP_PORT = 465
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("DS59_MODEL", "claude-sonnet-5")
# Web Push (phone notification) — all optional
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT") or "mailto:dorobuccidoro17@gmail.com"
PUSH_SUBSCRIPTION = os.environ.get("PUSH_SUBSCRIPTION", "")
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
    ("A leader is one who knows the way, goes the way, and shows the way.", "John C. Maxwell"),
    ("If you want to go fast, go alone. If you want to go far, go together.", "African proverb"),
    ("Culture eats strategy for breakfast.", "Peter Drucker"),
    ("The greatest glory in living lies not in never falling, but in rising every time we fall.", "Nelson Mandela"),
    ("Do not wait for the perfect moment; take the moment and make it perfect.", "Zoey Sayward"),
    ("What gets measured gets managed.", "Peter Drucker"),
    ("The price of light is less than the cost of darkness.", "Arthur C. Nielsen"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
    ("Management is doing things right; leadership is doing the right things.", "Peter Drucker"),
    ("You miss 100% of the shots you don't take.", "Wayne Gretzky"),
    ("Vision without execution is hallucination.", "Thomas Edison"),
    ("Education is the most powerful weapon you can use to change the world.", "Nelson Mandela"),
    ("The way to get started is to quit talking and begin doing.", "Walt Disney"),
    ("Innovation distinguishes between a leader and a follower.", "Steve Jobs"),
    ("Courage is what it takes to stand up and speak; it is also what it takes to sit down and listen.", "Winston Churchill"),
    ("Quality is not an act, it is a habit.", "Aristotle"),
    ("It is not the strongest that survives, but the most adaptable to change.", "Leon Megginson"),
    ("Efficiency is doing things right; effectiveness is doing the right things.", "Peter Drucker"),
    ("A goal without a plan is just a wish.", "Antoine de Saint-Exupéry"),
    ("Simplicity is the ultimate sophistication.", "Leonardo da Vinci"),
    ("Hardships often prepare ordinary people for an extraordinary destiny.", "C.S. Lewis"),
    ("Well done is better than well said.", "Benjamin Franklin"),
    ("The obstacle is the way.", "Marcus Aurelius"),
    ("Great things in business are never done by one person.", "Steve Jobs"),
    ("Fall seven times, stand up eight.", "Japanese proverb"),
    ("If you don't drive your business, you will be driven out of business.", "B.C. Forbes"),
    ("Knowing is not enough; we must apply.", "Johann Wolfgang von Goethe"),
    ("Risk comes from not knowing what you're doing.", "Warren Buffett"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese proverb"),
    ("Leadership is not about being in charge. It's about taking care of those in your charge.", "Simon Sinek"),
    ("Perfection is not attainable, but if we chase perfection we can catch excellence.", "Vince Lombardi"),
    ("Action is the foundational key to all success.", "Pablo Picasso"),
    ("Ideas are easy. Implementation is hard.", "Guy Kawasaki"),
    ("Character cannot be developed in ease and quiet.", "Helen Keller"),
]
JOKES = [
    "Why don't scientists trust atoms? Because they make up everything.",
    "I told my computer I needed a break, and now it won't stop sending me KitKat ads.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Parallel lines have so much in common. It's a shame they'll never meet.",
    "My boss told me to have a good day, so I went home.",
    "I used to play piano by ear. Now I use my hands.",
    "The meeting could have been an email. The email could have been silence.",
    "Why did the spreadsheet go to therapy? Too many unresolved cells.",
    "I asked the librarian if the library had books on paranoia. She whispered, 'They're right behind you.'",
    "A budget is just a spreadsheet telling you what you can't afford, politely.",
    "Why don't skeletons fight each other? They don't have the guts.",
    "My password is the last eight digits of pi. Good luck.",
    "Two economists walk into a bar. They argue about whether it exists.",
    "Why did the coffee file a police report? It got mugged.",
    "I'd tell you a construction joke, but I'm still working on it.",
    "Autocorrect has become my worst enema.",
    "Why was the maths book sad? It had too many problems.",
    "I bought shoes from a drug dealer once. I don't know what he laced them with, but I was tripping all day.",
    "Deadlines are just dreams with anxiety attached.",
    "Why did the developer go broke? He used up all his cache.",
    "I have a joke about procrastination, but I'll tell you tomorrow.",
    "Never trust a stair. It's always up to something.",
    "The early bird gets the worm, but the second mouse gets the cheese.",
    "Why don't eggs tell jokes? They'd crack each other up.",
    "My email signature says 'sent from my phone' so people forgive the typos. I'm on a desktop.",
    "I told my wife she should embrace her mistakes. She gave me a hug.",
    "Statistics show that people who have more birthdays live longer.",
    "Why did the strategy deck cross the road? To get to the next quarter.",
    "A clean desk is a sign of a cluttered desk drawer.",
    "I'm on a seafood diet. I see food and I eat it.",
    "Time flies like an arrow. Fruit flies like a banana.",
    "Why did the robot go on holiday? It needed to recharge.",
    "I would exercise, but I'm allergic to sweat — it makes my eyes water.",
    "Some people graduate with honours. I'm just honoured to graduate.",
    "My plan for retirement is to keep making plans for retirement.",
    "Why do meetings about efficiency always run over?",
    "I named my Wi-Fi 'Hack me if you can'. It's been quiet since.",
]
EDGES = [
    "Start with the problem, not the technology. The initiatives that pay off begin with one specific, costly business problem and a metric to move — not 'let's use AI.'",
    "Pilot small before you scale. Prove value on one workflow with a clear baseline before rolling anything out widely.",
    "Fix data quality first. A modest model on clean, well-governed data beats a frontier model on a mess.",
    "Upskill the team, don't just buy tools. Adoption, not licences, is where the return lives.",
    "Assign clear AI ownership. Someone accountable for governance and outcomes prevents 'shadow AI' sprawl.",
    "Keep a human in the loop for high-stakes calls. Let AI draft and triage; let people decide.",
    "Measure ROI against a baseline. If you can't state the before-and-after number, you can't defend the spend.",
    "Avoid 'AI theatre'. An impressive demo that never reaches production is a cost, not a capability.",
    "Communicate the 'why' early. Unexplained automation breeds fear; explained automation breeds adoption.",
    "Prioritise use cases by value × feasibility. The best first project is valuable AND easy, not heroic.",
    "Verify vendor claims with your own pilot. Benchmarks are marketing until they run on your data.",
    "Budget for change management, not just licences. The software is the cheap part.",
    "Track leading indicators, not vanity metrics. Time saved per task beats 'number of users'.",
    "Document decisions for auditability. If a regulator asked why the model did that, could you answer?",
    "Revisit your AI strategy quarterly. The capability curve moves faster than annual planning cycles.",
    "Write the policy before the incident. Data-usage rules are cheap now and expensive later.",
    "Delegate outcomes, not keystrokes. Tell the team what success looks like; let them find the tooling.",
    "Beware the pilot that never ends. Set a decision date: scale it, fix it, or kill it.",
    "Insist on a fallback path. Every automated workflow needs an answer to 'what if it's wrong?'",
    "Buy commodity, build differentiator. Don't build what you can rent; don't rent what makes you distinct.",
    "Make one person accountable per initiative. Shared ownership is no ownership.",
    "Test with your sceptics, not your enthusiasts. They'll find the failure modes your fans won't.",
    "Protect focus. Three finished AI projects beat twelve started ones.",
    "Show the work. Adoption follows trust, and trust follows visible reasoning and sources.",
    "Cost-control from day one. Set spend alerts before usage scales, not after the invoice.",
    "Hire for judgement, not tool familiarity. Tools change every quarter; judgement compounds.",
    "Run a pre-mortem. Ask 'it's a year on and this failed — why?' before you commit budget.",
    "Beware automating a broken process. Fix the workflow first, or you'll just fail faster.",
    "Give the team time to learn. Capability built under deadline pressure rarely sticks.",
    "Close the loop with users. The people doing the work know where the minutes are actually lost.",
    "Decide what you will NOT do this quarter. Strategy is subtraction.",
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
    ("Training vs Inference",
     "Training is the expensive, one-off process of teaching a model from data; inference is the cheap, repeated act of using it to answer. Almost everything a business does day-to-day is inference.",
     "You rarely need to train anything — your costs and decisions live on the inference side."),
    ("Prompting Basics",
     "A prompt is the instruction you give a model, and its quality dominates the output. Clear role, context, examples, and desired format reliably outperform clever phrasing.",
     "Prompting is a teachable staff skill with immediate ROI — train the team before buying more tools."),
    ("Embeddings & Vector Search",
     "Embeddings turn text into numbers that capture meaning, so a system can find documents by concept rather than exact keywords. This is the engine behind modern search and RAG.",
     "It's why an AI can find the right policy document even when nobody used the right words."),
    ("Multimodal AI",
     "Multimodal models handle images, audio, and documents alongside text — reading a scanned invoice, describing a photo, or transcribing a meeting.",
     "Much of your untapped value sits in documents and recordings, not tidy databases."),
    ("Foundation Models",
     "A foundation model is a large, general model trained once at great expense, then adapted to countless tasks. It's why capable AI is now rentable rather than built.",
     "You're buying access to shared infrastructure — your edge comes from data and workflow, not the model."),
    ("Benchmarks & Evaluation",
     "Public benchmarks measure models on standard tests, but they rarely reflect your actual workload. A private evaluation set of your real tasks is far more informative.",
     "Build a small internal test set — it turns vendor selection from opinion into evidence."),
    ("Guardrails & Safety",
     "Guardrails are the constraints around a model — filters, allowed actions, approval steps — that keep it inside acceptable behaviour. The model itself is not a control.",
     "Design the guardrails before deployment; they're what makes AI safe to put in front of customers."),
    ("Data Privacy in AI",
     "What you send to a model may be processed, stored, or used for training depending on the contract and settings. Enterprise terms usually differ sharply from consumer ones.",
     "Read the data terms before staff paste anything sensitive — and give them a clear policy."),
    ("Compute & Inference Cost",
     "Every response consumes compute, billed by volume of text processed. Costs scale with usage, prompt length, and model size.",
     "Match the model to the task: small models for routine work, large ones only where they earn it."),
    ("Open vs Closed Models",
     "Closed models are accessed via a provider's API; open-weight models can be downloaded and self-hosted. Open offers control and data residency, closed offers convenience and frontier capability.",
     "Choose by constraint: regulation and sovereignty push open, speed and capability push closed."),
    ("Bias & Fairness",
     "Models learn patterns from historical data, including its inequities, which can surface in hiring, lending, or service decisions. Bias is a data and process problem, not merely a technical one.",
     "For any decision affecting people, test outcomes across groups — and keep a human accountable."),
    ("Human-in-the-Loop",
     "This is the deliberate design choice to keep a person at the decision point, with AI preparing and recommending rather than deciding.",
     "It's the single most effective control for high-stakes automation — and usually a regulatory expectation."),
    ("Measuring AI ROI",
     "Return shows up as time saved, error rates reduced, throughput gained, or revenue enabled — but only if you captured a baseline beforehand.",
     "Measure the 'before' in week one, or you'll never prove the 'after'."),
    ("Build vs Buy",
     "Buying gets capability fast at recurring cost; building offers control and differentiation at high effort and maintenance.",
     "Buy the commodity, build only what genuinely differentiates you."),
    ("Copilots vs Autonomous Agents",
     "A copilot assists a person in real time; an agent executes multi-step tasks independently. Copilots are lower risk and faster to adopt; agents offer bigger leverage with bigger failure modes.",
     "Start with copilots to build trust, then graduate specific workflows to agents."),
    ("RLHF (Learning from Human Feedback)",
     "After initial training, humans rate model outputs and the model is tuned toward preferred responses. It's why modern assistants feel helpful rather than merely predictive.",
     "Model behaviour is a design choice made by its makers — worth asking vendors about."),
    ("Prompt Injection & Security",
     "Malicious instructions hidden in a webpage, email, or document can hijack an AI that reads them — a genuinely new attack surface.",
     "Treat any content your AI ingests as untrusted input, and limit what it's permitted to act on."),
    ("MLOps / LLMOps",
     "The operational discipline of deploying, monitoring, versioning, and improving AI systems in production. Without it, pilots work and production quietly degrades.",
     "Budget for operations from the start — AI is a system to run, not a project to finish."),
    ("Change Management for AI",
     "Adoption fails on fear, unclear expectations, and workflow disruption far more often than on technology.",
     "Communicate intent, involve the people affected, and measure adoption as seriously as accuracy."),
    ("Context Engineering",
     "Beyond prompts, this is the practice of supplying a model the right documents, tools, and history at the right moment. Most 'the AI got it wrong' cases are missing-context problems.",
     "Better context beats a better model, and it's usually cheaper to fix."),
    ("Model Distillation",
     "A large model teaches a smaller one to imitate it, yielding cheaper, faster inference with much of the capability retained.",
     "It's how you scale a proven use case without scaling the bill."),
    ("Structured Outputs",
     "Models can be constrained to return strict formats like JSON, so their answers plug directly into systems instead of needing a human to retype them.",
     "This is what turns a chat demo into genuine automation."),
    ("Latency & User Experience",
     "Response speed shapes adoption as much as accuracy — a brilliant answer nobody waits for is unused.",
     "Optimise perceived speed (streaming, partial results); people forgive imperfection more readily than delay."),
    ("Synthetic Data",
     "Artificially generated data used to train or test when real data is scarce, sensitive, or imbalanced. Useful, but it can amplify the flaws of whatever produced it.",
     "Valuable for testing edge cases and protecting privacy — validate it against reality."),
    ("Total Cost of Ownership",
     "The real cost of an AI system includes integration, monitoring, evaluation, staff time, and ongoing maintenance — typically dwarfing the licence.",
     "When comparing options, insist on TCO over three years, not the sticker price."),
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


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def fetch_top(feeds):
    for url in feeds:
        try:
            content = None
            try:
                resp = requests.get(url, headers={"User-Agent": UA,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*"}, timeout=25)
                if resp.ok and resp.content:
                    content = resp.content
            except Exception as exc:  # noqa: BLE001
                print(f"  ! fetch {url}: {exc}", file=sys.stderr)
            feed = feedparser.parse(content if content is not None else url)
            if not feed.entries:
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


def send_push(items):
    """Optional phone notification via Web Push.

    Fully self-contained and non-fatal: if anything is missing or fails, the
    briefing still publishes. (Not used on iOS below 16.4, which lacks Web Push.)
    """
    if not (VAPID_PRIVATE_KEY.strip() and PUSH_SUBSCRIPTION.strip()):
        print("  [no push] not configured — skipping notification.")
        return
    try:
        from pywebpush import webpush  # optional dependency
    except Exception:  # noqa: BLE001
        print("  [no push] pywebpush not installed — skipping notification.")
        return
    try:
        sub = json.loads(PUSH_SUBSCRIPTION)
        headline = items[0][1]["title"] if items else "Your daily briefing is ready."
        webpush(subscription_info=sub,
                data=json.dumps({"title": "DS59 — today's briefing", "body": headline}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT})
        print("  ✓ push notification sent")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! push notification failed (ignored): {exc}", file=sys.stderr)


def main():
    today = datetime.date.today()
    date_str = today.strftime("%A, %d %B %Y")
    # Rotate on a continuous day count (not day-of-year) so it doesn't reset each
    # January, and offset each list so the four never repeat as a set.
    n = today.toordinal()
    quote = QUOTES[n % len(QUOTES)]
    joke = JOKES[(n + 11) % len(JOKES)]
    edge = EDGES[(n + 5) % len(EDGES)]
    concept = CONCEPTS[(n + 3) % len(CONCEPTS)]

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
        print("  ! No headlines fetched from any feed — publishing the brief without news today.",
              file=sys.stderr)

    ds59_polish([it for _, it in items])
    watchlist = fetch_watchlist()
    print(f"  watchlist tiles: {len(watchlist)}")

    # 1) Always write brief.json (this is what the phone app reads).
    brief = build_brief_json(date_str, quote, joke, edge, concept, items, watchlist)
    with open("brief.json", "w", encoding="utf-8") as fh:
        json.dump(brief, fh, ensure_ascii=False, indent=2)
    print("  ✓ wrote brief.json")

    # Notify the phone (optional Web Push).
    send_push(items)

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
    # Never fail the workflow: log the problem, exit 0, keep the schedule healthy.
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("  ! DS59 hit an unexpected problem — logged below, continuing.", file=sys.stderr)
        traceback.print_exc()
    sys.exit(0)

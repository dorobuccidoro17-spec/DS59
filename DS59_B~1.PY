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
    ("It is better to lead from behind and put others in front.", "Nelson Mandela"),
    ("The function of leadership is to produce more leaders, not more followers.", "Ralph Nader"),
    ("Not everything that is faced can be changed, but nothing can be changed until it is faced.", "James Baldwin"),
    ("A person who never made a mistake never tried anything new.", "Albert Einstein"),
    ("Learn the rules like a pro, so you can break them like an artist.", "Pablo Picasso"),
    ("Slow is smooth, and smooth is fast.", "Military maxim"),
    ("If everyone is moving forward together, then success takes care of itself.", "Henry Ford"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("What you do speaks so loudly that I cannot hear what you say.", "Ralph Waldo Emerson"),
    ("Amateurs talk strategy; professionals talk logistics.", "Omar Bradley"),
    ("However beautiful the strategy, you should occasionally look at the results.", "Winston Churchill"),
    ("There are decades where nothing happens, and weeks where decades happen.", "Vladimir Lenin"),
    ("Chance favours the prepared mind.", "Louis Pasteur"),
    ("The cost of being wrong is less than the cost of doing nothing.", "Seth Godin"),
    ("If you're not embarrassed by the first version, you launched too late.", "Reid Hoffman"),
    ("Plans are worthless, but planning is everything.", "Dwight D. Eisenhower"),
    ("You cannot swim for new horizons until you have courage to lose sight of the shore.", "William Faulkner"),
    ("Move fast, but don't rush.", "Adapted proverb"),
    ("The man who moves a mountain begins by carrying away small stones.", "Confucius"),
    ("Excellence is never an accident.", "Aristotle"),
    ("Change before you have to.", "Jack Welch"),
    ("A ship in harbour is safe, but that is not what ships are built for.", "John A. Shedd"),
    ("The quality of a leader is reflected in the standards they set for themselves.", "Ray Kroc"),
    ("If you think education is expensive, try ignorance.", "Derek Bok"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("It is not enough to be busy; the question is what are we busy about.", "Henry David Thoreau"),
    ("Facts do not cease to exist because they are ignored.", "Aldous Huxley"),
    ("The best investment you can make is in yourself.", "Warren Buffett"),
    ("Speed of execution is the ultimate competitive advantage.", "Business maxim"),
    ("Coming together is a beginning; keeping together is progress; working together is success.", "Henry Ford"),
    ("A smooth sea never made a skilled sailor.", "Franklin D. Roosevelt"),
    ("What is not started today is never finished tomorrow.", "Johann Wolfgang von Goethe"),
    ("Nothing will work unless you do.", "Maya Angelou"),
    ("An organisation's ability to learn is the ultimate competitive advantage.", "Jack Welch"),
    ("The wise man does at once what the fool does finally.", "Baltasar Gracián"),
    ("Do not go where the path may lead; go instead where there is no path.", "Ralph Waldo Emerson"),
    ("努力 — effort — compounds quietly before it shows loudly.", "Proverb"),
    ("You don't rise to the level of your goals; you fall to the level of your systems.", "James Clear"),
    ("Strategy is about making choices; it's about deliberately choosing to be different.", "Michael Porter"),
    ("The essence of strategy is choosing what not to do.", "Michael Porter"),
    ("Trust is built in drops and lost in buckets.", "Kevin Plank"),
    ("Leadership is the capacity to translate vision into reality.", "Warren Bennis"),
    ("If you can't describe what you are doing as a process, you don't know what you're doing.", "W. Edwards Deming"),
    ("In God we trust; all others must bring data.", "W. Edwards Deming"),
    ("It's not the load that breaks you down, it's the way you carry it.", "Lena Horne"),
    ("Ubuntu — I am because we are.", "Southern African philosophy"),
    ("Only a fool tests the depth of the water with both feet.", "African proverb"),
    ("When the music changes, so does the dance.", "African proverb"),
    ("Wisdom is like a baobab tree; no one individual can embrace it.", "African proverb"),
    ("However long the night, the dawn will break.", "African proverb"),
    ("A river that forgets its source will dry up.", "African proverb"),
    ("Smooth seas do not make skilful sailors.", "African proverb"),
    ("Knowledge is like a garden: if it is not cultivated, it cannot be harvested.", "African proverb"),
    ("He who learns, teaches.", "Ethiopian proverb"),
    ("Patience is the mother of a beautiful child.", "Bantu proverb"),
    ("It is the wise bird that builds its nest before the rains.", "African proverb"),
    ("Sharpening the axe is not a delay in cutting the tree.", "Proverb"),
    ("Success is walking from failure to failure with no loss of enthusiasm.", "Winston Churchill"),
    ("Compound interest is the eighth wonder of the world.", "Attributed to Albert Einstein"),
    ("Price is what you pay; value is what you get.", "Warren Buffett"),
    ("It takes 20 years to build a reputation and five minutes to ruin it.", "Warren Buffett"),
    ("Someone is sitting in the shade today because someone planted a tree long ago.", "Warren Buffett"),
    ("The most dangerous phrase in the language is 'we've always done it this way'.", "Grace Hopper"),
    ("A ship is always safe at shore, but that is not what it's built for.", "Albert Einstein"),
    ("If opportunity doesn't knock, build a door.", "Milton Berle"),
    ("Clarity is kindness.", "Brené Brown"),
    ("Done is better than perfect.", "Sheryl Sandberg"),
    ("Real knowledge is to know the extent of one's ignorance.", "Confucius"),
    ("Doubt kills more dreams than failure ever will.", "Suzy Kassem"),
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
    "My to-do list has a to-do list. They're not speaking.",
    "I tried to catch fog yesterday. Mist.",
    "The office printer and I have an understanding: it understands when I'm in a hurry.",
    "Why did the accountant break up with the calculator? Too many issues to work through.",
    "I put my phone on aeroplane mode, but it's still on my desk. Disappointing.",
    "A synonym is a word you use when you can't spell the first one.",
    "My calendar is fully booked, mostly with meetings about my calendar.",
    "Why don't ants get sick? They have little anty-bodies.",
    "I told my team to think outside the box. They're now outside, and I can't find the box.",
    "Sleep is a poor substitute for coffee, but it's what I could afford.",
    "Why did the PowerPoint go to the doctor? It had too many bullet points.",
    "The best thing about a Boolean is that even if you're wrong, you're only off by a bit.",
    "I have an inferiority complex, but it's not a very good one.",
    "Why did the CV go to therapy? Too many unresolved gaps.",
    "My cloud storage is full of things I'll never look at again. Like my gym membership.",
    "I don't trust stairs — but escalators have their ups and downs too.",
    "What do you call a fake noodle? An impasta.",
    "The company said dress for the job you want, so I came in a bathrobe.",
    "Why was the equal sign so humble? It knew it wasn't less than or greater than anyone.",
    "I've started telling everyone about the benefits of eating dried grapes. It's all about raisin awareness.",
    "My inbox has 4,000 unread emails. I call it 'archiving in advance'.",
    "A pessimist sees a dark tunnel. An optimist sees light. A realist sees a train. The driver sees three idiots on the track.",
    "Why don't they play poker in the jungle? Too many cheetahs.",
    "I'd agree with you, but then we'd both be wrong.",
    "My strategy is to have no strategy. So far, it's working exactly as expected.",
    "Why did the coffee break get promoted? It always delivered on time.",
    "I used to think I was indecisive. Now I'm not so sure.",
    "The road to success is always under construction.",
    "Never argue with a thermostat. It's always right about the room.",
    "Why did the data scientist get thrown out of the bar? He kept trying to normalise everything.",
    "I bought a book on procrastination. It arrived eventually.",
    "My phone battery lasts all day, provided the day is four hours long.",
    "Why did the manager sit on the fence? To get a better view of both deadlines.",
    "I'm not lazy — I'm on energy-saving mode.",
    "What's the best thing about Switzerland? I don't know, but the flag is a big plus.",
    "Meetings: the practical alternative to work.",
    "Why did the graph go to the party? It heard there'd be good trends.",
    "I finally organised my desk. Now I can't find anything with confidence.",
    "Change is inevitable — except from a vending machine.",
    "Why did the intern bring a ladder to the office? He heard about climbing the corporate ladder.",
    "My New Year's resolution was to read more, so I've turned on subtitles.",
    "Why do accountants make good detectives? They always follow the trail.",
    "I asked for a raise. They gave me a title. I can't spend a title.",
    "The trouble with quotes on the internet is you can't verify their authenticity. — Abraham Lincoln",
    "Why did the laptop go to the dentist? It had Bluetooth.",
    "A committee is a group that keeps minutes and loses hours.",
    "I told my dog to fetch my slippers. He brought my agenda. Now we're both confused.",
    "Why don't calendars ever get invited anywhere? Their days are always numbered.",
    "The early meeting gets the yawn.",
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
    "Put the sceptic on the steering committee. Opposition inside the tent improves the plan; outside it, it kills the plan.",
    "Separate the experiment budget from the operations budget. Mixing them means innovation always loses to firefighting.",
    "Ask 'what would have to be true?' before approving a business case. It exposes the assumptions doing the heavy lifting.",
    "Automate the boring before the glamorous. Invoice matching pays back faster than a chatbot.",
    "Give the pilot a real user, not a demo audience. Feedback from someone doing the job beats applause.",
    "Write down the decision and the reasoning. Six months on, you'll want to know why, not just what.",
    "Time-box the analysis. Perfect information arrives after the opportunity has left.",
    "If everyone agrees immediately, the idea is either obvious or unexamined.",
    "Make the default 'human reviews', and require a case to remove the human — not the other way round.",
    "Watch for the metric that improves while the business doesn't. That's usually gaming, not gains.",
    "Know your unit economics before you scale. 'Cheap per query' becomes expensive at a million queries.",
    "Rotate people through the AI initiative. Capability that lives in one person is a single point of failure.",
    "Explain what happens to the time you save. Unanswered, staff will assume the answer is redundancy.",
    "Reward the team that kills a bad project early. It's cheaper than the team that finishes one.",
    "Insist on seeing the failure cases in every vendor demo. What they hide is what you'll live with.",
    "Start the governance conversation before the first pilot, not after the first incident.",
    "Treat prompts and system instructions as versioned assets. Undocumented changes cause unexplained behaviour.",
    "Set a review date on every automation. Processes that run unwatched drift out of alignment with the business.",
    "Prefer reversible decisions. Where a mistake can be undone cheaply, move fast; where it can't, slow down.",
    "Quantify the cost of the status quo. 'Doing nothing' is a decision with a price tag people rarely calculate.",
    "Talk to the front line before the consultants. They already know where the waste is.",
    "Beware the pilot chosen because it's easy to demo rather than valuable to fix.",
    "Publish your AI usage policy internally. Ambiguity is what drives staff to unsanctioned tools.",
    "Pair every efficiency metric with a quality metric. Faster and worse is not progress.",
    "Ask who is accountable when the system is wrong. If no name emerges, don't deploy it.",
    "Invest in the boring layer — data, access, integration. It's what makes the exciting layer possible.",
    "Don't outsource understanding. You can outsource building, but you must understand what you've bought.",
    "Run the numbers on 'good enough'. The last 5% of accuracy often costs more than the first 80%.",
    "Celebrate adoption publicly, not just launches. What gets recognised gets repeated.",
    "Keep a written list of what you've decided *not* to automate, and why. It prevents relitigating every quarter.",
    "Check whether the bottleneck is really the task you're automating. Speeding up a non-bottleneck changes nothing.",
    "Look for work that is high-volume, low-judgement, and well-documented. That's the sweet spot for early wins.",
    "Assume any AI output that leaves the building will be scrutinised. Set your review standard accordingly.",
    "Give yourself a kill switch, and test it. An automation you cannot stop is a risk you cannot manage.",
    "Beware efficiency that shifts work rather than removing it. Ask where the effort actually went.",
    "Train managers before teams. A manager who doesn't understand the tool will quietly block its use.",
    "Prefer one integrated workflow to five impressive tools. Fragmentation is where productivity dies.",
    "Set expectations that the first version will disappoint. Managed expectations survive early imperfection.",
    "Ask vendors what their model does when it doesn't know. The answer reveals the engineering quality.",
    "Do a data inventory before an AI strategy. You cannot plan around assets you haven't catalogued.",
    "Make security review a gate, not a formality. Retrofitting security after adoption is far costlier.",
    "Treat AI spend like cloud spend: monitor it weekly at first, or it will surprise you monthly.",
    "Distinguish pilots that test feasibility from pilots that test value. They need different success criteria.",
    "Keep a decision log for the board. Governance is evidenced by records, not intentions.",
    "Where the stakes are high, require two independent checks — the model and a person, or two different methods.",
    "Ask what your competitors could do with the same tool. Advantage is relative, not absolute.",
    "Don't confuse a capability demonstration with a business case. Impressive is not the same as profitable.",
    "Plan for the model to improve. Design workflows that get better automatically when the underlying model does.",
    "Retire tools deliberately. Unused licences and abandoned pilots quietly accumulate real cost.",
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
    ("Machine Learning vs AI",
     "AI is the broad ambition of machines performing tasks that need intelligence; machine learning is the dominant method — systems that learn patterns from data rather than following written rules.",
     "When a vendor says 'AI', ask what it learns from; if there's no data story, it's usually just software."),
    ("Supervised vs Unsupervised Learning",
     "Supervised learning trains on labelled examples ('this invoice is fraudulent'); unsupervised finds structure in unlabelled data, like natural customer segments.",
     "Labelled data is the expensive part — check you have it before promising a prediction project."),
    ("Neural Networks",
     "Layers of simple mathematical units that adjust their connections until they map inputs to outputs well. Depth lets them capture very complex patterns.",
     "The architecture matters less to you than the data quality feeding it."),
    ("Overfitting",
     "A model that memorises its training data performs beautifully in testing and poorly in the real world — it learned the answers, not the lesson.",
     "Always ask how a model performed on data it had never seen; that's the only number worth trusting."),
    ("Model Drift",
     "Accuracy decays over time as the world changes — customer behaviour shifts, products change, language moves. The model is static; reality isn't.",
     "Schedule periodic re-evaluation; a model that isn't monitored is quietly degrading."),
    ("Explainability",
     "The ability to say why a system produced a given output. Some models explain readily; large ones are far harder to interrogate.",
     "In regulated decisions, explainability isn't optional — choose approaches you can defend."),
    ("Confidence & Calibration",
     "A well-calibrated system knows when it's unsure. Many models express high confidence regardless, which is dangerous when acted on automatically.",
     "Route low-confidence cases to a human — that single rule prevents most automation disasters."),
    ("Precision vs Recall",
     "Precision is how often flagged items are truly relevant; recall is how many of the real cases you caught. Improving one usually costs the other.",
     "Decide which error hurts more — a false alarm or a miss — and tune deliberately for it."),
    ("The Data Flywheel",
     "Usage generates data, which improves the product, which attracts more usage. It's the compounding advantage behind most durable AI businesses.",
     "Ask of any AI investment: does using it make it better? If not, it's a tool, not an asset."),
    ("Vendor Lock-in",
     "Deep integration with one provider's models, formats, and tooling makes switching costly later, weakening your negotiating position.",
     "Keep an abstraction layer between your systems and any single model provider."),
    ("Shadow AI",
     "Staff quietly using unapproved consumer AI tools for work — often with company data — because official options are slow or absent.",
     "The cure is provision, not prohibition: give people a sanctioned tool that's genuinely good."),
    ("AI Literacy Across the Organisation",
     "Broad, basic fluency — knowing what these systems can and cannot do — produces better decisions than a handful of specialists ever will.",
     "Invest in wide, shallow literacy before deep, narrow expertise."),
    ("The Last Mile Problem",
     "Most AI value is lost between a working model and a changed workflow. The technology succeeds; the adoption fails.",
     "Budget more attention for the last mile than for model selection."),
    ("Automation vs Augmentation",
     "Automation replaces a task; augmentation makes a person better at it. Augmentation is usually faster to adopt, less risky, and better received.",
     "Lead with augmentation — you'll meet far less resistance and learn where automation is genuinely safe."),
    ("Chain-of-Thought Reasoning",
     "Prompting a model to work through steps before answering markedly improves accuracy on complex problems — and shows its workings.",
     "For analytical tasks, ask for the reasoning, not just the conclusion."),
    ("Temperature & Determinism",
     "A setting controlling randomness: low values give consistent, predictable answers; high values give varied, creative ones.",
     "For anything auditable or repeatable, insist on low-variability settings."),
    ("System Prompts",
     "Standing instructions that define an assistant's role, tone, and limits for every conversation — where policy is encoded.",
     "Your system prompt is corporate policy in code; review it as carefully as a contract."),
    ("Function / Tool Calling",
     "Models can be given tools — a database query, a calculator, an email send — and decide when to invoke them, turning conversation into action.",
     "This is the bridge from chatbot to workflow; scope those tools tightly."),
    ("Knowledge Cut-off",
     "Models only know the world up to their training date, and will answer confidently about later events regardless.",
     "For anything current, ensure your system retrieves live data rather than relying on memory."),
    ("Grounding & Citations",
     "Requiring answers to cite retrieved sources makes them checkable, and dramatically reduces confident invention.",
     "Insist on citations for any AI output that informs a decision."),
    ("Small Language Models",
     "Compact models that run cheaply, quickly, and sometimes entirely on your own hardware, at surprisingly good quality for narrow tasks.",
     "Not every job needs the frontier — small models often win on cost, speed, and privacy."),
    ("On-Device AI",
     "Running models locally on phones or laptops, so data never leaves the device — attractive for privacy and offline use.",
     "Where confidentiality dominates, on-device may beat any cloud option."),
    ("Fine-tuning Costs & Risks",
     "Beyond the training bill, fine-tuning locks you to a version, needs curated data, and must be redone as base models improve.",
     "Treat fine-tuning as a maintenance commitment, not a one-off purchase."),
    ("Evaluation Harnesses",
     "An automated suite that scores your system against known-good examples every time you change something — regression testing for AI.",
     "Without one, every 'improvement' is a guess and every deploy is a risk."),
    ("Red-Teaming",
     "Deliberately attacking your own system — trying to make it leak, mislead, or misbehave — before someone else does.",
     "Red-team before launch, especially anything customer-facing."),
    ("Data Residency & Sovereignty",
     "Laws about where data may physically live and be processed, which vary by country and sector — a live concern under South African POPIA.",
     "Confirm processing locations before signing; it can quietly rule vendors out."),
    ("POPIA & Personal Information",
     "South Africa's data protection law governs processing of personal information, requiring lawful basis, purpose limitation, and safeguards.",
     "Any AI touching customer or employee data needs a POPIA view before deployment, not after."),
    ("Consent & Transparency",
     "People increasingly expect to be told when they're interacting with AI or when it shapes decisions about them.",
     "Disclose AI involvement proactively — discovered concealment costs far more than disclosure."),
    ("Intellectual Property in AI Output",
     "Ownership and copyright status of AI-generated material remains legally unsettled and varies by jurisdiction.",
     "For brand-critical or commercial assets, take legal advice before relying on generated content."),
    ("Model Versioning",
     "Providers update models continually, and behaviour can shift beneath you without warning if you haven't pinned a version.",
     "Pin versions in production and test upgrades deliberately, as you would any dependency."),
    ("Rate Limits & Availability",
     "APIs cap how much you can call and occasionally go down. A workflow with no fallback simply stops.",
     "Design degradation paths — what happens to the business when the model is unavailable?"),
    ("Batch Processing",
     "Submitting work in bulk for slower but substantially cheaper processing — ideal for anything not needed instantly.",
     "Ask which of your AI workloads genuinely need real-time; the rest can be batched at lower cost."),
    ("Caching",
     "Reusing results for repeated or similar requests, cutting both cost and latency significantly.",
     "In high-volume use, caching is often the single largest cost saving available."),
    ("Orchestration",
     "Coordinating multiple models, tools, and steps into a reliable pipeline — increasingly where the real engineering lives.",
     "Capability is commoditising; orchestration is where differentiation now sits."),
    ("Multi-Agent Systems",
     "Several specialised agents collaborating — one researches, one drafts, one reviews — which can outperform a single generalist.",
     "Powerful, but harder to debug; start simple and add agents only when justified."),
    ("Memory & Personalisation",
     "Systems that retain context across sessions to give continuity — remembering preferences, history, and prior decisions.",
     "Memory turns a tool into an assistant, but raises real privacy and retention questions."),
    ("Hallucination Mitigation",
     "Practical defences: retrieval grounding, requiring citations, self-checking steps, and constrained output formats.",
     "You cannot eliminate invention; you can make it detectable and rare."),
    ("Benchmarking Against Humans",
     "The useful comparison isn't perfection, but current human performance including its error rate and cost.",
     "Ask 'better than our current process?', not 'is it flawless?'"),
    ("Time-to-Value",
     "How long before an initiative produces measurable benefit. Long horizons erode sponsorship and momentum.",
     "Favour projects showing value within a quarter; use those wins to fund the ambitious ones."),
    ("Pilot Purgatory",
     "The common state of many promising pilots and no production systems — usually a governance and ownership failure, not a technical one.",
     "Set a scale-or-kill decision date at the pilot's start."),
    ("Workflow Mapping",
     "Documenting how work actually flows today, step by step, before automating any part of it.",
     "You cannot automate what you haven't mapped — and mapping alone often reveals the real fix."),
    ("Process Mining",
     "Using system logs to discover how processes genuinely run, as opposed to how the manual says they run.",
     "It reliably finds the expensive bottleneck that everyone had misidentified."),
    ("Knowledge Management",
     "Organising institutional knowledge so it's retrievable. AI amplifies good knowledge bases and exposes bad ones mercilessly.",
     "Fixing documentation is often the highest-return 'AI project' available to you."),
    ("Document Intelligence",
     "Extracting structure from contracts, invoices, and forms — frequently the fastest, clearest AI win in an established business.",
     "Look for high-volume, rules-based paperwork; that's where payback comes quickest."),
    ("Conversational Interfaces",
     "Letting users ask in plain language instead of navigating menus — powerful, but only when grounded in real data.",
     "A chat box over bad data creates a fast, confident source of wrong answers."),
    ("Sentiment & Text Analytics",
     "Systematically reading customer feedback, reviews, and tickets at scale to surface themes no one has time to read.",
     "You likely already own thousands of customer opinions you've never analysed."),
    ("Forecasting",
     "Using historical patterns to predict demand, cash flow, or churn — one of the oldest and most bankable applications.",
     "Forecasts inform decisions; always ask for the uncertainty range, not just the number."),
    ("Anomaly Detection",
     "Flagging what deviates from normal — fraud, faults, outliers — without needing every failure type pre-defined.",
     "Excellent where problems are rare, costly, and hard to specify in advance."),
    ("Recommendation Systems",
     "Suggesting the next product, article, or action based on behaviour patterns — a proven revenue lever.",
     "Small relevance gains compound significantly at scale."),
    ("Personalisation vs Privacy",
     "Better personalisation demands more data, tightening the tension with privacy expectation and law.",
     "Set the line deliberately as policy, before product teams set it by default."),
    ("Customer Service Automation",
     "Deflecting routine queries while escalating complex ones — high volume, measurable, and immediately felt.",
     "Measure resolution and satisfaction, not just deflection rate; a bad deflection costs a customer."),
    ("Sales Enablement",
     "AI drafting outreach, summarising accounts, and preparing reps — augmentation that sellers usually welcome.",
     "Adoption is high here because it removes admin, not judgement."),
    ("Meeting Intelligence",
     "Automatic transcription, summaries, and action items — a small change with outsized effect on follow-through.",
     "One of the easiest starting points for a sceptical team."),
    ("Coding Assistants",
     "AI helping engineers write, review, and explain code — now standard practice, with real productivity gains on routine work.",
     "Expect measurable gains on boilerplate, minimal gains on hard architectural thinking."),
    ("AI in Finance Functions",
     "Reconciliation, anomaly detection, and reporting narratives — strong candidates given structured data and repetitive review.",
     "Insist on auditability; finance automation without a trail is a liability."),
    ("AI in HR & Hiring",
     "Screening and scheduling can be accelerated, but hiring decisions carry heavy bias and legal exposure.",
     "Automate scheduling freely; automate judgement about people very cautiously, if at all."),
    ("Board-Level AI Reporting",
     "Boards increasingly expect a coherent account of AI adoption, risk exposure, and value delivered.",
     "Prepare a one-page view: where we use it, what it saved, what could go wrong, who owns it."),
    ("Building an AI Roadmap",
     "A sequenced plan tying use cases to business objectives, capability building, and governance milestones.",
     "Without a roadmap you'll accumulate disconnected pilots instead of compounding capability."),
    ("The Capability Gap",
     "The widening distance between what these systems can do and what organisations have actually adopted.",
     "Most competitive advantage now lies in adoption speed, not in access to technology."),
    ("Strategic Positioning with AI",
     "Deciding whether AI cuts your costs, differentiates your product, or creates new revenue — three quite different strategies.",
     "Pick one primary axis; pursuing all three at once usually achieves none."),
    ("Talent Strategy",
     "Deciding what to hire, train, or outsource as AI reshapes which skills matter.",
     "Judgement, domain knowledge, and clear communication are appreciating; routine execution is depreciating."),
    ("Ethical Frameworks",
     "Stated principles guiding acceptable use — fairness, transparency, accountability, human oversight.",
     "Principles are worthless unaccompanied by a decision process that can actually stop a project."),
    ("Environmental Cost",
     "Training and running large models consumes meaningful energy and water, drawing growing scrutiny.",
     "Expect this in ESG reporting; efficiency choices increasingly have a sustainability dimension."),
    ("Concentration Risk",
     "A handful of providers supply most frontier capability, creating dependency on very few suppliers.",
     "Treat model providers as critical suppliers, with the contingency planning that implies."),
    ("The Build Trap",
     "Building bespoke AI infrastructure that commoditises within months, consuming scarce engineering capacity.",
     "Build only what remains valuable after the next model release."),
    ("Reading AI Announcements Critically",
     "Vendor claims and benchmark scores are marketing artefacts; capability on your workload is the only measure that matters.",
     "Discount every announcement until you've run it against your own evaluation set."),
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
    # Stride through each list with a step coprime to its length: every entry is
    # still used exactly once per full cycle, but consecutive days jump around
    # so similar items (e.g. proverbs) never bunch together.
    quote = QUOTES[(n * 37) % len(QUOTES)]
    joke = JOKES[(n * 29 + 11) % len(JOKES)]
    edge = EDGES[(n * 31 + 5) % len(EDGES)]
    concept = CONCEPTS[(n * 31 + 3) % len(CONCEPTS)]

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

# 🇮🇳 Scheme Saathi — स्कीम साथी

> **AI agent that tells every citizen exactly which government schemes they deserve — and why.**
> Conversational profile intake → transparent rule engine → ranked eligibility report with **near-miss gap analysis**, in **English + हिंदी**.

![status](https://img.shields.io/badge/tests-70%20passed-brightgreen) ![schemes](https://img.shields.io/badge/schemes-25-orange) ![docs](https://img.shields.io/badge/documents-checklist-teal) ![stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20LangGraph%20%2B%20RAG%20%2B%20Gemini-blue)

---

## 😤 The Problem

India has **700+ government schemes**, but the people who need them most — a farmer in UP, a street vendor in Delhi, a student in a village — **don't know what they're eligible for**. Portals are scattered, criteria are buried in PDFs, and most beneficiaries find out *by accident*.

## 💡 The Solution

Scheme Saathi asks a few **adaptive** questions (a farmer gets land questions, a student gets education questions — never a 20-field form), then instantly checks **25 curated central schemes** with a **transparent rule engine** and produces:

- ✅ **Eligible schemes** — ranked by value & relevance, with the *exact criteria you satisfy* and **why**
- ⚠️ **Near-miss gap analysis** — *"Your income ₹3,75,000 vs limit ₹3,00,000 — ₹75,000 over. You may still qualify under LIG."* + actionable **tips to become eligible**
- 📋 **Consolidated documents checklist** *(Key Feature 7)* — every document across all your matched schemes, **deduplicated**, ranked by how many schemes need it, showing *which* schemes need each one — and for anything you're missing, **how to get it** (where to go, what to carry, what it costs)
- 🔗 Apply links + 🖨️ **printable PDF report** with tickable checkboxes (an NGO worker prints it and hands it over)
- 🌐 Full **Hindi + English** support with auto language detection
- 🎤 Voice input (Web Speech API)

### 💬 It actually converses — ask anything, at any point

The intake is 8–11 adaptive questions, but you are never *trapped* in them. Any turn can be a real question, and the flow resumes exactly where it left off:

| You type, mid-form | What happens |
|---|---|
| *"BPL kya hai?"* | Explains BPL (ration card, SECC list) → re-asks the same question |
| *"mere paas aadhaar card nahi hai"* | Full answer: where to enrol, what to carry, the EID slip, that it's free → resumes |
| *"MUDRA me kitna loan milta hai?"* | Answers from the scheme dataset — ₹50K/₹5L/₹10L tiers, where to apply → resumes |
| *"actually meri income 2 lakh hai"* | **Corrects the earlier answer**, confirms ₹2,00,000, carries on (post-report it *rebuilds* the report) |
| *"rehne do"* / *"skip"* | Skips that question gracefully, never asks it again, notes what it costs |
| *"shuru se karo"* | Clears the profile and restarts — language remembered |
| *"kisan"*, *"gaon"*, *"aurat"* | Romanized Hinglish free text is understood, not just chip taps |
| *"cricket score batao"* | Honestly says it doesn't know and points to myscheme.gov.in — **never invents a rule** |

**How it stays trustworthy:** every answer is retrieved from a curated corpus — `data/knowledge.json` (25 citizen-doubt articles, bilingual) plus the 25 scheme records — by a dependency-free lexical retriever. With a Gemini key the model rewrites those passages conversationally but is instructed that they are the **only** permitted source of facts; with no key the curated passage *is* the answer. **Same knowledge either way — the LLM changes the tone, never the facts.** The demo cannot be bricked by a dead Wi-Fi or an expired API key.

---

## 🏆 Why this wins — differentiators

| Feature | Typical team | Scheme Saathi |
|---|---|---|
| Profile intake | Static form | **Adaptive conversational flow** (LangGraph state machine) |
| Off-script user input | Parse error, or the bot breaks | **Every turn can be a question, a correction, a skip or chit-chat** — answered properly, then the flow resumes untouched |
| Confused users | "Sorry, I didn't understand" | **RAG-grounded answers** from 25 curated citizen-doubt articles + the scheme dataset — offline-safe |
| Wrong answer given | Restart the whole form | *"actually meri income 2 lakh hai"* → **corrected in place**, report rebuilt |
| Eligibility | Black-box if-else / LLM guessing | **Deterministic rule engine** — every verdict traceable to a rule, bilingual |
| Near-miss | Not implemented | **Precise gap math** (₹ amounts, years, hectares) + cross-scheme tips |
| Documents *(Key Feature 7)* | A list copy-pasted per scheme | **One consolidated checklist** — deduplicated across all matches, attributed to schemes, with **how to obtain each missing document** |
| Hallucination risk | LLM free-styles scheme rules | Facts come **only** from retrieved passages; unknown → honest "I don't know" + myscheme.gov.in |
| Language | English only | Hindi-first design, auto-detect, romanized Hinglish (*kisan*, *gaon*) understood |
| Demo flow | Nervous live typing | **Quick-reply buttons** drive a full persona in ~10 seconds of taps; sidebar shows the profile building live |
| LLM dependency | Demo dies without API | **Graceful degradation**: Gemini enhances the tone, curated corpus guarantees the content |

---

## 🧠 Architecture

```
┌──────────────────────── Frontend (vanilla JS, glass UI) ────────────────────────┐
│  WhatsApp-style chat · quick-replies · instant persona demos · report dashboard  │
└──────────────────────────────────┬──────────────────────────────────────────────┘
                                   │ REST (JSON)
┌──────────────────────────────────▼──────────────────────────────────────────────┐
│                              FastAPI  (app/api/routes.py)                        │
│  /api/session/new · /api/chat · /api/report/{id}(.html) · /api/schemes · /demo   │
└──────────────────────────────────┬──────────────────────────────────────────────┘
                                   │ per message
┌──────────────────────────────────▼──────────────────────────────────────────────┐
│                     LangGraph orchestration (app/graph/main_graph.py)            │
│                                                                                  │
│   START ──► intake ──┬─► (more questions) ───────────────► END                   │
│                      ├─► pipeline (match→rank→reason) ──► END                    │
│                      └─► followup (report Q&A) ─────────► END                    │
│        (sequential fallback if langgraph missing — identical behaviour)          │
└──────────┬───────────────────┬──────────────────┬───────────────────────────────┘
           ▼                   ▼                  ▼
┌───────────────────────┐ ┌──────────────────┐ ┌──────────────────────────────────┐
│ Adaptive intake agent │ │ Conversation     │ │ Eligibility engine (app/engine)  │
│ agents/intake.py      │ │ agents/          │ │ matcher.py  — ALL/ANY rule groups│
│ prompts.py (EN/HI)    │ │  conversation.py │ │ near_miss.py— precise gap + tips │
│ tolerant parsers      │ │  · classify turn │ │ ranker.py   — benefit/fit/pop.   │
│ (₹lakh, हाँ, kisan)   │ │  · skip/correct  │ │ documents.py— MASTER CHECKLIST ★ │
│ skip + correction     │ │  knowledge.py    │ │ reasoner.py — bilingual report   │
│ aware                 │ │  · RAG retrieval │ └──────────────┬───────────────────┘
└───────────────────────┘ └────────┬─────────┘                ▼
                                   ▼                ┌──────────────────────────────┐
                    ┌──────────────────────────┐    │ data/schemes.json            │
                    │ data/knowledge.json      │    │ 25 schemes · bilingual rules │
                    │ 25 citizen-doubt articles│    │ docs · benefits · links      │
                    │ BPL · Aadhaar · CSC ·    │    └──────────────┬───────────────┘
                    │ documents · DBT · loans  │                   │
                    └────────────┬─────────────┘                   │
                                 └──────────┬─────────────────────┘
                                            ▼
                                 ┌─────────────────────────┐
                                 │ Gemini (optional)       │
                                 │ rewrites retrieved text │
                                 │ conversationally —      │
                                 │ NEVER adds new facts    │
                                 └─────────────────────────┘
```

★ **Key Feature 7** — `engine/documents.py` merges the `documents_*` field of every
matched scheme into one deduplicated checklist (canonicalising *"Aadhaar Card"*,
*"Aadhaar card (mandatory)"* and *"आधार कार्ड"* into a single row), attributes each
document to the schemes that need it, and attaches how-to-obtain guidance. It is
rendered in the report UI, the printable PDF (with ☐ checkboxes), the chat
(*"documents"*), and `GET /api/report/{id}/documents`.

---

## 🚀 Quickstart

```bash
pip install -r requirements.txt

# optional — without a key, everything still works (offline mode)
cp .env.example .env        # add GEMINI_API_KEY (free: aistudio.google.com/apikey)

python run.py               # → http://localhost:8000
```

Run the verification suite (all 4 demo personas + engine + conversation + checklist):

```bash
pytest tests/ -v          # 70 tests, ~1 second, no network needed
```

Every test runs **without an API key** — that is deliberate: it proves the offline
path (curated corpus + rule engine) produces the full experience on its own.

---

## 🎬 For the demo (important!)

Drive the chat live — quick-reply buttons make each persona ~10–15 seconds of tapping. Keep these cheat-cards next to you:

| Persona | Profile (answers to give) | Headline result |
|---|---|---|
| 🌾 **Ramesh** (run fully in **Hindi**) | 45 · पुरुष · ग्रामीण UP · किसान · ₹1–2.5 लाख · एससी · BPL हाँ · 1–2 हे. · पक्का नहीं · बैंक हाँ | PM-KISAN, Fasal Bima, KUSUM, PMAY-G, Ayushman, **Stand-Up India (SC!)** ✅ — MUDRA & APY as near-misses |
| 🎓 **Priya** | 20 · Female · Urban MH · Student · 12th · ₹1–2.5L · OBC · BPL No · pucca Yes · bank Yes | NSP + Post-Matric OBC scholarships ✅, Ayushman near-miss |
| 💼 **Amit** | 28 · Male · Delhi · Urban · Business · Graduate · ₹2.5–5L · General · new idea · services · pucca No · bank Yes | MUDRA + PMEGP + CGTMSE + Seed Fund ✅; **Stand-Up India near-miss with partnership tip**, PMAY-U gap **₹75,000** precise |
| 👩‍👧 **Sunita** | 35 · Female · Rural MP · Homemaker · <₹1L · ST · BPL Yes · pucca No · bank **No** · daughter+SHG | 8 schemes ✅ incl. **Jan Dhan**; insurance/pension become **near-misses that point back to Jan Dhan** (cross-scheme reasoning!) |

*(The same personas also exist as API fixtures — `POST /api/demo/ramesh` returns the full transcript + report, used by the test suite.)*

**Judges' moments — three, in this order:**

1. **The doubt** — midway through Ramesh's flow, when the BPL question appears, type **"BPL kya hai?"** instead of answering. It explains BPL in simple Hindi (ration card, SECC list) and re-asks. Flow intact.
2. **The real conversation** — on the very next question type **"mere paas aadhaar card nahi hai"**. It gives a complete answer (where to enrol, what to carry, that it's free, the EID slip that works meanwhile), then resumes the intake. *This is the bit that separates a chatbot from a form.* Then type **"actually meri income 2 lakh hai"** — it corrects the earlier answer in place.
3. **The checklist** *(Key Feature 7)* — open the report and scroll to **Documents to collect**: one list across every matched scheme, deduplicated, "needed for ALL your schemes" on Aadhaar, and under each missing one, exactly how to get it. Hit Print — the PDF has ☐ checkboxes an NGO worker ticks off.

Unplug the Wi-Fi before any of it. Everything above still works.

Then show: the near-miss (amber) cards → Print/Save PDF → language toggle → sidebar Scheme Library.
Full script: **[demo/demo_script.md](demo/demo_script.md)** · Deploy & submission: **[demo/HACKATHON_SUBMISSION_GUIDE.md](demo/HACKATHON_SUBMISSION_GUIDE.md)** (GitHub push → Render free live link → demo video → form checklist).

---

## 🛠️ Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI + Uvicorn | required, instant, auto OpenAPI docs at `/docs` |
| Orchestration | LangGraph `StateGraph` | required by the problem statement; real graph per message |
| Eligibility | Custom deterministic rule engine | **correctness + explainability** > LLM improvisation |
| LLM | Gemini 2.0 Flash (optional) | free tier; summary polish + follow-up Q&A with hard fallback |
| Retrieval | Dependency-free lexical scorer over a curated corpus | deterministic, millisecond, works offline — an embedding DB would add a failure point for 25 articles |
| Data | 25-scheme + 25-article curated JSON (bilingual) | editable without touching code; add schemes in minutes |
| Frontend | Vanilla HTML/CSS/JS, glass UI | zero build step, runs anywhere |

## 📁 Layout

```
scheme-saathi/
├── data/
│   ├── schemes.json         # 25 schemes, bilingual eligibility rules + documents
│   └── knowledge.json       # 25 citizen-doubt articles (the RAG corpus)
├── app/
│   ├── main.py              # FastAPI entry (+ static hosting)
│   ├── api/                 # routes, sessions, demo runner, printable report
│   ├── graph/               # LangGraph state machine + state schema
│   ├── agents/
│   │   ├── intake.py        # adaptive questions, tolerant parsers, skip/correct
│   │   ├── prompts.py       # bilingual question bank + copy
│   │   ├── conversation.py  # turn classifier + grounded answering
│   │   └── knowledge.py     # lexical retriever over both corpora
│   ├── engine/              # rules · matcher · near-miss · ranker · documents ★ · reasoner
│   └── core/                # config (.env) + Gemini client (offline-safe)
├── frontend/                # chat UI + report dashboard + checklist
├── demo/                    # personas.json (one-click demos) + demo_script.md
└── tests/test_engine.py     # 70 tests — personas, gaps, ranking, adaptivity,
                             #   conversation routing, RAG retrieval, checklist
```

## 🌐 Extending

- **Add a scheme** → append one JSON object to `data/schemes.json` (no code changes; tests validate the format).
- **Add a state scheme** → same JSON pattern; the engine already supports `any`/`all` groups.
- **More languages** → add `*_mr`/`*_ta` fields; prompts module is centralized.
- **RAG over scheme PDFs** → the rule engine gives the *verdict*; drop guidelines into ChromaDB and let Gemini cite them in explanations (planned; hooks exist in `core/llm.py`).

## ⚠️ Disclaimer

Scheme data is curated from official public criteria (Dec 2024) and simplified for the demo — final eligibility is always verified by the concerned department/portal.

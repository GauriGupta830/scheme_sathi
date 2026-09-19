"""
LangGraph orchestration — one graph invocation per user message.

    START → intake ──┬─ more questions ───────────→ END (bot asks next question)
                     ├─ profile complete → pipeline → END (report generated)
                     └─ already done → followup → END (Q&A about the report)

If langgraph isn't importable the same three nodes run sequentially — identical
behaviour, zero demo risk (graceful degradation is a feature, not a bug).
"""

from __future__ import annotations

from typing import Optional

from ..agents import conversation as convo
from ..agents import intake as intake_mod
from ..agents.prompts import (
    DONE_EN, DONE_HI, ERROR_EN, ERROR_HI,
    GENERAL_HELP_EN, GENERAL_HELP_HI,
    PROFILE_NOTE_EN, PROFILE_NOTE_HI, WELCOME_EN, WELCOME_HI,
    RESUME_EN, RESUME_HI,
)
from ..engine.reasoner import build_report
from ..core import llm
from .state import GraphState

try:  # pragma: no cover - depends on environment
    from langgraph.graph import END, START, StateGraph
    HAS_LANGGRAPH = True
except Exception:  # pragma: no cover
    END = START = None
    HAS_LANGGRAPH = False


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _progress(profile: dict) -> tuple[int, int]:
    total = intake_mod.questions_total_for(profile)
    remaining = len(intake_mod.pending_question_ids(profile))
    return total - remaining, total


def _question_payload(state: GraphState, q: dict, prefix: Optional[str] = None) -> GraphState:
    lang = state["language"]
    text = intake_mod.render_question(q, state["profile"], lang)
    if prefix:
        text = prefix + "\n\n" + text
    state["bot_messages"] = [text]
    state["quick_replies"] = intake_mod.render_options(q, lang, state["profile"])
    state["next_qid"] = q["id"]
    state["input_type"] = q.get("type", "text")
    state["step"], state["total_steps"] = _progress(state["profile"])
    return state


def _resume_line(lang: str) -> str:
    return RESUME_HI if lang == "hi" else RESUME_EN


def _help_payload(state: GraphState, q: dict, help_kind: str) -> GraphState:
    """The user asked a doubt about the CURRENT question — explain, then re-ask.

    With a Gemini key the explanation is conversational (grounded in the curated
    help text); without one we respond with that same template help text, so the
    "ask me anything, anytime" promise holds even fully offline.
    """
    lang = state.get("language") or "en"
    parts: list[str] = []

    explained = llm.explain_doubt(state.get("message", ""), q, state["profile"], lang)
    if explained:
        parts.append(explained)
    else:
        if help_kind == "general":
            parts.append(GENERAL_HELP_HI if lang == "hi" else GENERAL_HELP_EN)
        help_text = intake_mod.help_text_for(q, lang)
        if help_text:
            prefix = "💡 " if help_kind == "question" else ""
            parts.append(prefix + help_text)

    return _question_payload(state, q, prefix="\n\n".join(parts) if parts else None)


def _question_answer_payload(state: GraphState, q: Optional[dict]) -> GraphState:
    """The user asked a REAL question (not about the pending field).

    Answers it properly from the knowledge base — Gemini-polished when a key is
    present, the curated passage verbatim otherwise — then re-asks whatever the
    intake was waiting on, so a five-minute detour about Aadhaar cards costs the
    flow nothing.
    """
    lang = state.get("language") or "en"
    message = state.get("message", "")
    profile = state["profile"]

    answer = convo.answer_question(message, profile, lang, question=q, report=state.get("report"))

    if not answer:
        # Nothing relevant retrieved. If the doubt is plausibly about the current
        # question, fall back to that question's curated help; else say so honestly.
        help_text = intake_mod.help_text_for(q, lang) if q else ""
        answer = ("💡 " + help_text) if help_text else convo.unknown_reply(lang, q)

    if q:
        return _question_payload(state, q, prefix=answer + "\n\n" + _resume_line(lang))
    state["bot_messages"] = [answer]
    return state


def _apply_correction(state: GraphState, qid: str, value) -> None:
    """Rewrite one already-given answer ('actually my income is 2 lakh')."""
    profile = state["profile"]
    q = intake_mod.get_question(qid)
    if not q:
        return
    field = q.get("field", qid)
    profile[field] = value
    intake_mod.unmark_skipped(profile, field)
    if qid == "language":
        profile["language"] = value
        state["language"] = value
    # a changed answer can make later answers irrelevant (farmer → student)
    if qid == "occupation":
        for dependent in ("land_holding", "business_age_years", "business_sector", "education_level"):
            dq = intake_mod.get_question(dependent)
            if dq and dq.get("ask_if") and not dq["ask_if"](profile):
                profile.pop(dependent, None)


def intake_node(state: GraphState) -> GraphState:
    """Parse the user's answer to the pending question, then ask the next one."""
    profile = state["profile"]
    lang = profile.get("language") or "en"

    # Auto-language-detection on the very first free-text touch
    if not profile.get("language") and state.get("message"):
        lang = intake_mod.detect_language(state["message"])
    state["language"] = lang

    current_q = intake_mod.get_question(state.get("current_qid") or "")
    message = (state.get("message") or "").strip()
    value = None

    if current_q:
        intent = convo.classify(message, current_q, profile, done=False)

        # ---- "shuru se karo" — wipe the profile and begin again ----
        if intent == "restart":
            keep_lang = profile.get("language")
            profile.clear()
            if keep_lang:
                profile["language"] = keep_lang
            state["done"] = False
            state["report"] = None
            first = intake_mod.next_question(profile) or intake_mod.QUESTIONS[0]
            reply = ("ठीक है, बिल्कुल शुरू से चलते हैं — पुराने जवाब हटा दिए। 🔄"
                     if lang == "hi" else
                     "Sure, let's start fresh — I've cleared your earlier answers. 🔄")
            return _question_payload(state, first, prefix=reply)

        # ---- the user wants to move on without answering ----
        if intent == "skip":
            field = current_q.get("field", current_q["id"])
            intake_mod.mark_skipped(profile, field)
            nxt = intake_mod.next_question(profile)
            reply = convo.skip_reply(current_q, lang)
            if nxt:
                return _question_payload(state, nxt, prefix=reply)
            state["bot_messages"] = [reply]
            state["ready_to_report"] = True
            return state

        # ---- "actually, my income is 2 lakh" — fix an earlier answer ----
        if intent == "correction":
            fix = convo.detect_correction(message, profile)
            if fix:
                qid, new_value = fix
                _apply_correction(state, qid, new_value)
                lang = state.get("language") or lang
                reply = convo.correction_reply(intake_mod.get_question(qid) or current_q, new_value, lang)
                nxt = intake_mod.next_question(profile)
                if nxt:
                    return _question_payload(state, nxt, prefix=reply)
                state["bot_messages"] = [reply]
                state["ready_to_report"] = True
                return state

        # ---- friendly chit-chat: answer warmly, then re-ask ----
        if intent == "smalltalk":
            cat = intake_mod.looks_like_smalltalk(message)
            reply = intake_mod.smalltalk_reply(cat, lang, str(profile.get("name") or ""))
            return _question_payload(state, current_q, prefix=reply)

        # ---- a doubt about THIS question ("BPL kya hai?") ----
        if intent == "help":
            return _help_payload(state, current_q, "general")

        # ---- any other real question ("aadhaar nahi hai", "MUDRA kya hai?") ----
        if intent == "question":
            # a doubt clearly about the pending field keeps the curated,
            # question-specific explanation; anything broader goes to the KB
            if convo.is_about_current_question(message, current_q):
                return _help_payload(state, current_q, "question")
            return _question_answer_payload(state, current_q)

        ok, value = intake_mod.parse_answer(current_q, message, profile)
        if not ok:
            err = (ERROR_HI if lang == "hi" else ERROR_EN)
            return _question_payload(state, current_q, prefix=err.rstrip() + " ")

        field = current_q.get("field", current_q["id"])
        profile[field] = value
        intake_mod.unmark_skipped(profile, field)

        # answering the language question switches the conversation language
        if current_q["id"] == "language":
            lang = value
            profile["language"] = value
        elif not profile.get("language"):
            profile["language"] = lang
        state["language"] = lang

    nxt = intake_mod.next_question(profile)
    if nxt:
        prefix = None
        # contextual acknowledgment makes the bot feel smart & adaptive
        if current_q and current_q["id"] == "occupation":
            notes = PROFILE_NOTE_HI if lang == "hi" else PROFILE_NOTE_EN
            prefix = notes.get(value)  # type: ignore[arg-type]
        return _question_payload(state, nxt, prefix=prefix)

    state["ready_to_report"] = True
    return state


def pipeline_node(state: GraphState) -> GraphState:
    """Profile complete → match, detect near-misses, rank, reason, report."""
    profile = state["profile"]
    lang = state.get("language", "en")
    report = build_report(profile)

    # Optional Gemini polish — silent fallback to the template summary
    polished = llm.polish_summary(profile, report, lang)
    if polished:
        report["summary_llm"] = polished

    state["report"] = report
    state["done"] = True
    state["ready_to_report"] = False
    # tells the API layer to push this report to the client even if one already
    # existed — a correction rebuilds it and the UI must not show stale results
    state["report_refreshed"] = True
    done_tmpl = DONE_HI if lang == "hi" else DONE_EN
    state["bot_messages"] = [done_tmpl.format(
        name=profile.get("name", ""), total=report["n_checked"]
    )]
    state["quick_replies"] = []
    state["step"], state["total_steps"] = _progress(profile)
    return state


def _documents_reply(report: dict, lang: str) -> str:
    """KEY FEATURE 7 in chat form — the consolidated checklist, not one scheme's list."""
    from ..engine.documents import checklist_summary

    summary = report.get("documents_checklist") or checklist_summary(report)
    items = summary.get("items") or []
    hi = lang == "hi"
    if not items:
        return ("अभी कोई मैच नहीं है, इसलिए दस्तावेज़ सूची खाली है।" if hi
                else "No matched schemes yet, so there's no checklist to build.")

    head = (f"📋 **आपकी दस्तावेज़ चेकलिस्ट** — {len(items)} दस्तावेज़, "
            f"आपकी सभी मैच हुई योजनाओं के लिए एक साथ:"
            if hi else
            f"📋 **Your documents checklist** — {len(items)} documents, "
            f"covering every scheme you matched:")

    lines = [head, ""]
    for d in items[:10]:
        label = d["label_hi"] if hi else d["label_en"]
        n = d["n_schemes"]
        if d.get("universal"):
            tag = "सभी योजनाओं के लिए" if hi else "needed for all of them"
        elif hi:
            tag = f"{n} योजना के लिए" if n == 1 else f"{n} योजनाओं के लिए"
        else:
            tag = f"needed by {n} scheme{'s' if n != 1 else ''}"
        lines.append(f"📄 **{label}** — {tag}")
        how = d["how_to_hi"] if hi else d["how_to_en"]
        if how and d["n_schemes"] >= 2:
            lines.append(f"   ↳ {how}")

    if len(items) > 10:
        lines.append(("…और " + str(len(items) - 10) + " और — पूरी सूची रिपोर्ट में है।") if hi
                     else f"…and {len(items) - 10} more — the full list is in your report.")

    lines.append("")
    lines.append(("💡 कोई दस्तावेज़ नहीं है? मुझसे पूछिए — जैसे \"आधार कार्ड नहीं है\" — "
                  "मैं बनवाने का तरीका बता दूँगा।" if hi else
                  "💡 Missing one? Just ask me — e.g. \"I don't have an Aadhaar card\" — "
                  "and I'll tell you how to get it."))
    return "\n".join(lines)


def followup_node(state: GraphState) -> GraphState:
    """Post-report Q&A. Uses Gemini when a key is configured, else templates."""
    profile = state["profile"]
    lang = state.get("language", "en")
    report = state.get("report") or {}
    message = (state.get("message") or "").strip()
    msg = message.lower()

    # "shuru se karo" post-report → fresh profile, back to question one
    if convo.looks_like_restart(message):
        keep_lang = profile.get("language")
        profile.clear()
        if keep_lang:
            profile["language"] = keep_lang
        state["done"] = False
        state["report"] = None
        first = intake_mod.next_question(profile) or intake_mod.QUESTIONS[0]
        reply = ("ठीक है, नई प्रोफ़ाइल से शुरू करते हैं — पुराने जवाब हटा दिए। 🔄"
                 if lang == "hi" else
                 "Sure, starting a fresh profile — I've cleared your earlier answers. 🔄")
        return _question_payload(state, first, prefix=reply)

    # "actually my income is 2 lakh" → fix the profile and rebuild the report
    fix = convo.detect_correction(message, profile, allow_without_cue=True)
    if fix:
        qid, new_value = fix
        _apply_correction(state, qid, new_value)
        lang = state.get("language") or lang
        q = intake_mod.get_question(qid)
        nxt = intake_mod.next_question(profile)
        head = convo.correction_reply(q or {}, new_value, lang)
        if nxt:
            # the correction opened up a question we never asked → ask it
            state["done"] = False
            state["report"] = report or None
            return _question_payload(state, nxt, prefix=head)
        state = pipeline_node(state)
        state["bot_messages"] = [head + "\n\n" + state["bot_messages"][0]]
        return state

    # small-talk stays warm even post-report (instant, offline)
    smalltalk = intake_mod.looks_like_smalltalk(message)
    if smalltalk:
        tip = ("\nकुछ और पूछना हो — जैसे \"sabse acchi scheme?\", \"documents\", \"apply\" — बस लिखिए! 😊"
               if lang == "hi" else
               "\nWant more — like \"best scheme?\", \"documents\", \"apply\" — just ask! 😊")
        state["bot_messages"] = [intake_mod.smalltalk_reply(smalltalk, lang, str(profile.get("name") or "")) + tip]
        return state

    llm_answer = llm.answer_followup(state.get("message", ""), profile, report, lang)
    if llm_answer:
        state["bot_messages"] = [llm_answer]
        return state

    # KEY FEATURE 7 — the consolidated required-documents checklist.
    # Asked in chat, it returns the same master checklist the report renders:
    # every document, deduplicated, with which schemes need it.
    if any(k in msg for k in ("document", "docs", "kagaz", "kagzat", "papers", "checklist",
                              "दस्तावेज़", "दस्तावेज", "कागज", "कागज़")):
        state["bot_messages"] = [_documents_reply(report, lang)]
        return state

    if any(k in msg for k in ("apply", "आवेदन", "कैसे करें", "kaise")):
        links = "\n".join(
            f"🔗 {c['name_hi' if lang == 'hi' else 'name_en'].split(' (')[0]}: {c['apply_url']}"
            for c in (report.get("eligible") or [])[:5]
        )
        head = "ये रहे आपके शीर्ष योजनाओं के आवेदन लिंक:" if lang == "hi" else "Here are the apply links for your top schemes:"
        state["bot_messages"] = [(head + "\n" + links) if links else ("कोई पात्र योजना नहीं मिली।" if lang == "hi" else "No eligible schemes found.")]
        return state

    # ---- a strong knowledge-base hit wins over the report heuristics.
    # "koi dalal paisa maangta hai kya?" is a question about middlemen, not a
    # request for the benefit total — the keyword scorer settles it. ----
    from ..agents import knowledge as kb
    hits = kb.search_knowledge(message, limit=1)
    if hits and hits[0]["_score"] >= 4.0:
        answered = convo.answer_question(message, profile, lang, question=None, report=report)
        if answered:
            state["bot_messages"] = [answered]
            return state

    # ---- offline smart Q&A: count / list / best / benefit (report-grounded) ----
    smart = _offline_followup(msg, profile, report, lang)
    if smart:
        state["bot_messages"] = [smart]
        return state

    # ---- anything else is a genuine question: answer it from the knowledge
    # base ("aadhaar nahi hai", "CSC kya hota hai", "MUDRA kitna deta hai") ----
    answered = convo.answer_question(message, profile, lang, question=None, report=report)
    if answered:
        state["bot_messages"] = [answered]
        return state

    default = (
        "आपकी रिपोर्ट ऊपर तैयार है! 📊\n• किसी भी कार्ड पर क्लिक कर के पूरा विश्लेषण देखें\n"
        "• 'Documents' पूछें दस्तावेज़ सूची के लिए\n• 'Apply' पूछें आवेदन लिंक के लिए\n"
        "• नई प्रोफ़ाइल के लिए ⟳ Restart दबाएँ"
        if lang == "hi" else
        "Your report is ready above! 📊\n• Tap any card for full reasoning, documents & apply links\n"
        "• Ask me 'documents' for the checklist\n• Ask me 'apply' for all links\n"
        "• Press ⟳ Restart to try a new profile"
    )
    state["bot_messages"] = [default]
    return state


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def welcome_state() -> GraphState:
    """Initial message shown when a session starts."""
    q = intake_mod.QUESTIONS[0]  # language question
    state: GraphState = {
        "profile": {},
        "language": "en",
        "current_qid": None,
        "bot_messages": [WELCOME_EN + "\n---\n" + WELCOME_HI],
        "quick_replies": intake_mod.render_options(q, "en", {}),
        "input_type": q.get("type", "text"),
        "next_qid": q["id"],
        "step": 0,
        "total_steps": len(intake_mod.QUESTIONS),
        "done": False,
    }
    return state


# ---------------------------------------------------------------------------
# Offline smart follow-up (no API key needed) — grounded in the user's report
# ---------------------------------------------------------------------------

_DOMAIN_MAP = [
    (("startup", "business", "vyapar", "vyavsay", "vyavasay", "udyam", "udyog", "enterprise",
      "dukaan", "shop", "mudra", "loan", "व्यापार", "व्यवसाय", "बिज़नेस", "स्टार्टअप", "उद्यम", "दुकान", "लोन"),
     ("Entrepreneurship", "Skill & Enterprise", "Micro Finance"),
     "startup/business", "स्टार्टअप/व्यवसाय"),
    (("kisan", "farm", "agri", "fasal", "kheti", "किसान", "खेती", "फसल"),
     ("Agriculture",), "farming", "खेती"),
    (("ghar", "house", "housing", "awas", "aawas", "makaan", "आवास", "घर", "मकान"),
     ("Housing",), "housing", "आवास"),
    (("scholarship", "student", "padhai", "education", "college", "छात्रवृत्ति", "पढ़ाई", "शिक्षा", "छात्र"),
     ("Education",), "education", "शिक्षा"),
    (("bima", "insurance", "बीमा"),
     ("Insurance",), "insurance", "बीमा"),
    (("pension", "पेंशन"),
     ("Pension",), "pension", "पेंशन"),
    (("health", "ilaj", "hospital", "swasthya", "ayushman", "स्वास्थ्य", "इलाज", "अस्पताल", "आयुष्मान"),
     ("Health",), "health", "स्वास्थ्य"),
    (("mahila", "women", "woman", "ladies", "महिला", "औरत"),
     ("Women", "Livelihood"), "women", "महिलाओं"),
]

_COUNT_WORDS = ("kitn", "how many", "kaun", "kon", "list", "which", "what", "schemes for",
                "ke liye", "liye", "कितन", "कौन", "लिए")
_BEST_WORDS = ("best", "sabse acchi", "sabse achi", "sabse badhiya", "sabse best", "top scheme",
               "sabse jyada", "zyada fayda", "सबसे अच्छी", "सबसे अच्छा", "सबसे बढ़िया", "ज़्यादा फ़ायदा")
_BENEFIT_WORDS = ("kitna milega", "kitna paisa", "benefit", "fayda", "faayda", "subsidy", "paisa",
                  "फायदा", "फ़ायदा", "कितना मिलेगा", "पैसा", "सब्सिडी", "लाभ")


def _name(c: dict, lang: str) -> str:
    return c[f"name_{lang}"].split(" (")[0]


def _following_tip(lang: str) -> str:
    return ("\n👉 Cards खोलें या 'Apply' पूछें लिंक के लिए।" if lang == "hi"
            else "\n👉 Open the cards above for details, or ask 'apply' for links.")


def _offline_followup(msg_l: str, profile: dict, report: dict, lang: str) -> str | None:
    """Answer count/list/best/benefit questions from the report — deterministic,
    bilingual, zero hallucination by construction (uses only report data)."""
    if not report:
        return None
    elig = report.get("eligible") or []
    near = report.get("near_miss") or []
    hi = lang == "hi"

    def belongs(cards, cats):
        return [c for c in cards if any(cat in (c.get("category_en") or "") for cat in cats)]

    _NUM = ["", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]

    def names(cards, n=6):
        return "\n".join(f"{_NUM[i]} {_name(c, lang)}" for i, c in enumerate(cards[:n], 1))

    def first_gap(c):
        pools = (c.get("gaps_hi" if hi else "gaps_en") or []) + (c.get("reasons_hi" if hi else "reasons_en") or [])
        return pools[0] if pools else ""

    # ---- "sabse acchi scheme kaunsi?" (checked first — it also contains "kaunsi") ----
    if any(w in msg_l for w in _BEST_WORDS):
        if elig:
            top = elig[0]
            why = (top.get("reasons_hi" if hi else "reasons_en") or [""])[0]
            benefit = top.get("benefit_hi" if hi else "benefit_en", "")
            return ((f"आपका **सबसे मज़बूत मैच #1: {_name(top, lang)}** 🏆\n💰 {benefit}\n✅ क्योंकि: {why}" + _following_tip(lang)) if hi else
                    (f"Your **strongest match is #1: {_name(top, lang)}** 🏆\n💰 {benefit}\n✅ Because: {why}" + _following_tip(lang)))

    # ---- "kitna paisa milega / fayda kya?" (before COUNT — "kitna paisa" also starts with "kitn") ----
    if any(w in msg_l for w in _BENEFIT_WORDS):
        from ..engine.rules import inr
        v = report.get("top_benefit_estimate") or 0
        top_lines = "\n".join(f"💰 {_name(c, lang)} → {c.get('benefit_hi' if hi else 'benefit_en', '')}"
                              for c in elig[:4])
        return ((f"टॉप मैच का कुल लाभ अनुमान ≈ **{inr(v)}+**\n" + top_lines + _following_tip(lang)) if hi else
                (f"Estimated combined value of top matches ≈ **{inr(v)}+**\n" + top_lines + _following_tip(lang)))

    # ---- "startup ke liye kitni schemes hai?" → domain count/list ----
    if any(w in msg_l for w in _COUNT_WORDS):
        for keys, cats, dom_en, dom_hi in _DOMAIN_MAP:
            if any(k in msg_l for k in keys):
                e = belongs(elig, cats)
                n = belongs(near, cats)
                if e:
                    head = (f"{dom_hi} के लिए आप **{len(e)} योजनाओं** के पूरी तरह पात्र हैं ✅\n" if hi
                            else f"For {dom_en}, you're FULLY eligible for **{len(e)} scheme{'s' if len(e) != 1 else ''}** ✅\n")
                    tail = (f"\nऔर **{len(n)}** नियर-मिस में हैं — थोड़ा सुधार से मिल सकती हैं ⚠️" if (hi and n)
                            else f"\nPlus **{len(n)}** near-miss — small gaps away ⚠️" if n else "")
                    mid = (f" — जैसे {', '.join(_name(c, lang) for c in n[:2])}" if n else "")
                    return head + names(e) + tail + mid + _following_tip(lang)
                if n:
                    miss = (f"{dom_hi} में पूरी पात्रता अभी नहीं, पर **{len(n)} योजनाएँ बहुत करीब** हैं ⚠️\n" if hi
                            else f"No full {dom_en} match yet, but **{len(n)} scheme{'s' if len(n) != 1 else ''} very close** ⚠️\n")
                    gaps = "\n".join(f"• {_name(c, lang)}: {first_gap(c)}" for c in n[:3])
                    return miss + gaps + _following_tip(lang)
                return (f"{dom_hi} के लिए इस प्रोफ़ाइल में अभी कोई मैच नहीं निकला — नीचे 'Not eligible' सेक्शन में वजह देखें।"
                        if hi else
                        f"No {dom_en} schemes matched this profile — check the 'Not eligible' section for the exact reasons.")

        # generic count → the whole report picture
        t5 = ", ".join(_name(c, lang) for c in elig[:3])
        return ((f"कुल **{report['n_checked']}** योजनाएँ जाँचीं → **{report['n_eligible']} पूरी तरह पात्र** ✅ + "
                 f"**{report['n_near_miss']} नियर-मिस** ⚠️\nशीर्ष मैच: {t5}" + _following_tip(lang)) if hi else
                (f"Checked **{report['n_checked']}** schemes → **{report['n_eligible']} fully eligible** ✅ + "
                 f"**{report['n_near_miss']} near-miss** ⚠️\nTop matches: {t5}" + _following_tip(lang)))

    return None


def _router(state: GraphState) -> str:
    if state.get("ready_to_report"):
        return "pipeline"
    if state.get("done"):
        return "followup"
    return "end"


if HAS_LANGGRAPH:
    _builder = StateGraph(GraphState)
    _builder.add_node("intake", intake_node)
    _builder.add_node("pipeline", pipeline_node)
    _builder.add_node("followup", followup_node)
    # if the report already exists, skip intake entirely → straight to Q&A
    _builder.add_conditional_edges(START, lambda s: "followup" if s.get("done") else "intake",
                                   {"followup": "followup", "intake": "intake"})
    _builder.add_conditional_edges("intake", _router, {"pipeline": "pipeline", "followup": "followup", "end": END})
    _builder.add_edge("pipeline", END)
    _builder.add_edge("followup", END)
    _graph = _builder.compile()
else:  # pragma: no cover
    _graph = None


def process_message(profile: dict, message: str, current_qid: Optional[str],
                    done: bool, report: Optional[dict]) -> GraphState:
    """Public entry point used by the API layer. Runs one turn of the graph."""
    language = profile.get("language") or intake_mod.detect_language(message)
    init: GraphState = {
        "message": message,
        "profile": profile,
        "current_qid": current_qid,
        "language": language,
        "done": done,
        "report": report,
    }
    if _graph is not None:
        return _graph.invoke(init)
    # sequential fallback (identical node logic)
    if done:
        return followup_node(init)
    state = intake_node(init)
    if state.get("ready_to_report"):
        state = pipeline_node(state)
    return state

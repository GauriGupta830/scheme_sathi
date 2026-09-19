"""
Conversation layer — what makes Scheme Saathi *talk* instead of interrogate.

A rigid intake bot has exactly one acceptable input per turn: the answer.
Real citizens don't behave like that. Mid-form they say things like

    "BPL kya hai?"                    → a doubt about the current question
    "mere paas aadhaar card nahi hai" → a doubt about the whole process
    "MUDRA me kitna loan milta hai?"  → a question about a scheme
    "pata nahi, chhod do"             → they want to skip
    "nahi nahi, meri income 2 lakh"   → they want to fix an earlier answer
    "thanks bhai"                     → small talk

This module classifies the turn (`classify`) and produces a real, grounded
answer (`answer_question`) for anything that isn't a form answer. The graph
then re-asks the pending question, so the flow is never lost.

Grounding, always:
  · knowledge.py retrieves curated passages (help articles + scheme records)
  · with a Gemini key, the model rewrites them conversationally but may use
    NOTHING else as fact (see core/llm.py)
  · with no key, the curated passage IS the answer
Same knowledge either way — the LLM only changes the tone, never the facts.
"""

from __future__ import annotations

import re
from typing import Optional

from . import intake as intake_mod
from . import knowledge
from ..core import llm

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

SKIP_PHRASES = {
    "skip", "skip it", "skip this", "skip karo", "chhodo", "chodo", "chhod do", "chod do",
    "choddo", "next", "next question", "aage", "aage badho", "aage badhao", "agla sawal",
    "agla", "pass", "leave it", "rehne do", "rehne de", "nahi batana", "nahi bataunga",
    "nahi batana chahta", "not comfortable", "prefer not to say", "dont want to answer",
    "don't want to answer", "छोड़ो", "छोड़ दो", "आगे", "आगे बढ़ो", "अगला", "अगला सवाल",
    "रहने दो", "नहीं बताना", "स्किप",
}

RESTART_PHRASES = {
    "restart", "restart karo", "start over", "start again", "start from beginning",
    "reset", "reset karo", "new session", "nayi profile", "new profile",
    "phir se shuru", "phir se shuru karo", "fir se shuru", "fir se shuru karo",
    "dobara shuru", "dobara shuru karo", "naya shuru", "naye sire se",
    "shuru se", "shuru se karo", "shuru se shuru karo", "sab hata do", "clear karo",
    "नया सत्र", "नई प्रोफ़ाइल", "फिर से शुरू", "फिर से शुरू करो", "दोबारा शुरू",
    "दोबारा शुरू करो", "शुरू से", "शुरू से करो", "सब हटा दो",
}

# an explicit "I want to change something" cue
_CORRECTION_CUES = (
    "actually", "correction", "correct kar", "change kar", "change my", "badal do", "badlo",
    "badal dijiye", "sudhar do", "galat bata", "galat likh", "galti se", "maine galat",
    "i said wrong", "wrong answer", "not correct", "nahi nahi", "no no", "sorry mera",
    "sorry meri", "update kar", "edit kar", "बदल दो", "बदलिए", "सुधार", "गलत बता", "गलती से",
    "माफ़ करना मेरी", "माफ करना मेरा",
)

# field → words that identify it in a free-form correction
_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "annual_income": ("income", "aay", "aamdani", "kamai", "salary", "kamata", "kamati",
                      "आय", "आमदनी", "कमाई", "कमाता", "कमाती", "सैलरी", "इनकम"),
    "age": ("age", "umar", "umra", "saal ka", "saal ki", "years old", "उम्र", "साल का", "साल की"),
    "occupation": ("occupation", "kaam", "pesha", "job", "naukri", "farmer", "kisan", "student",
                   "chhatra", "business", "vyapar", "dukaan", "homemaker", "grihini",
                   "पेशा", "काम", "किसान", "छात्र", "व्यापार", "दुकान", "गृहिणी", "नौकरी"),
    "state": ("state", "rajya", "rehta hu", "rehti hu", "rehte hai", "राज्य", "रहता", "रहती"),
    "area_type": ("rural", "urban", "gaon", "gaanv", "sheher", "shehar", "city", "village",
                  "ग्रामीण", "शहरी", "गाँव", "गांव", "शहर"),
    "category": ("category", "varg", "jati", "caste", "general", "obc", "sc", "st",
                 "वर्ग", "जाति", "सामान्य", "ओबीसी", "एससी", "एसटी"),
    "gender": ("gender", "ling", "male", "female", "aadmi", "aurat", "mahila", "purush",
               "लिंग", "पुरुष", "महिला", "औरत"),
    "is_bpl": ("bpl", "ration card", "rashan", "बीपीएल", "राशन"),
    "land_holding": ("land", "zameen", "jameen", "hectare", "bigha", "acre", "khet",
                     "ज़मीन", "जमीन", "हेक्टेयर", "बीघा", "एकड़", "खेत", "भूमि"),
    "education_level": ("education", "padhai", "padha", "class", "pass", "graduate", "degree",
                        "शिक्षा", "पढ़ाई", "पास", "स्नातक", "कक्षा"),
    "has_bank_account": ("bank", "khata", "account", "बैंक", "खाता"),
    "owns_pucca_house": ("pucca", "pakka", "house", "ghar", "makan", "पक्का", "घर", "मकान"),
    "business_age_years": ("business", "vyapar", "dukaan", "startup", "व्यापार", "दुकान"),
    "business_sector": ("sector", "manufacturing", "services", "trading", "क्षेत्र", "विनिर्माण",
                        "सेवा", "व्यापार"),
    "name": ("name", "naam", "नाम"),
}


def _norm(text: str) -> str:
    t = re.sub(r"[^\w\s\u0900-\u097F₹.,/-]", " ", (text or "").strip().lower())
    return re.sub(r"\s+", " ", t).strip()


def looks_like_skip(message: str) -> bool:
    t = _norm(message).rstrip(".!")
    return t in SKIP_PHRASES


def looks_like_restart(message: str) -> bool:
    t = _norm(message).rstrip(".!")
    return t in RESTART_PHRASES


def _extract_value(q: dict, message: str, profile: dict) -> tuple[bool, object]:
    """Pull an answer value out of a full sentence.

    The intake parser expects a bare answer ("SC", "2 lakh"). A correction
    arrives as prose ("sorry meri category actually SC hai"), so for choice-like
    questions we also scan the sentence word by word for an option match.
    """
    ok, value = intake_mod.parse_answer(q, message, profile)
    if ok and q["type"] not in ("text",):
        return True, value
    if q["type"] in ("choice", "yesno", "multichoice"):
        words = [w for w in re.split(r"[\s,./]+", message.strip()) if w]
        # longest windows first so "post graduate" beats "graduate"
        for size in (3, 2, 1):
            for i in range(len(words) - size + 1):
                chunk = " ".join(words[i:i + size])
                if len(chunk) < 2:
                    continue
                got, val = intake_mod.parse_answer(q, chunk, profile)
                if got and val is not None and val != []:
                    return True, val
    return (ok, value) if ok else (False, None)


def detect_correction(message: str, profile: dict, allow_without_cue: bool = False
                      ) -> Optional[tuple[str, object]]:
    """Spot 'actually my income is 2 lakh' and return (question_id, new_value).

    Conservative on purpose: mid-intake it needs an explicit correction cue so a
    plain answer is never hijacked. After the report there is no pending
    question to confuse, so `allow_without_cue` relaxes that.
    """
    t = _norm(message)
    if not t:
        return None
    has_cue = any(c in t for c in _CORRECTION_CUES)
    if not has_cue and not allow_without_cue:
        return None

    from .prompts import QUESTIONS

    best: Optional[tuple[int, str, object]] = None
    for q in QUESTIONS:
        field = q.get("field", q["id"])
        if field == "language":
            continue
        # only fields we already know (or would ask) can be corrected
        hints = _FIELD_HINTS.get(field, ())
        hit = next((h for h in hints if h in t), None)
        if not hit:
            continue
        ok, value = _extract_value(q, message, profile)
        if not ok:
            continue
        # a correction must actually change something
        if profile.get(field) == value:
            continue
        weight = len(hit) + (5 if profile.get(field) is not None else 0)
        if best is None or weight > best[0]:
            best = (weight, q["id"], value)
    if best:
        return best[1], best[2]
    return None


def _is_exact_option(question: dict, message: str, profile: dict) -> bool:
    """Did the user click a quick-reply chip (or type its label verbatim)?"""
    t = _norm(message)
    if not t:
        return False
    for opt in intake_mod.visible_options(question, profile):
        for candidate in (opt.get("label_en"), opt.get("label_hi"), opt.get("value")):
            if candidate is not None and _norm(str(candidate)) == t:
                return True
    return False


def classify(message: str, question: Optional[dict], profile: dict, done: bool) -> str:
    """Route one user turn.

    Returns one of:
      'restart' | 'skip' | 'correction' | 'smalltalk' | 'help' | 'question' | 'answer'
    """
    t = (message or "").strip()
    if not t:
        return "answer"

    # A quick-reply chip always means what it says. Checked first so a label
    # like "Willing to join a women's Self-Help Group" is never mistaken for a
    # cry for help, and "None of these" is never read as small talk.
    if question is not None and _is_exact_option(question, t, profile):
        return "answer"

    if looks_like_restart(t):
        return "restart"
    if looks_like_skip(t):
        return "skip"
    if detect_correction(t, profile, allow_without_cue=done):
        return "correction"
    if intake_mod.looks_like_smalltalk(t):
        return "smalltalk"
    kind = intake_mod.looks_like_help(t)
    if kind == "general":
        return "help"
    if kind == "question":
        return "question"
    if question is None:
        # no pending question (post-report) → everything else is a question
        return "question"
    ok, _ = intake_mod.parse_answer(question, t, profile)
    if ok:
        return "answer"
    # Unparseable during intake: before scolding the user, see whether the
    # knowledge base recognises it as a real doubt ("aadhaar card nahi hai").
    if knowledge.search_knowledge(t, limit=1):
        return "question"
    return "answer"  # let the parser produce the friendly retry


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


# phrases that mean "I'm confused by what you just asked me" rather than
# "here is a new topic I want to know about"
_ABOUT_THIS_PHRASES = (
    "samajh nahi", "samjh nahi", "nahi samjha", "samajh mein nahi", "samajh me nahi",
    "nahi samajh", "matlab kya", "ka matlab", "iska matlab", "ye kya", "yeh kya",
    "kya matlab", "dobara", "phir se bolo", "repeat", "clear nahi", "confused",
    "don't understand", "dont understand", "do not understand", "didn't get", "didnt get",
    "not clear", "come again", "what do you mean", "samajh नहीं",
    "समझ नहीं", "नहीं समझ", "समझ में नहीं", "मतलब क्या", "इसका मतलब", "दोबारा", "फिर से बोलो",
    "नहीं पता", "पता नहीं", "nahi pata", "pata nahi", "no idea", "not sure", "nahi maloom",
    "maloom nahi", "मालूम नहीं", "नहीं मालूम",
)


def is_about_current_question(message: str, question: Optional[dict]) -> bool:
    """Is this doubt about the pending intake question, or a new topic?

    Decides between the curated per-question explanation (better for "BPL kya
    hai?" while the BPL question is on screen) and a knowledge-base answer
    (better for "mere paas aadhaar nahi hai", which has nothing to do with it).
    """
    if not question:
        return False
    t = _norm(message)
    if not t:
        return False
    if any(p in t for p in _ABOUT_THIS_PHRASES):
        return True
    if t in {"?", "??", "???"}:
        return True

    q_text = " ".join(
        str(question.get(k, "")) for k in ("text_en", "text_hi", "help_en", "help_hi")
    )
    q_text += " " + " ".join(
        f"{o.get('label_en', '')} {o.get('label_hi', '')} {o.get('value', '')}"
        for o in (question.get("options") or [])
    )
    q_overlap = knowledge._token_overlap(knowledge.tokens(message), q_text)

    # if the knowledge base has a clearly better match, it's a new topic
    kb = knowledge.search_knowledge(message, limit=1)
    kb_score = kb[0]["_score"] if kb else 0.0
    if kb_score >= 3.0 and q_overlap < 0.6:
        return False
    return q_overlap >= 0.34


def answer_question(message: str, profile: dict, lang: str,
                    question: Optional[dict] = None,
                    report: Optional[dict] = None,
                    schemes: Optional[list] = None) -> Optional[str]:
    """A real answer to a free-form question — LLM-polished, KB-grounded."""
    if schemes is None:
        try:
            from ..engine.matcher import load_schemes
            schemes = load_schemes()
        except Exception:  # pragma: no cover - data always present in practice
            schemes = []

    context = knowledge.context_for_llm(message, lang, schemes)
    polished = llm.chat_answer(message, context, profile, lang, question, report)
    if polished:
        return polished
    return knowledge.compose_offline_answer(message, lang, schemes)


def unknown_reply(lang: str, question: Optional[dict] = None) -> str:
    """Honest 'I don't know' — never invent a scheme rule."""
    if lang == "hi":
        base = ("इसका पक्का जवाब मेरे पास नहीं है, और अंदाज़े से कुछ कहना ठीक नहीं होगा। 🙏\n"
                "सरकारी योजनाओं की पूरी जानकारी myscheme.gov.in पर मिलेगी, या नज़दीकी CSC / "
                "जन सेवा केंद्र पर पूछ लीजिए।\n"
                "हाँ — पात्रता, दस्तावेज़, आवेदन या किसी योजना के बारे में पूछेंगे तो मैं ज़रूर बता दूँगा।")
    else:
        base = ("I don't have a reliable answer for that, and I'd rather not guess. 🙏\n"
                "For anything beyond these 25 schemes, myscheme.gov.in or your nearest CSC / "
                "Jan Seva Kendra is the right place to ask.\n"
                "But do ask me about eligibility, documents, how to apply, or any scheme here — "
                "that I can answer properly.")
    return base


def skip_reply(question: dict, lang: str) -> str:
    qname = question.get("text_hi" if lang == "hi" else "text_en", "")
    qname = re.sub(r"\s*\(.*?\)\s*", " ", qname).strip()
    if lang == "hi":
        return (f"ठीक है, यह सवाल छोड़ देते हैं — कोई ज़रूरत नहीं बताने की। 👍\n"
                f"(ध्यान रहे: इसके बिना कुछ योजनाएँ जाँची नहीं जा पाएँगी। बाद में बताना चाहें तो "
                f"बस लिख दीजिए।)")
    return ("No problem, we'll skip that one — you don't have to answer it. 👍\n"
            "(Just so you know: a few schemes can't be checked without it. Tell me any time "
            "later and I'll add it back.)")


def correction_reply(question: dict, value, lang: str) -> str:
    field = question.get("field", question.get("id", ""))
    shown = value
    if isinstance(value, bool):
        shown = ("हाँ" if value else "नहीं") if lang == "hi" else ("Yes" if value else "No")
    elif isinstance(value, list):
        shown = ", ".join(str(v) for v in value) or ("कोई नहीं" if lang == "hi" else "None")
    elif field == "annual_income":
        from ..engine.rules import inr
        shown = inr(value)
    elif field == "land_holding":
        shown = f"{value:g} " + ("हेक्टेयर" if lang == "hi" else "hectares")
    elif field == "age":
        shown = f"{value} " + ("वर्ष" if lang == "hi" else "years")
    elif isinstance(value, str):
        shown = value.replace("_", " ")
    if lang == "hi":
        return f"समझ गया, ठीक कर दिया ✅ — अब मैंने **{shown}** दर्ज कर लिया है।"
    return f"Got it, updated ✅ — I've changed that to **{shown}**."

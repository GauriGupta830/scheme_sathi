"""
Scheme Saathi — automated verification of the whole engine.

Run:  pytest tests/ -v

Covers all 4 judging criteria:
  correctness        — every persona produces exactly the eligibility verdicts
                       a human expert would (derived from official criteria)
  clarity            — every result carries bilingual explanations
  near-miss analysis — gap amounts are computed precisely (e.g. ₹75,000 over)
  adaptivity         — the intake flow asks farmers/students/entrepreneurs
                       different questions
"""

from __future__ import annotations

import json
import os

import pytest

from app.agents import intake as intake_mod
from app.api.demo_runner import load_personas, run_persona
from app.engine.matcher import load_schemes, match_all_schemes
from app.engine.reasoner import build_report
from app.engine.rules import inr

DATA_OK = os.path.exists(os.path.join(os.path.dirname(__file__), "..", "data", "schemes.json"))


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def test_schemes_database_is_rich():
    schemes = load_schemes()
    assert len(schemes) == 25, f"expected 25 schemes, found {len(schemes)}"
    for s in schemes:
        for key in ("id", "name_en", "name_hi", "benefit_en", "benefit_hi",
                    "apply_url", "documents_en", "rule_groups"):
            assert s.get(key), f"scheme {s.get('id')} missing {key}"
        assert s["apply_url"].startswith("http"), f"{s['id']} apply_url invalid"
        # every rule carries bilingual explanations (clarity of reasoning)
        for g in s["rule_groups"]:
            assert g.get("rules"), f"{s['id']} has an empty rule group"
            for r in g["rules"]:
                assert r.get("desc_en") and r.get("desc_hi"), f"{s['id']} rule lacks why-matched text"
                assert r.get("fail_en") and r.get("fail_hi"), f"{s['id']} rule lacks why-failed text"


def test_inr_formatting_indian_style():
    assert inr(100000) == "₹1,00,000"
    assert inr(5000000) == "₹50,00,000"
    assert inr(75000) == "₹75,000"
    assert inr(6000) == "₹6,000"


# ---------------------------------------------------------------------------
# End-to-end persona verdicts (correctness)
# ---------------------------------------------------------------------------


def _run(persona_id):
    personas = {p["id"]: p for p in load_personas()}
    session = {"id": "test", "profile": {}, "current_qid": None, "done": False, "report": None, "history": []}
    result = run_persona(persona_id, session)
    report = session["report"]
    eligible = {c["scheme_id"] for c in report["eligible"]}
    near = {c["scheme_id"] for c in report["near_miss"]}
    total = report["n_eligible"] + report["n_near_miss"] + len(report["not_eligible"])
    assert total == 25, "every scheme must receive a verdict"
    return personas[persona_id], report, eligible, near


@pytest.mark.parametrize("pid", ["ramesh", "priya", "amit", "sunita"])
def test_persona_expected_verdicts(pid):
    persona, report, eligible, near = _run(pid)
    exp = persona["expected"]
    assert set(exp["eligible"]) <= eligible, (
        f"{pid}: expected eligible {set(exp['eligible']) - eligible} missing"
    )
    assert set(exp["near_miss"]) <= near, (
        f"{pid}: expected near-miss {set(exp['near_miss']) - near} missing"
    )
    # nothing expected-eligible may appear as not-eligible
    not_elig = {c["scheme_id"] for c in report["not_eligible"]}
    assert not (set(exp["eligible"]) & not_elig)


def test_ramesh_farmer_core_schemes():
    _, report, eligible, near = _run("ramesh")
    assert {"pm_kisan", "pmfby", "pm_kusum", "pmay_gramin", "pmjay"} <= eligible
    assert "stand_up_india" in eligible  # SC entrepreneur
    assert "mudra" in near               # the plan's headline near-miss
    assert "jandhan" not in eligible     # already banked → correctly excluded


def test_priya_student_scholarships():
    _, report, eligible, near = _run("priya")
    assert {"nsp", "postmatric_obc"} <= eligible
    assert "postmatric_sc" not in eligible          # she is OBC, not SC
    assert "pmegp" not in near                      # never asked business q's → no fake near-miss
    assert "ssy" in near or "ssy" not in eligible   # no daughter under 10


def test_amit_entrepreneur_stack():
    _, report, eligible, near = _run("amit")
    assert {"mudra", "pmegp", "cgtmse", "sisf"} <= eligible
    assert "stand_up_india" in near  # General-category male → near-miss with partnership tip
    assert "pmay_urban" in near


def test_amit_income_gap_is_precise():
    """The money shot: exact gap math — ₹3,75,000 vs ₹3,00,000 limit = ₹75,000 over."""
    _, report, _, _ = _run("amit")
    pmay = next(c for c in report["near_miss"] if c["scheme_id"] == "pmay_urban")
    assert any("₹75,000" in g for g in pmay["gaps_en"]), pmay["gaps_en"]
    assert any("₹3,00,000" in g for g in pmay["gaps_en"]), pmay["gaps_en"]


def test_sunita_bank_account_cascade():
    """No bank account → Jan Dhan eligible; insurance/pension become near-misses
    whose tips point back to Jan Dhan. Cross-scheme reasoning!"""
    _, report, eligible, near = _run("sunita")
    assert "jandhan" in eligible
    assert {"pmjjby", "pmsby", "apy"} <= near
    assert {"ujjwala", "nrlm", "pmay_gramin", "pmjay", "ssy"} <= eligible
    pmjjby = next(c for c in report["near_miss"] if c["scheme_id"] == "pmjjby")
    assert any("Jan Dhan" in t for t in pmjjby["tips_en"])


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_ranking_is_sorted_and_bounded():
    _, report, _, _ = _run("ramesh")
    percents = [c["match_percent"] for c in report["eligible"]]
    assert percents == sorted(percents, reverse=True)
    assert all(0 <= p <= 100 for p in percents)


def test_report_is_bilingual_and_explained():
    _, report, _, _ = _run("priya")
    assert report["summary_en"] and report["summary_hi"]
    for card in report["eligible"]:
        assert card["reasons_en"] and card["reasons_hi"], card["scheme_id"]
        assert card["documents_en"] and card["apply_url"]


# ---------------------------------------------------------------------------
# Adaptive intake
# ---------------------------------------------------------------------------


def test_adaptive_questions_farmer():
    profile = {"occupation": "farmer", "annual_income": 150000}
    pending = intake_mod.pending_question_ids(profile)
    assert "land_holding" in pending
    assert "business_age_years" not in pending
    assert "education_level" not in pending  # farmers skip the education question
    assert "is_bpl" in pending               # low income → BPL question appears


def test_adaptive_questions_business():
    profile = {"occupation": "business", "annual_income": 500000}
    pending = intake_mod.pending_question_ids(profile)
    assert "business_age_years" in pending
    assert "business_sector" in pending
    assert "education_level" in pending
    assert "land_holding" not in pending
    assert "is_bpl" not in pending           # income too high → skipped


def test_adaptive_questions_student():
    profile = {"occupation": "student", "annual_income": 200000}
    pending = intake_mod.pending_question_ids(profile)
    assert "education_level" in pending
    assert "land_holding" not in pending
    assert "business_age_years" not in pending


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parsers_handle_real_answers():
    q_age = intake_mod.get_question("age")
    assert intake_mod.parse_answer(q_age, "मेरी उम्र 45 साल है") == (True, 45)
    # regression: raw numbers must never be swallowed by quick-reply labels
    assert intake_mod.parse_answer(q_age, "45") == (True, 45)   # "36–45" label used to steal this
    assert intake_mod.parse_answer(q_age, "26–35") == (True, 30)  # exact quick-reply click still works
    q_land = intake_mod.get_question("land_holding")
    assert intake_mod.parse_answer(q_land, "1.5") == (True, 1.5)
    assert intake_mod.parse_answer(q_land, "1 – 2 हे.") == (True, 1.5)

    q_income = intake_mod.get_question("annual_income")
    assert intake_mod.parse_answer(q_income, "1.5 lakh")[1] == 150000
    assert intake_mod.parse_answer(q_income, "देढ़ लाख 1.5 लाख")[1] == 150000

    q_bpl = intake_mod.get_question("is_bpl")
    assert intake_mod.parse_answer(q_bpl, "हाँ") == (True, True)
    assert intake_mod.parse_answer(q_bpl, "nahi") == (True, False)

    q_area = intake_mod.get_question("area_type")
    assert intake_mod.parse_answer(q_area, "गाँव") == (True, "rural")

    q_special = intake_mod.get_question("special")
    ok, val = intake_mod.parse_answer(q_special, "1, 4")
    assert ok and val == ["daughter_under_10", "willing_shg"]
    ok, val = intake_mod.parse_answer(q_special, "कोई नहीं")
    assert ok and val == []


def test_language_detection():
    assert intake_mod.detect_language("मुझे योजना चाहिए") == "hi"
    assert intake_mod.detect_language("I need a scheme") == "en"


# ---------------------------------------------------------------------------
# Adaptive option visibility (user's #1 UX ask)
# ---------------------------------------------------------------------------


def test_special_options_adapt_to_profile():
    q = intake_mod.get_question("special")

    male_urban = {"gender": "male", "area_type": "urban", "age": 30}
    opts = [o["value"] for o in intake_mod.visible_options(q, male_urban)]
    assert "pregnant_or_new_mother" not in opts   # never shown to a male
    assert "willing_shg" not in opts              # SHGs are rural women only
    assert "daughter_under_10" in opts            # fathers count too
    assert "traditional_artisan" in opts
    assert "none" in opts

    rural_woman = {"gender": "female", "area_type": "rural", "age": 30}
    opts_w = [o["value"] for o in intake_mod.visible_options(q, rural_woman)]
    assert {"pregnant_or_new_mother", "willing_shg", "daughter_under_10"} <= set(opts_w)

    urban_woman = {"gender": "female", "area_type": "urban", "age": 30}
    opts_u = [o["value"] for o in intake_mod.visible_options(q, urban_woman)]
    assert "pregnant_or_new_mother" in opts_u     # PMMVY applies everywhere
    assert "willing_shg" not in opts_u            # but not NRLM SHGs (rural only)

    teen = {"gender": "female", "area_type": "urban", "age": 16}
    opts_t = [o["value"] for o in intake_mod.visible_options(q, teen)]
    assert "pregnant_or_new_mother" not in opts_t
    assert "daughter_under_10" not in opts_t


def test_multichoice_indexes_track_filtered_options():
    """Numeric answers ('1, 4') must map to the buttons the user actually saw."""
    q = intake_mod.get_question("special")

    rural_woman = {"gender": "female", "area_type": "rural", "age": 30}
    ok, vals = intake_mod.parse_answer(q, "1, 4", rural_woman)
    assert ok and vals == ["daughter_under_10", "willing_shg"]

    male_urban = {"gender": "male", "area_type": "urban", "age": 30}
    # filtered list: [daughter_under_10, traditional_artisan, differently_abled, ...]
    ok, vals = intake_mod.parse_answer(q, "3", male_urban)
    assert ok and vals == ["differently_abled"]
    ok, vals = intake_mod.parse_answer(q, "None of these", male_urban)
    assert ok and vals == []


# ---------------------------------------------------------------------------
# "Ask anytime" help system (offline + Gemini-polished)
# ---------------------------------------------------------------------------


def test_every_question_has_bilingual_help():
    from app.agents.prompts import QUESTIONS
    for q in QUESTIONS:
        assert q.get("help_en"), f"question {q['id']} missing help_en"
        assert q.get("help_hi"), f"question {q['id']} missing help_hi"


def test_looks_like_help_catches_confusion():
    assert intake_mod.looks_like_help("BPL kya hai?") == "question"
    assert intake_mod.looks_like_help("samajh nahi aaya") == "question"
    assert intake_mod.looks_like_help("what is this") == "question"
    assert intake_mod.looks_like_help("?") == "general"
    assert intake_mod.looks_like_help("help") == "general"
    assert intake_mod.looks_like_help("मुझे नहीं आता") == "question"
    assert intake_mod.looks_like_help("ये क्या होता है") == "question"
    assert intake_mod.looks_like_help("मदद") == "general"


def test_looks_like_help_never_eats_real_answers():
    # every legitimate answer style must pass through to the parser
    assert intake_mod.looks_like_help("nahi") == ""          # classic NO answer
    assert intake_mod.looks_like_help("हाँ") == ""
    assert intake_mod.looks_like_help("yes") == ""
    assert intake_mod.looks_like_help("2") == ""
    assert intake_mod.looks_like_help("1, 3") == ""
    assert intake_mod.looks_like_help("1.5 lakh") == ""
    assert intake_mod.looks_like_help("kisan") == ""         # 'farmer' free text
    assert intake_mod.looks_like_help("🌾 Farmer") == ""     # chip label passthrough
    assert intake_mod.looks_like_help("हाँ / Yes") == ""     # yesno chip label
    assert intake_mod.looks_like_help("नहीं") == ""
    assert intake_mod.looks_like_help("Ramesh Kumar") == ""
    assert intake_mod.looks_like_help("") == ""


def test_help_interrupts_intake_without_losing_state():
    """A doubt answered mid-flow must re-ask the SAME question (step frozen),
    and the very next real answer must continue the flow normally."""
    from app.graph.main_graph import process_message, welcome_state

    ws = welcome_state()
    profile: dict = {}
    state = process_message(profile, "English", ws["next_qid"], False, None)
    assert state["next_qid"] == "name"
    state = process_message(profile, "Ramesh", state["next_qid"], False, None)
    assert profile["name"] == "Ramesh"
    assert state["next_qid"] == "age"

    # user suddenly asks a doubt about the age question
    step_before = state.get("step", 0)
    state2 = process_message(profile, "why do you need my age?", state["next_qid"], False, None)
    assert state2["next_qid"] == "age"                      # same question re-asked
    assert state2.get("step", 0) == step_before             # progress untouched
    assert "age" not in profile                             # nothing stored
    assert any("Reason" in m or "💡" in m or "age" in m.lower() for m in state2["bot_messages"])

    # and a normal answer right after simply continues the flow
    state3 = process_message(profile, "45", state2["next_qid"], False, None)
    assert profile["age"] == 45
    assert state3["next_qid"] == "gender"


def test_general_help_then_resume():
    from app.graph.main_graph import process_message

    profile: dict = {"language": "en"}
    state = process_message(profile, "Ramesh", "name", False, None)
    assert state["next_qid"] == "age"
    state2 = process_message(profile, "help", "age", False, None)
    assert "1️⃣" in state2["bot_messages"][0]              # the 4-step explainer
    assert state2["next_qid"] == "age"                      # flow frozen, re-asked


def test_bpl_doubt_shows_bpl_explanation_offline():
    """The flagship scenario: stuck on BPL, asks 'BPL kya hai' — offline fallback
    must produce the curated BPL explanation and re-ask the same question."""
    from app.graph.main_graph import process_message

    profile: dict = {"language": "hi", "name": "रमेश", "age": 45, "annual_income": 90000}
    state = process_message(profile, "BPL क्या होता है?", "is_bpl", False, None)
    blob = "\n".join(state["bot_messages"])
    assert "BPL" in blob
    assert "गरीबी रेखा" in blob                              # actual explanation
    assert "राशन कार्ड" in blob                              # actionable guidance
    assert state["next_qid"] == "is_bpl"                     # same question again
    assert state["quick_replies"]                            # yes/no buttons shown


def test_followup_chat_does_not_resend_report():
    """After the report is generated, follow-up Q&A must return report=None so
    the UI stays in chat (bug: every answer yanked the user back to the report)."""
    TestClient = pytest.importorskip("fastapi.testclient", reason="fastapi not installed in this env").TestClient
    from app.main import app
    client = TestClient(app)
    demo = client.post("/api/demo/ramesh").json()
    sid = demo["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "apply kaise karna hai"}).json()
    assert r["done"] is True
    assert r["report"] is None                     # <- the fix
    assert r["messages"] and r["messages"][0]      # answer still delivered


def test_every_chip_label_roundtrips():
    """Zero-trust UI contract: whatever text a quick-reply chip sends (its label),
    the parser MUST accept it — in BOTH languages. Guards the Hindi 'हाँ / Yes'
    infinite-loop bug class for every current and future question."""
    from app.agents.prompts import QUESTIONS
    rich_profile = {
        "age": 30, "gender": "female", "area_type": "rural",
        "occupation": "farmer", "annual_income": 80000, "name": "X",
    }
    checked = 0
    for q in QUESTIONS:
        if q.get("ask_if") and not q["ask_if"](rich_profile):
            continue  # question not shown for this profile
        for lang in ("en", "hi"):
            for opt in intake_mod.render_options(q, lang, rich_profile):
                ok, _ = intake_mod.parse_answer(q, str(opt["label"]), rich_profile)
                assert ok, (
                    f"chip '{opt['label']}' of question '{q['id']}' (lang={lang}) "
                    f"fails to parse — users would hit an infinite loop!"
                )
                checked += 1
    assert checked > 50, "expected to round-trip dozens of chip labels"


def test_hindi_yesno_chip_labels_parse():
    """The exact production bug: 'हाँ / Yes' & 'नहीं / No' chips on yes/no questions."""
    q = intake_mod.get_question("is_bpl")
    ok, val = intake_mod.parse_answer(q, "हाँ / Yes", {"annual_income": 80000})
    assert ok and val is True
    ok, val = intake_mod.parse_answer(q, "नहीं / No", {"annual_income": 80000})
    assert ok and val is False


def test_offline_followup_domain_count():
    """'startup ke liye kitni schemes hai' — offline, report-grounded answer."""
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/amit").json()["session_id"]   # entrepreneur profile
    r = client.post("/api/chat", json={"session_id": sid, "message": "startup ke liye kitni schemes hai"}).json()
    ans = " ".join(r["messages"])
    assert "eligible" in ans.lower() and "MUDRA" in ans.upper(), ans          # real count + scheme
    assert "📊" not in ans or "scheme" in ans.lower()                          # not the generic menu


def test_offline_followup_domain_count_hindi():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/ramesh").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "खेती के लिए कितनी योजनाएँ हैं"}).json()
    ans = " ".join(r["messages"])
    assert "खेती" in ans and ("पीएम" in ans or "PM" in ans), ans


def test_offline_followup_best_scheme():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/ramesh").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "sabse acchi scheme kaunsi hai"}).json()
    ans = " ".join(r["messages"])
    top_name = client.get(f"/api/report/{sid}").json()["eligible"][0]["name_hi"].split(" (")[0]
    assert top_name in ans, ans
    assert "🏆" in ans


def test_offline_followup_gibberish_falls_back():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/priya").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "cricket score batao"}).json()
    ans = " ".join(r["messages"])
    assert "report" in ans.lower() or "रिपोर्ट" in ans                        # safe generic menu


def test_offline_followup_benefit_value():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/amit").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "kitna paisa milega total"}).json()
    ans = " ".join(r["messages"])
    assert "₹" in ans and ("value" in ans.lower() or "लाभ" in ans), ans     # money answer, not menu


def test_smalltalk_detected():
    assert intake_mod.looks_like_smalltalk("hello") == "greet"
    assert intake_mod.looks_like_smalltalk("Kaise ho?") == "howru"
    assert intake_mod.looks_like_smalltalk("tum kaun ho") == "who"
    assert intake_mod.looks_like_smalltalk("What can you do?") == "what"
    assert intake_mod.looks_like_smalltalk("thank you so much") == "thanks"
    assert intake_mod.looks_like_smalltalk("theek hai") == "ack"
    assert intake_mod.looks_like_smalltalk("bye") == "bye"
    assert intake_mod.looks_like_smalltalk("hello kaise ho") == "howru"   # prefix strip
    assert intake_mod.looks_like_smalltalk("नमस्ते") == "greet"


def test_smalltalk_never_eats_answers():
    # everything that can be an answer must NOT be smalltalk
    for ans in ["हाँ", "nahi", "yes", "हाँ / Yes", "1", "2", "1, 3", "1.5 lakh", "kisan",
                "rural", "🌾 Farmer", "उत्तर प्रदेश", "Bpl kya hai", "help", "samajh nahi aaya"]:
        assert intake_mod.looks_like_smalltalk(ans) == "", f"'{ans}' wrongly treated as smalltalk"


def test_smalltalk_mid_intake_reasks_same_question():
    from app.graph.main_graph import process_message, welcome_state
    ws = welcome_state()
    profile: dict = {}
    s1 = process_message(profile, "English", ws["next_qid"], False, None)
    assert s1["next_qid"] == "name"
    step = s1.get("step", 0)
    s2 = process_message(profile, "hello, kaise ho?", "name", False, None)
    assert s2["next_qid"] == "name"                     # frozen, re-asked
    assert s2.get("step", 0) == step
    blob = " ".join(s2["bot_messages"])
    assert "great" in blob.lower()                      # friendly answer present
    assert "name" in blob.lower()                       # and the question again
    # real answer continues normally afterwards
    s3 = process_message(profile, "Gauri", "name", False, None)
    assert profile["name"] == "Gauri"
    assert s3["next_qid"] == "age"


def test_smalltalk_post_report():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/ramesh").json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "dhanyavad"}).json()
    assert "स्वागत" in " ".join(r["messages"])
    assert r["report"] is None                          # stays in chat


def test_smalltalk_fillers():
    assert intake_mod.looks_like_smalltalk("dhanyavad bhai") == "thanks"
    assert intake_mod.looks_like_smalltalk("are kaise ho bhai") == "howru"
    assert intake_mod.looks_like_smalltalk("ok ji") == "ack"
    assert intake_mod.looks_like_smalltalk("bye bhai") == "bye"
    # fillers must not rescue non-smalltalk
    assert intake_mod.looks_like_smalltalk("bhai 2 lakh kamata hu") == ""


# ---------------------------------------------------------------------------
# Conversational layer — "talk to me like a person, not a form"
# ---------------------------------------------------------------------------


def test_knowledge_base_is_well_formed():
    from app.agents.knowledge import load_knowledge
    kb = load_knowledge()
    assert len(kb) >= 20, "knowledge base should cover the common citizen doubts"
    seen = set()
    for a in kb:
        for key in ("id", "topic_en", "topic_hi", "keywords", "answer_en", "answer_hi"):
            assert a.get(key), f"knowledge article {a.get('id')} missing {key}"
        assert a["id"] not in seen, f"duplicate knowledge id {a['id']}"
        seen.add(a["id"])
        # answers must be substantial, not one-liners
        assert len(a["answer_en"]) > 200 and len(a["answer_hi"]) > 200, a["id"]


@pytest.mark.parametrize("query,expected_id", [
    ("BPL kya hai?", "bpl"),
    ("mere paas aadhaar card nahi hai", "no_aadhaar"),
    ("bank account nahi hai kya karu", "no_bank_account"),
    ("jaati praman patra kaise banwaye", "caste_certificate"),
    ("CSC kya hota hai", "csc_centre"),
    ("koi dalal paisa mangta hai kya", "is_it_free"),
    ("mera data safe hai kya", "privacy"),
    ("khatauni kahan se milegi", "land_records"),
    ("paisa nahi aaya abhi tak", "dbt_seeding"),
    ("ghar banane ke liye kya scheme hai", "housing_basics"),
    ("scholarship kaise milegi", "scholarship_basics"),
    ("मेरे पास कोई दस्तावेज़ नहीं है", "no_documents_at_all"),
])
def test_knowledge_retrieval_finds_the_right_article(query, expected_id):
    from app.agents.knowledge import search_knowledge
    hits = search_knowledge(query, limit=3)
    assert hits, f"no knowledge retrieved for {query!r}"
    assert expected_id in [h["id"] for h in hits], (
        f"{query!r} retrieved {[h['id'] for h in hits]}, expected {expected_id}"
    )


def test_offline_answers_are_real_answers_not_menus():
    """No API key in CI — every answer below must still be genuinely useful."""
    from app.agents.knowledge import compose_offline_answer
    from app.engine.matcher import load_schemes
    schemes = load_schemes()

    ans = compose_offline_answer("mere paas aadhaar card nahi hai", "en", schemes)
    assert ans and "Aadhaar Seva Kendra" in ans and "free" in ans.lower()

    ans_hi = compose_offline_answer("आधार कार्ड नहीं है", "hi", schemes)
    assert ans_hi and "आधार सेवा केंद्र" in ans_hi

    # a scheme-specific question is answered from the scheme record
    ans_scheme = compose_offline_answer("sukanya samriddhi me kitna interest hai", "en", schemes)
    assert ans_scheme and "Sukanya" in ans_scheme and "₹" in ans_scheme


def test_intent_classifier_routes_each_kind_of_turn():
    from app.agents import conversation as convo
    q = intake_mod.get_question("is_bpl")
    profile = {"language": "en", "annual_income": 80000, "age": 40}

    assert convo.classify("Yes", q, profile, False) == "answer"
    assert convo.classify("skip", q, profile, False) == "skip"
    assert convo.classify("thanks bhai", q, profile, False) == "smalltalk"
    assert convo.classify("help", q, profile, False) == "help"
    assert convo.classify("BPL kya hai?", q, profile, False) == "question"
    assert convo.classify("mere paas aadhaar card nahi hai", q, profile, False) == "question"
    assert convo.classify("actually meri income 2 lakh hai", q, profile, False) == "correction"
    assert convo.classify("restart", q, profile, False) == "restart"


def test_off_topic_question_mid_intake_answers_and_resumes():
    """The headline fix: a real question mid-form gets a real answer, and the
    pending question comes back untouched — no state lost, no parse error."""
    from app.graph.main_graph import process_message

    profile = {"language": "en", "name": "Ramesh", "age": 45, "gender": "male",
               "state": "UP", "area_type": "rural", "occupation": "farmer"}
    state = process_message(profile, "mere paas aadhaar card nahi hai, kya karu?",
                            "annual_income", False, None)
    blob = " ".join(state["bot_messages"])

    assert "Aadhaar Seva Kendra" in blob                 # a genuine answer
    assert "CSC" in blob and "free" in blob.lower()      # with actionable detail
    assert state["next_qid"] == "annual_income"          # same question re-asked
    assert "annual_income" not in profile                # nothing wrongly stored
    assert state["quick_replies"]                        # its options still shown


def test_question_about_current_field_uses_curated_help():
    """'BPL kya hai?' while ON the BPL question keeps the question-specific
    explanation rather than a generic knowledge article."""
    from app.graph.main_graph import process_message

    profile = {"language": "en", "annual_income": 80000, "age": 45}
    state = process_message(profile, "BPL kya hai?", "is_bpl", False, None)
    blob = " ".join(state["bot_messages"])
    assert "Below Poverty Line" in blob and "RATION CARD" in blob.upper()
    assert state["next_qid"] == "is_bpl"


def test_user_can_skip_a_question():
    from app.graph.main_graph import process_message

    profile = {"language": "en", "annual_income": 80000, "age": 45, "occupation": "farmer"}
    state = process_message(profile, "rehne do", "is_bpl", False, None)
    assert state["next_qid"] != "is_bpl"                 # moved on
    assert "is_bpl" not in profile                       # not answered
    assert "is_bpl" in intake_mod.skipped_fields(profile)
    # and a skipped question is never asked again
    assert "is_bpl" not in intake_mod.pending_question_ids(profile)


def test_user_can_correct_an_earlier_answer_mid_intake():
    from app.graph.main_graph import process_message

    profile = {"language": "en", "name": "Amit", "age": 28, "gender": "male",
               "state": "Delhi", "area_type": "urban", "occupation": "business",
               "education_level": "graduate", "annual_income": 375000}
    state = process_message(profile, "actually meri income 2 lakh hai", "category", False, None)
    assert profile["annual_income"] == 200000
    blob = " ".join(state["bot_messages"])
    assert "2,00,000" in blob                            # confirms in Indian format
    assert state["next_qid"]                             # flow continues


def test_correction_after_report_rebuilds_it():
    """Correcting a fact post-report must regenerate the report, not just chat."""
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/priya").json()["session_id"]

    before = client.get(f"/api/report/{sid}").json()
    r = client.post("/api/chat", json={
        "session_id": sid, "message": "sorry meri category actually SC hai"
    }).json()
    after = client.get(f"/api/report/{sid}").json()

    assert after["profile"]["category"] == "sc"
    before_ids = {c["scheme_id"] for c in before["eligible"]}
    after_ids = {c["scheme_id"] for c in after["eligible"]}
    assert "postmatric_sc" in after_ids and "postmatric_sc" not in before_ids
    assert "postmatric_obc" not in after_ids              # she is no longer OBC
    assert r["messages"]


def test_followup_answers_general_questions_not_just_the_menu():
    """Post-report, an unrelated-but-real question must get a real answer."""
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/amit").json()["session_id"]

    r = client.post("/api/chat", json={"session_id": sid, "message": "CSC kya hota hai"}).json()
    ans = " ".join(r["messages"])
    assert "Common Service Centre" in ans or "Jan Seva Kendra" in ans
    assert "report is ready" not in ans.lower()          # NOT the generic menu

    r2 = client.post("/api/chat", json={"session_id": sid, "message": "koi dalal paisa mangta hai kya"}).json()
    ans2 = " ".join(r2["messages"])
    assert "FREE" in ans2.upper() and ("agent" in ans2.lower() or "middleman" in ans2.lower())


def test_assistant_admits_when_it_does_not_know():
    """Honesty guard: never invent a scheme rule for an unknown question."""
    from app.agents.conversation import unknown_reply
    from app.agents.knowledge import compose_offline_answer
    from app.engine.matcher import load_schemes

    assert compose_offline_answer("what is the ipl score today", "en", load_schemes()) is None
    for lang in ("en", "hi"):
        msg = unknown_reply(lang)
        assert "myscheme.gov.in" in msg
        assert ("don't have" in msg.lower() or "नहीं है" in msg)


# ---------------------------------------------------------------------------
# KEY FEATURE 7 (compulsory) — required-documents checklist
# ---------------------------------------------------------------------------


def test_every_scheme_ships_a_documents_list():
    """The compulsory add-on at the data layer: documents are a scheme field."""
    for s in load_schemes():
        assert s.get("documents_en"), f"{s['id']} has no documents_en"
        assert s.get("documents_hi"), f"{s['id']} has no documents_hi"
        assert len(s["documents_en"]) >= 2, f"{s['id']} documents list is too thin"
        assert len(s["documents_en"]) == len(s["documents_hi"]), (
            f"{s['id']} EN/HI document lists are out of sync"
        )


def test_report_embeds_a_consolidated_checklist():
    _, report, _, _ = _run("ramesh")
    cl = report["documents_checklist"]
    assert cl["n_documents"] > 0
    keys = [d["key"] for d in cl["items"]]
    assert "aadhaar" in keys and "bank" in keys
    assert "land" in keys                                 # farmer-specific doc present
    # the most widely needed document must be ranked first
    assert cl["items"][0]["n_schemes"] >= cl["items"][-1]["n_schemes"]


def test_checklist_deduplicates_and_attributes_documents():
    _, report, _, _ = _run("sunita")
    cl = report["documents_checklist"]
    keys = [d["key"] for d in cl["items"]]
    assert len(keys) == len(set(keys)), "the same document must appear only once"

    aadhaar = next(d for d in cl["items"] if d["key"] == "aadhaar")
    matched = len(report["eligible"]) + len(report["near_miss"])
    assert aadhaar["n_schemes"] == matched and aadhaar["universal"]
    # every attribution points at a real matched scheme
    matched_ids = {c["scheme_id"] for c in report["eligible"] + report["near_miss"]}
    for d in cl["items"]:
        for s in d["schemes"]:
            assert s["scheme_id"] in matched_ids


def test_checklist_tells_you_how_to_get_a_missing_document():
    _, report, _, _ = _run("sunita")
    cl = report["documents_checklist"]
    bank = next(d for d in cl["items"] if d["key"] == "bank")
    assert "Jan Dhan" in bank["how_to_en"]                 # actionable, not just a name
    assert "जन धन" in bank["how_to_hi"]
    covered = [d for d in cl["items"] if d["how_to_en"]]
    assert len(covered) >= 5, "most common documents should carry how-to guidance"


def test_checklist_flags_near_miss_only_documents():
    """Documents needed only by near-miss schemes are marked, so a user knows
    what is optional right now."""
    _, report, _, _ = _run("sunita")
    cl = report["documents_checklist"]
    near_ids = {c["scheme_id"] for c in report["near_miss"]}
    for d in cl["items"]:
        if d["near_miss_only"]:
            assert all(s["scheme_id"] in near_ids for s in d["schemes"])
    # and they are sorted to the bottom
    flags = [d["near_miss_only"] for d in cl["items"]]
    assert flags == sorted(flags), "near-miss-only documents must come last"


def test_checklist_endpoint_and_chat_and_print_all_expose_it():
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/ramesh").json()["session_id"]

    # 1. dedicated API
    cl = client.get(f"/api/report/{sid}/documents").json()
    assert cl["n_documents"] > 0 and cl["items"][0]["label_en"]

    # 2. in chat
    r = client.post("/api/chat", json={"session_id": sid, "message": "documents"}).json()
    ans = " ".join(r["messages"])
    assert "आधार कार्ड" in ans or "Aadhaar" in ans
    assert "📄" in ans

    # 3. in the printable report
    html = client.get(f"/api/report/{sid}/html?lang=hi").text
    assert "doc-checklist" in html and "☐" in html         # tickable boxes
    assert "आधार कार्ड" in html


def test_user_can_restart_the_conversation_by_typing():
    from app.graph.main_graph import process_message

    profile = {"language": "hi", "name": "रमेश", "age": 45, "occupation": "farmer"}
    state = process_message(profile, "shuru se karo", "annual_income", False, None)
    assert profile.get("name") is None                    # wiped
    assert profile.get("language") == "hi"                # language remembered
    assert state["next_qid"] == "name"                    # back to question one


def test_romanized_free_text_answers_are_understood():
    """People type 'kisan' and 'gaon', they don't always tap the chip."""
    assert intake_mod.parse_answer(intake_mod.get_question("occupation"), "kisan") == (True, "farmer")
    assert intake_mod.parse_answer(intake_mod.get_question("area_type"), "gaon") == (True, "rural")
    assert intake_mod.parse_answer(intake_mod.get_question("area_type"), "sheher") == (True, "urban")
    assert intake_mod.parse_answer(intake_mod.get_question("gender"), "aurat") == (True, "female")
    assert intake_mod.parse_answer(intake_mod.get_question("occupation"), "grihini") == (True, "homemaker")
    # a guess that doesn't fit this question's options is rejected, not forced
    assert intake_mod.parse_answer(intake_mod.get_question("area_type"), "kisan") == (False, None)


def test_chip_labels_are_never_mistaken_for_doubts_or_chitchat():
    """Regression: 'Willing to join a women's Self-Help Group' contains the word
    'Help' and used to be routed to the help system instead of being stored."""
    from app.agents import conversation as convo
    from app.agents.prompts import QUESTIONS

    profile = {"age": 30, "gender": "female", "area_type": "rural",
               "occupation": "farmer", "annual_income": 80000, "name": "X", "language": "en"}
    checked = 0
    for q in QUESTIONS:
        if q.get("ask_if") and not q["ask_if"](profile):
            continue
        for lang in ("en", "hi"):
            for opt in intake_mod.render_options(q, lang, profile):
                intent = convo.classify(str(opt["label"]), q, profile, False)
                assert intent == "answer", (
                    f"chip '{opt['label']}' on '{q['id']}' routed to '{intent}' instead of being answered"
                )
                checked += 1
    assert checked > 50


def test_rebuilt_report_is_pushed_to_the_client():
    """Regression: after a correction the report is regenerated server-side, so
    it must be sent down again — otherwise the UI keeps showing stale results."""
    TestClient = pytest.importorskip("fastapi.testclient", reason="no fastapi").TestClient
    from app.main import app
    client = TestClient(app)
    sid = client.post("/api/demo/priya").json()["session_id"]

    # a plain follow-up must NOT resend the report (keeps the user in chat)
    plain = client.post("/api/chat", json={"session_id": sid, "message": "apply kaise kare"}).json()
    assert plain["report"] is None

    # a correction that rebuilds it MUST resend it
    fixed = client.post("/api/chat", json={
        "session_id": sid, "message": "sorry meri category actually SC hai"
    }).json()
    assert fixed["report"] is not None
    assert {c["scheme_id"] for c in fixed["report"]["eligible"]} >= {"postmatric_sc"}
    assert fixed["report"]["documents_checklist"]["n_documents"] > 0

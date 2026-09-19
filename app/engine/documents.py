"""
KEY FEATURE 7 — required-documents checklist (compulsory add-on).

Every scheme in data/schemes.json carries `documents_en` / `documents_hi`, and
each matched scheme's card renders its own list. This module adds the layer
that actually helps a citizen standing in a queue: ONE consolidated,
deduplicated master checklist across all their matched schemes.

For each document it answers three questions:
  · which of MY schemes need it            (`schemes`, `n_schemes`)
  · is it needed for everything or just one (`universal`)
  · I don't have it — how do I get one?     (`how_to_en` / `how_to_hi`)

Near-miss schemes are included but flagged, so an NGO worker collecting papers
for a beneficiary gathers everything in a single trip instead of coming back
once the income certificate finally arrives.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Canonicalisation — the same document is worded differently across schemes
# ("Aadhaar Card", "Aadhaar card (mandatory)", "आधार कार्ड") but a citizen
# only has to carry it once.
# ---------------------------------------------------------------------------

_CANON: list[tuple[tuple[str, ...], str, str, str]] = [
    # (match substrings, canonical key, label_en, label_hi)
    (("aadhaar", "aadhar", "आधार"), "aadhaar", "Aadhaar Card", "आधार कार्ड"),
    (("bank account", "bank passbook", "passbook", "bank detail", "बैंक", "पासबुक"),
     "bank", "Bank account passbook", "बैंक खाता पासबुक"),
    (("land ownership", "land record", "khatauni", "khasra", "7/12", "भूमि", "खतौनी", "खसरा"),
     "land", "Land records (Khatauni / Khasra)", "भूमि रिकॉर्ड (खतौनी / खसरा)"),
    (("ration card", "राशन कार्ड"), "ration", "Ration card", "राशन कार्ड"),
    (("income certificate", "income proof", "आय प्रमाण"),
     "income", "Income certificate", "आय प्रमाण पत्र"),
    (("caste certificate", "caste proof", "जाति प्रमाण"),
     "caste", "Caste certificate (SC/ST/OBC)", "जाति प्रमाण पत्र (एससी/एसटी/ओबीसी)"),
    (("photograph", "photo", "फोटो"), "photo", "Passport-size photographs", "पासपोर्ट साइज़ फोटो"),
    (("mobile", "मोबाइल"), "mobile", "Mobile number linked with Aadhaar", "आधार से जुड़ा मोबाइल नंबर"),
    (("bpl", "secc", "बीपीएल", "एसईसीसी"), "bpl", "BPL / SECC proof", "बीपीएल / SECC प्रमाण"),
    (("project report", "business plan", "प्रोजेक्ट रिपोर्ट", "व्यवसाय योजना"),
     "project", "Business project report", "व्यवसाय प्रोजेक्ट रिपोर्ट"),
    (("udyam", "उद्यम"), "udyam", "Udyam / MSME registration", "उद्यम / एमएसएमई पंजीकरण"),
    (("gst", "जीएसटी"), "gst", "GST registration (if applicable)", "जीएसटी पंजीकरण (यदि लागू)"),
    (("pan", "पैन"), "pan", "PAN card", "पैन कार्ड"),
    (("marksheet", "mark sheet", "अंकतालिका", "मार्कशीट"),
     "marksheet", "Previous year's marksheet", "पिछले वर्ष की मार्कशीट"),
    (("bonafide", "institution certificate", "बोनाफाइड", "संस्थान प्रमाण"),
     "bonafide", "Bonafide certificate from institution", "संस्थान का बोनाफाइड प्रमाण पत्र"),
    (("birth certificate", "जन्म प्रमाण"), "birth", "Birth certificate", "जन्म प्रमाण पत्र"),
    (("address proof", "residence", "domicile", "निवास", "पता प्रमाण"),
     "address", "Address / domicile proof", "निवास / पता प्रमाण"),
    (("disability", "दिव्यांग"), "disability", "Disability certificate", "दिव्यांगता प्रमाण पत्र"),
    (("mgnrega", "job card", "जॉब कार्ड", "मनरेगा"), "jobcard", "MGNREGA job card", "मनरेगा जॉब कार्ड"),
    (("electricity", "बिजली"), "electricity", "Electricity bill / connection proof", "बिजली बिल / कनेक्शन प्रमाण"),
    (("self declaration", "self-declaration", "स्व-घोषणा", "स्व घोषणा"),
     "declaration", "Self-declaration form", "स्व-घोषणा पत्र"),
    (("pregnancy", "mcp card", "गर्भ", "एमसीपी"), "mcp", "MCP card / pregnancy registration", "एमसीपी कार्ड / गर्भावस्था पंजीकरण"),
]

# "I don't have this" → the exact next step. Mirrors data/knowledge.json.
_HOW_TO: dict[str, tuple[str, str]] = {
    "aadhaar": (
        "Free at any Aadhaar Seva Kendra / CSC / post office — carry any ID + address proof; "
        "the enrolment slip (EID) works meanwhile.",
        "किसी भी आधार सेवा केंद्र / CSC / डाकघर पर मुफ्त — कोई पहचान + पता प्रमाण ले जाइए; "
        "तब तक नामांकन पर्ची (EID) काम आती है।",
    ),
    "bank": (
        "No account? Open a zero-balance Jan Dhan account at any bank or Bank Mitra with Aadhaar — same day.",
        "खाता नहीं? आधार लेकर किसी भी बैंक या बैंक मित्र के पास ज़ीरो-बैलेंस जन धन खाता खुलवाइए — उसी दिन।",
    ),
    "land": (
        "Download free from your state land portal (upbhulekh / mpbhulekh / mahabhumi) or ₹10–₹30 at the Patwari office.",
        "अपने राज्य के भू-अभिलेख पोर्टल (upbhulekh / mpbhulekh / mahabhumi) से मुफ्त डाउनलोड करें या पटवारी कार्यालय से ₹10–₹30 में।",
    ),
    "ration": (
        "Apply at your state Food & Civil Supplies portal or the Block Supply Office — ₹5–₹45, about 15–30 days.",
        "अपने राज्य के खाद्य एवं रसद पोर्टल या ब्लॉक आपूर्ति कार्यालय में आवेदन करें — ₹5–₹45, लगभग 15–30 दिन।",
    ),
    "income": (
        "Tehsildar / SDM office or the state e-District portal — ₹10–₹50, 3–7 days. Valid one financial year, so renew if old.",
        "तहसीलदार / SDM कार्यालय या राज्य के e-District पोर्टल से — ₹10–₹50, 3–7 दिन। एक वित्तीय वर्ष मान्य, पुराना हो तो नया बनवाएँ।",
    ),
    "caste": (
        "Tehsildar / SDM office or state e-District portal — 7–21 days. OBC applicants also need a Non-Creamy-Layer certificate.",
        "तहसीलदार / SDM कार्यालय या राज्य e-District पोर्टल — 7–21 दिन। OBC वालों को नॉन-क्रीमी-लेयर प्रमाण पत्र भी चाहिए।",
    ),
    "bpl": (
        "Your ration card (BPL / Antyodaya / PHH) is the proof; the Gram Panchayat or CSC can check the SECC-2011 list.",
        "आपका राशन कार्ड (BPL / अंत्योदय / PHH) ही प्रमाण है; ग्राम पंचायत या CSC SECC-2011 सूची जाँच सकता है।",
    ),
    "project": (
        "A one-page plan is enough: what you'll make/sell, machinery cost, and expected monthly sales. CSC or the bank can help draft it.",
        "एक पन्ने की योजना काफी है: क्या बनाएँगे/बेचेंगे, मशीन की लागत, और अनुमानित मासिक बिक्री। CSC या बैंक बनाने में मदद कर देता है।",
    ),
    "udyam": ("Free and instant at udyamregistration.gov.in with just Aadhaar + PAN.",
              "udyamregistration.gov.in पर सिर्फ आधार + पैन से मुफ्त और तुरंत।"),
    "pan": ("Apply online at onlineservices.nsdl.com or a CSC — about ₹107, 7–15 days.",
            "onlineservices.nsdl.com या CSC से ऑनलाइन आवेदन — लगभग ₹107, 7–15 दिन।"),
    "bonafide": ("Ask your school/college office — usually issued the same week, free or nominal.",
                 "अपने स्कूल/कॉलेज कार्यालय में माँगिए — आम तौर पर उसी सप्ताह, मुफ्त या मामूली शुल्क।"),
    "address": ("Ration card, electricity bill, voter ID or bank passbook all count as address proof.",
                "राशन कार्ड, बिजली बिल, वोटर आईडी या बैंक पासबुक — सब पता प्रमाण के रूप में चलते हैं।"),
    "mobile": ("Link your number to Aadhaar free at any Aadhaar Seva Kendra — OTPs for every portal need it.",
               "किसी भी आधार सेवा केंद्र पर अपना नंबर आधार से मुफ्त जोड़वाइए — हर पोर्टल के OTP के लिए यही चाहिए।"),
    "photo": ("Any photo studio or CSC — keep 4–6 passport-size copies handy.",
              "कोई भी फोटो स्टूडियो या CSC — 4–6 पासपोर्ट साइज़ कॉपी पास रखिए।"),
    "disability": ("Issued by the district hospital medical board; apply via swavlambancard.gov.in.",
                   "ज़िला अस्पताल के मेडिकल बोर्ड से बनता है; swavlambancard.gov.in पर आवेदन कीजिए।"),
    "jobcard": ("Apply at the Gram Panchayat — a job card is issued within about 15 days, free.",
                "ग्राम पंचायत में आवेदन कीजिए — जॉब कार्ड लगभग 15 दिन में, मुफ्त बन जाता है।"),
    "marksheet": ("Lost it? Your school/college or board website issues a duplicate for a small fee.",
                  "खो गई? आपका स्कूल/कॉलेज या बोर्ड की वेबसाइट मामूली शुल्क पर डुप्लिकेट देती है।"),
    "birth": ("Municipal office / Gram Panchayat registrar, or your state's civil registration portal.",
              "नगर निगम / ग्राम पंचायत रजिस्ट्रार, या अपने राज्य के जन्म-मृत्यु पंजीकरण पोर्टल से।"),
    "mcp": ("Given free at your Anganwadi centre or government hospital at the first ANC check-up.",
            "पहली प्रसव-पूर्व जाँच पर आपके आंगनवाड़ी केंद्र या सरकारी अस्पताल में मुफ्त मिलता है।"),
}


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKC", (text or "")).lower()
    t = re.sub(r"\(.*?\)", " ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\u0900-\u097F/]", " ", t)).strip()


def canonical_key(doc_en: str) -> tuple[str, str, str]:
    """Map a raw scheme document string to (key, label_en, label_hi).

    Unknown documents keep their own wording — better a slightly duplicated
    entry than silently dropping something a department will ask for.
    """
    s = _slug(doc_en)
    for needles, key, label_en, label_hi in _CANON:
        if any(n in s for n in needles):
            return key, label_en, label_hi
    return "other:" + s, doc_en.strip(), doc_en.strip()


def build_checklist(report: dict) -> list[dict]:
    """Consolidated, deduplicated document checklist for a whole report.

    Sorted by how many schemes need the document (most-needed first), so the
    top of the list is exactly what to collect first.
    """
    cards = list(report.get("eligible") or []) + list(report.get("near_miss") or [])
    if not cards:
        return []

    n_eligible = len(report.get("eligible") or [])
    merged: dict[str, dict] = {}

    for idx, card in enumerate(cards):
        is_near = idx >= n_eligible
        docs_en = card.get("documents_en") or []
        docs_hi = card.get("documents_hi") or []
        for i, doc_en in enumerate(docs_en):
            doc_hi = docs_hi[i] if i < len(docs_hi) else doc_en
            key, label_en, label_hi = canonical_key(doc_en)
            entry = merged.setdefault(key, {
                "key": key,
                "label_en": label_en,
                "label_hi": label_hi if not key.startswith("other:") else doc_hi,
                "schemes": [],
                "near_miss_only": True,
                "how_to_en": _HOW_TO.get(key, ("", ""))[0],
                "how_to_hi": _HOW_TO.get(key, ("", ""))[1],
            })
            if not is_near:
                entry["near_miss_only"] = False
            entry["schemes"].append({
                "scheme_id": card["scheme_id"],
                "name_en": card["name_en"].split(" (")[0],
                "name_hi": card["name_hi"].split(" (")[0],
                "near_miss": is_near,
            })

    checklist = []
    total_schemes = len(cards)
    for entry in merged.values():
        entry["n_schemes"] = len(entry["schemes"])
        entry["universal"] = entry["n_schemes"] == total_schemes and total_schemes > 1
        checklist.append(entry)

    checklist.sort(key=lambda d: (d["near_miss_only"], -d["n_schemes"], d["label_en"]))
    return checklist


def checklist_summary(report: dict) -> dict:
    """Checklist plus the headline numbers the UI and the report print out."""
    items = build_checklist(report)
    return {
        "items": items,
        "n_documents": len(items),
        "n_core": sum(1 for d in items if not d["near_miss_only"]),
        "core_four": [d["key"] for d in items[:4]],
    }

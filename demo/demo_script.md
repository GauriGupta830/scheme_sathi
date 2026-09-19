# 🎬 Scheme Saathi — demo script

**Total run time: 4 minutes.** Everything below works with the Wi-Fi unplugged —
unplug it before you start and say so out loud. That single move answers the
"what if your API dies on stage" question before anyone asks it.

---

## 0. Setup (before you present)

```bash
python run.py          # → http://localhost:8000
```

Open the app, press **⟳ New session**, and leave it on the chat view.
Have this file open on a second screen or printed.

---

## 1. The problem (20 seconds — say it, don't slide it)

> "India runs 700+ schemes. A farmer in UP is *entitled* to six of them right now and
> knows about one. Not because he's careless — because eligibility is buried in PDFs
> across a dozen portals. So the middleman becomes the interface, and takes a cut of
> a benefit that was free."

---

## 2. Ramesh — run this one **in Hindi** (90 seconds)

Tap through the quick replies. Speak while you tap; don't read the screen aloud.

| Question | Tap / type |
|---|---|
| Language | **हिंदी (Hindi)** |
| नाम | `रमेश कुमार` |
| उम्र | **46–60** |
| लिंग | **पुरुष** |
| राज्य | **उत्तर प्रदेश** |
| क्षेत्र | **ग्रामीण (गाँव)** |
| पेशा | **🌾 किसान** |

> Point at the sidebar: *"the profile is building live, and notice it just decided to
> ask about land — a student would never see that question."*

### 🔴 Moment 1 — the doubt (do NOT skip this)

The BPL question appears. **Type instead of tapping:**

```
BPL kya hai?
```

> "He's stuck. A form would throw a validation error. Watch."

It explains BPL in plain Hindi — ration card, Antyodaya, the SECC list, and what to do
if he still can't tell — then re-asks the same question. **Progress bar hasn't moved.**

Now answer: **हाँ**

### 🔴 Moment 2 — an actual conversation

On the next question, type:

```
mere paas aadhaar card nahi hai
```

> "This has nothing to do with the question on screen. It's what a real person
> actually says."

It answers properly: any Aadhaar Seva Kendra or CSC, free, 15–30 days, carry any one
ID + one address proof, sarpanch certificate if you have neither, and the EID slip
works in the meantime — **then returns to the intake question**.

> "That's retrieved from a curated corpus and — with a key — rewritten by Gemini,
> which is forbidden from adding any fact that isn't in the retrieved text. Right now
> there's no key and no internet. Same answer."

Finish the remaining questions: land **1 – 2 हे.** · pucca house **नहीं** · bank **हाँ** ·
category **एससी** · special **कोई नहीं**.

---

## 3. The report (60 seconds)

The report view opens with confetti. Three things, in this order:

1. **Ranked eligible cards** — open the #1 card. *"Every green line is a rule the
   engine evaluated, not an LLM opinion. PM-KISAN because: farmer ✓, owns 1.5 ha ✓."*
2. **Near-miss (amber)** — *"MUDRA isn't a no, it's a 'not yet' — and it tells him
   exactly what would change it. No other team will show you this."*
3. 🔴 **Documents to collect** — scroll to the blue section. **This is Key Feature 7.**
   > "Not one list per scheme — **one list for the human being**. Aadhaar: needed for
   > ALL nine of his schemes. Land records: needed by three, and it names them. And
   > under every document he might not have — exactly where to go, what to carry,
   > what it costs."

Hit **Print / Save PDF** → the checklist prints with **☐ checkboxes**.

> "An NGO field worker prints this, hands it to him, and ticks boxes as papers come in."

---

## 4. Amit — the precise gap (40 seconds)

Sidebar → **New session** → run the **Amit** persona quick-demo (or tap through:
28 · Male · Delhi · Urban · Business · Graduate · ₹2.5–5L · General · just an idea ·
Services · pucca No · bank Yes · None).

Open the **PMAY-Urban** near-miss card:

> "₹3,75,000 against a ₹3,00,000 ceiling — **₹75,000 over**. Computed, not guessed.
> And it points him at the LIG slab where he *does* qualify."

Then in chat, type:

```
actually meri income 2 lakh hai
```

> "He mis-tapped. No restart, no re-doing twelve questions — it corrects that one
> answer and rebuilds the report."

---

## 5. Close (20 seconds)

> "Deterministic rule engine for the verdict — every result traceable to a rule.
> Retrieval for the conversation — grounded, so it can't invent a scheme rule.
> The LLM is a tone layer: it makes it warm, it never makes it wrong.
> Hindi-first, works offline, and it ends with a checklist that turns eligibility
> into something a person can actually act on tomorrow morning."

---

## 🆘 If something goes wrong

| Problem | Do this |
|---|---|
| Chat feels stuck | Sidebar → **New session**. Sessions are in-memory; nothing to clean up. |
| You mistype mid-demo | Just type the correction in plain words — it's a feature, demo it. |
| Laptop has no internet | **Good.** Say so. Everything in this script works offline. |
| Report view looks empty | Click **Eligibility Report** in the sidebar. |
| Total emergency | `POST /api/demo/ramesh` (or priya / amit / sunita) returns the full transcript + report instantly. |

---

## 📋 Quick persona cheat-cards

| Persona | Answers | Headline |
|---|---|---|
| 🌾 **Ramesh** (Hindi) | 45 · पुरुष · ग्रामीण UP · किसान · ₹1–2.5L · एससी · BPL हाँ · 1–2 हे. · पक्का नहीं · बैंक हाँ | PM-KISAN, Fasal Bima, KUSUM, PMAY-G, Ayushman, **Stand-Up India (SC!)** ✅ · MUDRA & APY near-miss |
| 🎓 **Priya** | 20 · Female · Urban MH · Student · 12th · ₹1–2.5L · OBC · BPL No · pucca Yes · bank Yes | NSP + Post-Matric OBC ✅ · Ayushman near-miss |
| 💼 **Amit** | 28 · Male · Delhi · Urban · Business · Graduate · ₹2.5–5L · General · idea · services · pucca No · bank Yes | MUDRA + PMEGP + CGTMSE + Seed Fund ✅ · **PMAY-U gap ₹75,000 exactly** |
| 👩‍👧 **Sunita** | 35 · Female · Rural MP · गृहिणी · <₹1L · ST · BPL हाँ · pucca No · bank **No** · daughter + SHG | 6 schemes ✅ incl. **Jan Dhan** · insurance/pension near-misses **pointing back to Jan Dhan** |

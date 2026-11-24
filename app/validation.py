import re
from datetime import date, datetime

from rapidfuzz import fuzz

from .policies import DOC_HINTS, DOC_LABELS, POLICIES
from .schemas import Bill

NAME_MATCH_THRESHOLD = 95
_HONORIFICS = {"mr", "mrs", "ms", "smt", "shri", "sh", "dr", "late"}


def _norm_name(s: str) -> str:
    # Only strip punctuation (NOT \W - that would destroy Devanagari vowel signs).
    s = re.sub(r"[.,'\-_()]", " ", (s or "").lower())
    return " ".join(w for w in s.split() if w not in _HONORIFICS)


def _d(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def validate_claim(policy_id: str, bill: Bill, documents_provided: list[str], holder_name: str,
                   today: date | None = None) -> dict:
    policy = POLICIES.get(policy_id)
    if not policy:
        raise ValueError(f"Unknown policy_id '{policy_id}'")
    today = today or date.today()
    issues: list[dict] = []

    def add(type_, en, hi, adv_en, adv_hi, penalty):
        issues.append(dict(type=type_, en=en, hi=hi, adv_en=adv_en, adv_hi=adv_hi, penalty=penalty))

    # ---- documents ----
    provided = {str(d).strip().lower() for d in documents_provided if d}
    documents = []
    for did in policy["required_documents"]:
        en, hi = DOC_LABELS[did]
        ok = did in provided
        documents.append({"name": en, "status": "provided" if ok else "missing"})
        if not ok:
            hint_en, hint_hi = DOC_HINTS.get(did, (f"Collect the {en} and upload it before submitting.",
                                                  f"जमा करने से पहले {hi} प्राप्त करें और अपलोड करें।"))
            add("missing_document",
                f"{en} is missing. Claims without it are often delayed or rejected.",
                f"{hi} नहीं मिला। इसके बिना क्लेम अक्सर देर से या अस्वीकृत होते हैं।",
                hint_en, hint_hi, 20)

    # ---- amounts ----
    items = bill.items
    items_total = round(sum(i.amount for i in items), 2)
    gross = bill.total_amount if bill.total_amount > 0 else items_total

    non_covered_items = []
    for it in items:
        for pattern, reason in policy["rules"]:
            if pattern.search(it.name):
                non_covered_items.append({"name": it.name, "amount": round(it.amount, 2), "reason": reason})
                break
    excluded_sum = round(sum(i["amount"] for i in non_covered_items), 2)
    if non_covered_items:
        add("excluded_items",
            f"{len(non_covered_items)} item(s) worth ₹{excluded_sum:,.0f} are not covered by this policy.",
            f"{len(non_covered_items)} मद (₹{excluded_sum:,.0f}) इस पॉलिसी में कवर नहीं हैं।",
            "These charges will be deducted. You can still claim the covered amount.",
            "ये शुल्क कटेंगे। आप कवर की गई राशि का क्लेम फिर भी कर सकते हैं।", 10)

    eligible = max(gross - excluded_sum, 0.0)
    limit = policy["coverage_limit"]
    covered = eligible
    if eligible > limit:
        excess = round(eligible - limit, 2)
        covered = float(limit)
        non_covered_items.append({"name": "Amount above sum insured limit", "amount": excess,
                                  "reason": f"Payout is capped at the sum insured of ₹{limit:,.0f}"})
        add("limit_exceeded",
            f"Eligible amount exceeds the sum insured; payout is capped at ₹{limit:,.0f}.",
            f"योग्य राशि बीमा राशि से अधिक है; भुगतान ₹{limit:,.0f} तक सीमित रहेगा।",
            "Keep all bills safe; the payout cannot exceed the sum insured.",
            "सभी बिल संभालकर रखें; भुगतान बीमा राशि से अधिक नहीं हो सकता।", 5)

    non_covered_amount = round(sum(i["amount"] for i in non_covered_items), 2)

    if items and bill.total_amount > 0 and abs(items_total - bill.total_amount) > max(1.0, 0.01 * bill.total_amount):
        add("total_mismatch",
            f"Total on the bill (₹{bill.total_amount:,.0f}) does not match the sum of items (₹{items_total:,.0f}).",
            f"बिल का कुल (₹{bill.total_amount:,.0f}) मदों के जोड़ (₹{items_total:,.0f}) से मेल नहीं खाता।",
            "Check for missed or misread items, or ask the hospital for an itemised bill.",
            "छूटी या गलत पढ़ी गई मदें जाँचें, या अस्पताल से मदवार बिल मांगें।", 10)

    # ---- identity ----
    if holder_name.strip() and bill.patient_name.strip():
        score = fuzz.token_sort_ratio(_norm_name(holder_name), _norm_name(bill.patient_name))
        if score < NAME_MATCH_THRESHOLD:
            add("name_mismatch",
                f"Patient name on the bill ('{bill.patient_name}') does not match the policy holder ('{holder_name}').",
                f"बिल पर मरीज का नाम ('{bill.patient_name}') पॉलिसीधारक ('{holder_name}') से मेल नहीं खाता।",
                "Ask the hospital to correct the name on the bill, or attach proof of relationship (e.g. ration card or Aadhaar).",
                "अस्पताल से बिल पर नाम सुधरवाएं, या संबंध का प्रमाण (जैसे राशन कार्ड/आधार) लगाएं।", 20)

    # ---- completeness / dates ----
    if not bill.patient_name.strip() or (gross <= 0) or not (bill.admission_date or bill.discharge_date):
        add("incomplete_bill",
            "Some key details (patient name, dates or amount) could not be read from the bill.",
            "बिल से कुछ ज़रूरी जानकारी (मरीज का नाम, तारीख या राशि) पढ़ी नहीं जा सकी।",
            "Upload a clearer photo or fill in the missing details by hand.",
            "साफ़ फोटो अपलोड करें या छूटी जानकारी हाथ से भरें।", 15)

    adm, dis = _d(bill.admission_date), _d(bill.discharge_date)
    if (adm and dis and dis < adm) or (adm and adm > today) or (dis and dis > today):
        add("date_invalid",
            "The admission/discharge dates on the bill look incorrect.",
            "बिल पर भर्ती/डिस्चार्ज की तारीखें गलत लग रही हैं।",
            "Verify the dates against the hospital's records.",
            "अस्पताल के रिकॉर्ड से तारीखें जाँच लें।", 10)
    else:
        ref = dis or adm
        if ref:
            days_since = (today - ref).days
            left = policy["deadline_days"] - days_since
            if left < 0:
                add("deadline_passed",
                    f"The {policy['deadline_days']}-day claim window after discharge has passed ({days_since} days ago).",
                    f"डिस्चार्ज के बाद {policy['deadline_days']} दिन की क्लेम अवधि बीत चुकी है ({days_since} दिन पहले)।",
                    "Submit anyway with a written reason for the delay; the insurer may still consider it.",
                    "देरी का कारण लिखकर फिर भी जमा करें; बीमा कंपनी फिर भी विचार कर सकती है।", 25)
            elif left <= 5:
                add("deadline_near",
                    f"Only {left} day(s) left to file this claim.",
                    f"क्लेम दाखिल करने के लिए सिर्फ़ {left} दिन बचे हैं।",
                    "Submit your claim today.", "अपना क्लेम आज ही जमा करें।", 5)

    if bill.confidence is not None and bill.confidence < 0.6:
        add("low_confidence",
            "Automatic reading of the bill had low confidence. Please check every field.",
            "बिल की स्वतः पढ़ाई का भरोसा कम है। कृपया हर जानकारी जाँचें।",
            "Compare the extracted details with your paper bill and correct any mistakes.",
            "निकाली गई जानकारी को अपने कागज़ी बिल से मिलाकर गलतियाँ सुधारें।", 10)

    score = max(0, min(100, 100 - sum(i["penalty"] for i in issues)))
    advice_en = [i["adv_en"] for i in issues]
    advice_hi = [i["adv_hi"] for i in issues]
    if not issues:
        advice_en = ["Your claim looks complete. Submit it now and keep copies of all documents."]
        advice_hi = ["आपका क्लेम पूरा लग रहा है। अभी जमा करें और सभी दस्तावेज़ों की प्रति रखें।"]

    return {
        "covered_amount": round(covered, 2),
        "non_covered_amount": non_covered_amount,
        "non_covered_items": non_covered_items,
        "documents": documents,
        "warnings": [{"type": i["type"], "message_en": i["en"], "message_hi": i["hi"]} for i in issues],
        "readiness_score": score,
        "advice_en": advice_en,
        "advice_hi": advice_hi,
    }
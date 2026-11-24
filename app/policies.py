import re

DOC_LABELS = {  # id -> (English, Hindi)
    "bill": ("Hospital bill", "अस्पताल का बिल"),
    "discharge_summary": ("Discharge summary", "डिस्चार्ज सारांश"),
    "id_proof": ("ID proof", "पहचान पत्र"),
    "policy_copy": ("Policy copy", "पॉलिसी की प्रति"),
    "fir": ("FIR / accident report", "एफआईआर / दुर्घटना रिपोर्ट"),
}

DOC_HINTS = {  # id -> (advice_en, advice_hi)
    "discharge_summary": ("Ask the hospital's discharge desk for a signed discharge summary.",
                          "अस्पताल के डिस्चार्ज डेस्क से हस्ताक्षरित डिस्चार्ज सारांश मांगें।"),
    "fir": ("Get the FIR or accident report from the nearest police station or employer.",
            "नज़दीकी थाने या नियोक्ता से एफआईआर या दुर्घटना रिपोर्ट प्राप्त करें।"),
}

# keyword rules for items that are not payable: (compiled regex, reason)
_RULES = [
    (re.compile(r"\b(cosmetic|aesthetic|beauty|whitening|botox|facial|hair (transplant|removal)|plastic surgery)", re.I),
     "Cosmetic / aesthetic procedures are excluded"),
    (re.compile(r"\b(dental|tooth|teeth|root canal|denture)", re.I),
     "Dental treatment is excluded unless caused by an accident"),
    (re.compile(r"\b(vitamin|supplement|tonic|protein powder|health drink)", re.I),
     "Vitamins, supplements and tonics are not payable"),
    (re.compile(r"\b(registration|admission fee|attendant|toiletr|laundry|telephone|service charge|diet for attendant)", re.I),
     "Non-medical / administrative charges are not payable"),
    (re.compile(r"\b(spectacle|eyeglass|hearing aid)", re.I),
     "Spectacles and hearing aids are excluded"),
]

POLICIES = {
    "basic_health": {
        "id": "basic_health",
        "name": "Basic Health Insurance",
        "name_hi": "बेसिक स्वास्थ्य बीमा",
        "coverage_limit": 100000,
        "exclusions": [
            "Cosmetic and aesthetic procedures",
            "Routine dental treatment (unless due to accident)",
            "Vitamins, supplements and tonics",
            "Non-medical items (registration, attendant food, toiletries)",
            "Spectacles and hearing aids",
            "Pre-existing conditions during the first 2 years",
        ],
        "required_documents": ["bill", "discharge_summary", "id_proof", "policy_copy"],
        "deadline_days": 30,
        "rules": _RULES,
    },
    "gig_accident": {
        "id": "gig_accident",
        "name": "Gig Worker Accident Cover",
        "name_hi": "गिग वर्कर दुर्घटना बीमा",
        "coverage_limit": 200000,
        "exclusions": [
            "Illness or disease not caused by an accident",
            "Injuries under the influence of alcohol or drugs",
            "Self-inflicted injuries",
            "Cosmetic and aesthetic procedures",
            "Dental treatment unless caused by the accident",
            "Non-medical items (registration, attendant food, toiletries)",
        ],
        "required_documents": ["bill", "fir", "id_proof"],
        "deadline_days": 15,
        "rules": _RULES,
    },
}

EXPECTED_DAYS = 7


def public_policy(p: dict) -> dict:
    return {k: p[k] for k in ("id", "name", "coverage_limit", "exclusions", "required_documents", "deadline_days")}
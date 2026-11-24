from datetime import date, timedelta

# NOTE: ids are what the frontend sends as {"sample_id": ...}; adjust here if your UI uses different ones.
SAMPLE_META = [
    {"id": "clean", "title_en": "Clean claim - everything in order",
     "title_hi": "सही क्लेम - सब कुछ ठीक"},
    {"id": "missing_discharge", "title_en": "Missing discharge summary",
     "title_hi": "डिस्चार्ज सारांश गायब"},
    {"id": "name_mismatch", "title_en": "Name mismatch + excluded cosmetic charge",
     "title_hi": "नाम में अंतर + कवर न होने वाला कॉस्मेटिक शुल्क"},
]

_BILLS = {
    "clean": ("Ramesh Kumar", "City Care Hospital, Pune", 6, 3, "Acute gastroenteritis", [
        ("Room rent (3 days)", 9000), ("Doctor consultation", 3000), ("Medicines", 4500),
        ("Laboratory tests", 2500), ("IV fluids and injections", 1500)]),
    "missing_discharge": ("Ramesh Kumar", "Sanjeevani Nursing Home, Pune", 8, 4, "Dengue fever", [
        ("Room rent (4 days)", 8000), ("Doctor visits", 3500), ("Platelet count and lab tests", 4200),
        ("Medicines", 6300), ("Nursing charges", 2000)]),
    "name_mismatch": ("Rakesh Kumar", "Lifeline Multispeciality Hospital, Pune", 5, 3, "Skin infection (cellulitis)", [
        ("Room rent (2 days)", 6000), ("Doctor fees", 2500), ("Medicines", 3000),
        ("Laboratory tests", 1500), ("Cosmetic facial treatment", 4000)]),
}


def get_sample(sample_id: str | None) -> dict | None:
    """Dates are relative to today so the 'claim deadline' check never fires on demo data."""
    row = _BILLS.get(str(sample_id or ""))
    if not row:
        return None
    name, hospital, adm_days_ago, dis_days_ago, dx, items = row
    today = date.today()
    return {
        "patient_name": name, "hospital": hospital,
        "admission_date": (today - timedelta(days=adm_days_ago)).isoformat(),
        "discharge_date": (today - timedelta(days=dis_days_ago)).isoformat(),
        "diagnosis": dx,
        "total_amount": sum(a for _, a in items),
        "items": [{"name": n, "amount": a} for n, a in items],
        "confidence": 0.96, "source": "sample",
    }
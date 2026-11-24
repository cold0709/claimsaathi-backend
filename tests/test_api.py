import io

from PIL import Image

HLT, ACC = "HLT-2026-001234", "ACC-2026-005678"
ALL_DOCS = ["bill", "discharge_summary", "id_proof", "policy_copy"]


def login(client, pn=HLT):
    client.post("/api/auth/send-otp", json={"policy_number": pn})
    return client.post("/api/auth/verify-otp", json={"policy_number": pn, "otp": "123456"})


def sample(client, sid):
    return client.post("/api/extract", json={"sample_id": sid}).json()


def png_bytes(size=(200, 100)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def test_health(client):
    r = client.get("/health").json()
    assert r == {"status": "ok", "demo_mode": True, "ai_enabled": False}


def test_send_otp_and_login(client):
    r = client.post("/api/auth/send-otp", json={"policy_number": " hlt-2026-001234 ", "junk": 1})
    assert r.status_code == 200
    assert r.json() == {"sent": True, "phone_masked": "98XXXXXX10", "demo_otp": "123456"}
    r = client.post("/api/auth/verify-otp", json={"policy_number": HLT, "otp": "123456"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["type_hi"] == "बेसिक स्वास्थ्य बीमा" and user["sum_insured"] == 100000
    assert r.json()["token"]


def test_unknown_policy_404_and_wrong_otp_400(client):
    assert client.post("/api/auth/send-otp", json={"policy_number": "NOPE"}).status_code == 404
    client.post("/api/auth/send-otp", json={"policy_number": HLT})
    assert client.post("/api/auth/verify-otp", json={"policy_number": HLT, "otp": "000000"}).status_code == 400


def test_lockout_after_five_attempts(client):
    client.post("/api/auth/send-otp", json={"policy_number": ACC})
    for _ in range(5):
        assert client.post("/api/auth/verify-otp", json={"policy_number": ACC, "otp": "111111"}).status_code == 400
    r = client.post("/api/auth/verify-otp", json={"policy_number": ACC, "otp": "123456"})
    assert r.status_code == 429          # locked even with the right OTP
    assert client.post("/api/auth/send-otp", json={"policy_number": ACC}).status_code == 429


def test_send_otp_rate_limit(client):
    codes = [client.post("/api/auth/send-otp", json={"policy_number": HLT}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_change_phone(client):
    client.post("/api/auth/send-otp", json={"policy_number": ACC})
    bad = client.post("/api/auth/change-phone", json={"policy_number": ACC, "new_phone": "12345", "otp": "123456"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/change-phone", json={"policy_number": ACC, "new_phone": "9000000001", "otp": "123456"})
    assert ok.json() == {"ok": True}
    client.post("/api/auth/send-otp", json={"policy_number": ACC})
    assert client.post("/api/auth/change-phone",
                       json={"policy_number": ACC, "new_phone": "9812345678", "otp": "123456"}).json() == {"ok": True}


def test_policies_and_samples(client):
    pol = client.get("/api/policies").json()
    assert [p["id"] for p in pol] == ["basic_health", "gig_accident"]
    assert set(pol[0]) == {"id", "name", "coverage_limit", "exclusions", "required_documents", "deadline_days"}
    assert len(client.get("/api/samples").json()) == 3


def test_extract_sample_and_errors(client):
    b = sample(client, "clean")
    assert b["source"] == "sample" and b["total_amount"] == 20500
    assert client.post("/api/extract", json={"sample_id": "nope"}).status_code == 404
    assert client.post("/api/extract", json={}).status_code == 400


def test_extract_upload(client):
    r = client.post("/api/extract", files={"file": ("bill.png", png_bytes(), "image/png")})
    assert r.status_code == 200 and r.json()["source"] == "fallback"
    assert client.post("/api/extract", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400
    fake = client.post("/api/extract", files={"file": ("a.png", b"not an image", "image/png")})
    assert fake.status_code == 400
    big = client.post("/api/extract", files={"file": ("a.png", b"0" * (8 * 1024 * 1024 + 10), "image/png")})
    assert big.status_code == 400


# ---------------------------------------------------------------- Gemini (mocked, no network)
def _fake_gemini(monkeypatch, behaviour):
    """behaviour(url, call_number) -> HTTP status code. Returns the list of URLs called."""
    import httpx
    from app import extraction

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "model-a")
    monkeypatch.setattr(extraction, "_working_gemini_model", None)    # don't leak state between tests
    monkeypatch.setattr(extraction, "_gemini_blocked_until", 0.0)
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "overloaded"

        def json(self):
            t = ('{"patient_name": "Ramesh Kumar", "hospital": "City Hospital", "admission_date": "2026-01-02",'
                 ' "discharge_date": "2026-01-04", "diagnosis": "Fever", "total_amount": 5000,'
                 ' "items": [{"name": "Room rent", "amount": 5000}], "confidence": 0.9}')
            return {"candidates": [{"content": {"parts": [{"text": t}]}}]}

    def fake_post(url, **kw):
        calls.append(url)
        return Resp(behaviour(url, len(calls)))

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_gemini_extraction_mocked(client, monkeypatch):
    calls = _fake_gemini(monkeypatch, lambda url, n: 200)
    assert client.get("/health").json()["ai_enabled"] is True
    r = client.post("/api/extract", files={"file": ("bill.png", png_bytes(), "image/png")}).json()
    assert r["source"] == "gemini" and r["patient_name"] == "Ramesh Kumar" and r["total_amount"] == 5000
    assert len(calls) == 1


def test_gemini_moves_to_next_model_on_503(client, monkeypatch):
    calls = _fake_gemini(monkeypatch, lambda url, n: 503 if "model-a" in url else 200)
    r = client.post("/api/extract", files={"file": ("b.png", png_bytes((50, 50)), "image/png")}).json()
    assert r["source"] == "gemini" and len(calls) == 2
    assert "model-a" in calls[0] and "model-a" not in calls[1]


def test_gemini_cooldown_after_total_failure(client, monkeypatch):
    calls = _fake_gemini(monkeypatch, lambda url, n: 503)
    img = {"file": ("b.png", png_bytes((50, 50)), "image/png")}
    assert client.post("/api/extract", files=img).json()["source"] == "fallback"
    assert len(calls) == 3                       # model-a + two fallbacks, then gave up
    assert client.post("/api/extract", files=img).json()["source"] == "fallback"
    assert len(calls) == 3                       # cooldown: second upload never called Google


# ---------------------------------------------------------------- validation / claims / complaints / auth
def test_validate_clean(client):
    r = client.post("/api/validate", json={"policy_id": "basic_health", "bill": sample(client, "clean"),
                                           "documents_provided": ALL_DOCS, "policy_holder_name": "Ramesh Kumar",
                                           "whatever": 1}).json()
    assert r["readiness_score"] == 100 and r["covered_amount"] == 20500 and r["warnings"] == []


def test_validate_missing_discharge(client):
    r = client.post("/api/validate", json={"policy_id": "basic_health", "bill": sample(client, "missing_discharge"),
                                           "documents_provided": ["bill", "id_proof", "policy_copy"],
                                           "policy_holder_name": "Ramesh Kumar"}).json()
    assert {"name": "Discharge summary", "status": "missing"} in r["documents"]
    assert r["readiness_score"] == 80 and r["warnings"][0]["type"] == "missing_document"


def test_validate_name_mismatch_and_cosmetic(client):
    r = client.post("/api/validate", json={"policy_id": "basic_health", "bill": sample(client, "name_mismatch"),
                                           "documents_provided": ALL_DOCS,
                                           "policy_holder_name": "Ramesh Kumar"}).json()
    types = {w["type"] for w in r["warnings"]}
    assert {"name_mismatch", "excluded_items"} <= types
    assert r["non_covered_amount"] == 4000 and r["covered_amount"] == 13000
    assert r["non_covered_items"][0]["name"] == "Cosmetic facial treatment"


def test_validate_gig_docs(client):
    r = client.post("/api/validate", json={"policy_id": "gig_accident", "bill": sample(client, "clean"),
                                           "documents_provided": ["bill", "id_proof"],
                                           "policy_holder_name": "Ramesh Kumar"}).json()
    assert {"name": "FIR / accident report", "status": "missing"} in r["documents"]


def test_pdf_submit_and_claims(client):
    body = {"policy_id": "basic_health", "bill": sample(client, "clean"), "documents_provided": ALL_DOCS,
            "policy_holder_name": "Ramesh Kumar", "validation": {"readiness_score": 999}}
    pdf = client.post("/api/claim-pdf", json=body)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    s = client.post("/api/submit", json=body).json()
    assert s["tracking_id"].startswith("CS-") and s["expected_days"] == 7 and s["simulated"] is True
    assert client.post("/api/submit", json=body).json()["tracking_id"] == s["tracking_id"]   # idempotent
    lst = client.get("/api/claims", params={"policy_number": HLT}).json()
    assert lst[0]["tracking_id"] == s["tracking_id"] and lst[0]["readiness_score"] == 100
    detail = client.get(f"/api/claims/{s['tracking_id']}").json()
    assert detail["events"][0]["status"] == "submitted"
    assert client.get("/api/claims/CS-0000-00000").status_code == 404


def test_complaints(client):
    assert client.post("/api/complaints", json={"policy_number": HLT, "category": "claim", "message": "hi"}
                       ).status_code == 422
    assert client.post("/api/complaints", json={"policy_number": "X", "category": "c", "message": "long enough"}
                       ).status_code == 404
    r = client.post("/api/complaints", json={"policy_number": HLT, "category": "claim", "message": "Claim is late"})
    assert r.json()["status"] == "open" and r.json()["complaint_id"].startswith("CMP-")
    client.post("/api/complaints", json={"policy_number": HLT, "category": "other", "message": "Second one"})
    lst = client.get("/api/complaints", params={"policy_number": HLT}).json()
    assert lst[0]["message"] == "Second one"


def test_require_auth(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    assert client.get("/api/policies").status_code == 401
    assert client.get("/health").status_code == 200
    token = login(client).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/policies", headers=h).status_code == 200
    assert client.get("/api/claims", params={"policy_number": ACC}, headers=h).status_code == 403
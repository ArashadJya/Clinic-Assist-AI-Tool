# tests/test_regression.py
# Regression tests for ClinicAssist AI.
# They use a FAKE AI and a FAKE SMTP server, so no API key, no internet and no real email are used.
#
# Run:  python -m pytest tests -v
# Test names:  test_unit_*   = logic tests (ai_engine, logger, sample data)
#              test_static_* = security / config checks on the source files
#              test_ui_*     = full app tests using Streamlit's AppTest (patient view vs staff view)

import json
import os
import re
import shutil
import smtplib
import sys

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

# Project folder to test. Default = the folder above /tests. Can be overridden for comparisons.
PROJECT_DIR = os.environ.get(
    "CLINIC_PROJECT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
sys.path.insert(0, PROJECT_DIR)

import ai_engine  # noqa: E402
import logger  # noqa: E402
import sample_data  # noqa: E402
from google.api_core import exceptions as gexc  # noqa: E402

OLD_LOG = os.path.join(os.path.dirname(__file__), "old_format_log_sample.csv")


# ----------------------------------------------------------------------
# FIXTURES AND HELPERS
# ----------------------------------------------------------------------
class FakeAI:
    """Replaces ai_engine._call_gemini. Lets each test decide what the 'AI' answers."""

    def __init__(self):
        self.category, self.urgency = "Appointment", "Low"
        self.summary, self.reason = "SUMMARY_SECRET_XYZ", "REASON_SECRET_XYZ"
        self.reply = "REPLY_SECRET_XYZ"
        self.triage_outputs = None      # list of raw strings, returned in order (last one repeats)
        self.error = None               # exception to raise on every call
        self.triage_calls = 0
        self.reply_calls = 0

    def __call__(self, prompt, json_mode=False):
        if self.error:
            raise self.error
        if json_mode:                    # triage call
            self.triage_calls += 1
            if self.triage_outputs is not None:
                i = min(self.triage_calls - 1, len(self.triage_outputs) - 1)
                return self.triage_outputs[i]
            return json.dumps({"category": self.category, "urgency": self.urgency,
                               "summary": self.summary, "reason": self.reason})
        self.reply_calls += 1            # reply call
        return self.reply


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    """Every test writes its log to a temporary folder, never to the real data/ folder."""
    monkeypatch.setattr(logger, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(logger, "LOG_FILE", str(tmp_path / "clinic_log.csv"))
    return tmp_path


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    """Tests must never read the developer's real .streamlit/secrets.toml.
    Every test starts with EMPTY secrets; a test adds only the secrets it needs."""
    monkeypatch.setattr(st, "secrets", {})


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(ai_engine, "_call_gemini", fake)
    return fake


class FakeSMTP:
    """Fake mail server. Records messages instead of sending them."""
    sent, used = [], 0

    def __init__(self, host, port, timeout=None):
        FakeSMTP.used += 1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.used = [], 0
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def new_app(secrets=None):
    at = AppTest.from_file(os.path.join(PROJECT_DIR, "app.py"), default_timeout=30)
    for key, value in (secrets or {}).items():
        at.secrets[key] = value
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def page_text(at):
    """All visible text of the main page, lower-cased, so tests can check what a user can see."""
    parts = []
    for group in (at.title, at.header, at.subheader, at.markdown, at.caption, at.success,
                  at.info, at.warning, at.error, at.metric):
        parts += [str(getattr(e, "value", "")) for e in group]
    parts += [str(t.value) for t in at.text_area]
    parts += [str(b.label) for b in at.button]
    return "\n".join(parts).lower()


def find_button(at, text):
    for b in at.button:
        if text.lower() in str(b.label).lower():
            return b
    return None


STAFF = {"STAFF_PASSWORD": "pw123", "DEMO_MODE": True}


def login_staff(at, password="pw123"):
    at.sidebar.radio[0].set_value("Clinic Staff").run()
    at.text_input[0].set_value(password)
    find_button(at, "Login").click().run()
    assert not at.exception
    return at


def seed(urgency="High", category="Emergency", email="", enquiry="seed enquiry"):
    """Put one row in the log (same as a patient submission would)."""
    logger.save_result(
        enquiry,
        {"category": category, "urgency": urgency, "summary": "seed summary", "reason": "r"},
        "seed reply text",
        *([email] if email else []),
    )


# ======================================================================
# UNIT: sample data
# ======================================================================
def test_unit_sample_data_has_10_fake_enquiries():
    assert len(sample_data.SAMPLE_ENQUIRIES) == 10
    assert all(isinstance(t, str) and len(t) > 20 for t in sample_data.SAMPLE_ENQUIRIES.values())


# ======================================================================
# UNIT: ai_engine
# ======================================================================
def test_unit_ai_clean_json_strips_markdown_fences_and_extra_words():
    raw = 'Sure! ```json\n{"category": "Billing", "urgency": "Low"}\n``` hope this helps'
    assert json.loads(ai_engine.clean_json_text(raw)) == {"category": "Billing", "urgency": "Low"}


def test_unit_ai_triage_valid_json(fake_ai):
    fake_ai.category, fake_ai.urgency = "Billing", "Medium"
    r = ai_engine.triage_enquiry("I was charged twice")
    assert (r["category"], r["urgency"], r["used_fallback"]) == ("Billing", "Medium", False)
    assert fake_ai.triage_calls == 1


def test_unit_ai_triage_accepts_fenced_json_and_wrong_case(fake_ai):
    fake_ai.triage_outputs = ['```json\n{"category":"reports","urgency":"LOW","summary":"s","reason":"r"}\n```']
    r = ai_engine.triage_enquiry("where is my report")
    assert (r["category"], r["urgency"], r["used_fallback"]) == ("Reports", "Low", False)


def test_unit_ai_triage_retries_once_when_json_is_invalid(fake_ai):
    good = json.dumps({"category": "Reports", "urgency": "Low", "summary": "s", "reason": "r"})
    fake_ai.triage_outputs = ["this is not json", good]
    r = ai_engine.triage_enquiry("report please")
    assert fake_ai.triage_calls == 2 and r["category"] == "Reports" and not r["used_fallback"]


def test_unit_ai_triage_fallback_general_medium_after_two_bad_answers(fake_ai):
    fake_ai.triage_outputs = ["garbage", "more garbage"]
    r = ai_engine.triage_enquiry("hello there")
    assert fake_ai.triage_calls == 2
    assert (r["category"], r["urgency"], r["used_fallback"]) == ("General", "Medium", True)


def test_unit_ai_triage_fallback_flags_emergency_keywords(fake_ai):
    fake_ai.triage_outputs = ["garbage"]
    r = ai_engine.triage_enquiry("My father has severe chest pain")
    assert (r["category"], r["urgency"], r["used_fallback"]) == ("Emergency", "High", True)


def test_unit_ai_triage_rejects_values_outside_allowed_lists(fake_ai):
    fake_ai.triage_outputs = [json.dumps({"category": "Pizza", "urgency": "Urgent",
                                          "summary": "s", "reason": "r"})]
    assert ai_engine.triage_enquiry("hi")["used_fallback"] is True


def test_unit_ai_reply_high_urgency_gets_emergency_line_if_ai_forgets(fake_ai):
    fake_ai.reply = "Dear patient, we received your message."
    out = ai_engine.draft_reply("x", {"category": "Emergency", "urgency": "High", "summary": "s", "reason": "r"})
    assert "emergency" in out.lower() and "hospital" in out.lower()


def test_unit_ai_reply_does_not_duplicate_emergency_text(fake_ai):
    fake_ai.reply = "Please call emergency services now."
    out = ai_engine.draft_reply("x", {"category": "Emergency", "urgency": "High", "summary": "s", "reason": "r"})
    assert out == "Please call emergency services now."


def test_unit_ai_reply_low_urgency_has_no_emergency_line(fake_ai):
    fake_ai.reply = "We will confirm your slot shortly."
    out = ai_engine.draft_reply("x", {"category": "Appointment", "urgency": "Low", "summary": "s", "reason": "r"})
    assert out == "We will confirm your slot shortly."


@pytest.mark.parametrize("error, expected", [
    (gexc.ResourceExhausted("quota"), "rate limit"),
    (gexc.NotFound("model"), "model name was not found"),
    (gexc.PermissionDenied("key"), "api key"),
    (RuntimeError("boom"), "not available"),
])
def test_unit_ai_api_errors_become_friendly_messages(monkeypatch, error, expected):
    class BadModel:
        def generate_content(self, prompt):
            raise error
    monkeypatch.setattr(ai_engine, "_get_model", lambda json_mode=False: BadModel())
    with pytest.raises(ai_engine.AIServiceError) as info:
        ai_engine._call_gemini("hi")
    assert expected in str(info.value).lower()


def test_unit_ai_missing_api_key_gives_friendly_error():
    with pytest.raises(ai_engine.AIServiceError) as info:
        ai_engine._get_model()
    assert "gemini_api_key" in str(info.value).lower()


# ======================================================================
# UNIT: logger
# ======================================================================
def test_unit_logger_basic_roundtrip():
    assert len(logger.load_log()) == 0
    seed("Low", "Billing", enquiry="billing question")
    df = logger.load_log()
    assert len(df) == 1
    assert df.loc[0, "enquiry"] == "billing question"
    assert df.loc[0, "category"] == "Billing" and df.loc[0, "urgency"] == "Low"
    assert df.loc[0, "reply"] == "seed reply text"


def test_unit_logger_new_rows_start_as_pending_and_keep_email():
    seed("Low", "Billing", email="a@example.com")
    df = logger.load_log()
    assert df.loc[0, "status"] == "Pending review" and df.loc[0, "patient_email"] == "a@example.com"


def test_unit_logger_update_status():
    seed("Low", "Billing")
    seed("High", "Emergency")
    logger.update_status(1, "Reviewed")
    assert list(logger.load_log()["status"]) == ["Pending review", "Reviewed"]
    logger.update_status(99, "Reviewed")            # unknown row must not crash or change anything
    assert list(logger.load_log()["status"]) == ["Pending review", "Reviewed"]


def test_unit_logger_old_format_csv_still_loads_and_accepts_new_rows(tmp_log):
    shutil.copy(OLD_LOG, logger.LOG_FILE)           # the log file from the last deployed version
    old_rows = len(logger.load_log())
    assert old_rows >= 1
    df = logger.load_log()
    assert list(df.columns) == logger.COLUMNS
    assert set(df["status"]) == {"Pending review"}
    first_enquiry = df.loc[0, "enquiry"]
    seed("Low", "Billing", enquiry="new row after old log")
    df2 = logger.load_log()
    assert len(df2) == old_rows + 1
    assert df2.loc[0, "enquiry"] == first_enquiry   # old data not damaged


def test_unit_logger_corrupt_file_does_not_crash(tmp_log):
    open(logger.LOG_FILE, "w").write("")
    assert len(logger.load_log()) == 0


# ======================================================================
# STATIC: security and config checks
# ======================================================================
def test_static_no_hardcoded_api_keys_in_source_files():
    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{10,}|AQ\.[0-9A-Za-z_\-]{10,}")
    checked = 0
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "data")]
        for name in files:
            if name.endswith((".py", ".md", ".example", ".txt", ".csv")):
                checked += 1
                text = open(os.path.join(root, name), encoding="utf-8", errors="ignore").read()
                assert not pattern.search(text), f"key-like text found in {name}"
    assert checked > 5


def test_static_gitignore_protects_secrets_and_data():
    lines = open(os.path.join(PROJECT_DIR, ".gitignore")).read().splitlines()
    for needed in (".streamlit/secrets.toml", ".env", "data/"):
        assert needed in lines


def test_static_ai_engine_reads_key_only_from_st_secrets():
    src = open(os.path.join(PROJECT_DIR, "ai_engine.py"), encoding="utf-8").read()
    assert 'st.secrets["GEMINI_API_KEY"]' in src


# ======================================================================
# UI: PATIENT VIEW
# ======================================================================
def test_ui_patient_is_default_and_cannot_see_staff_features():
    at = new_app()
    text = page_text(at)
    assert "not medical advice" in text                       # disclaimer still shown
    assert len(at.tabs) == 0                                  # no History / Dashboard tabs
    assert len(at.metric) == 0 and len(at.dataframe) == 0     # no dashboard numbers, no log table
    assert find_button(at, "send email") is None              # no email option
    assert "dashboard" not in text and "history" not in text and "drafted reply" not in text


def test_ui_patient_empty_input_shows_error_and_logs_nothing(fake_ai):
    at = new_app()
    find_button(at, "Submit").click().run()
    assert any("enter your enquiry" in e.value.lower() for e in at.error)
    assert fake_ai.triage_calls == 0 and len(logger.load_log()) == 0


def test_ui_patient_too_long_input_is_rejected(fake_ai):
    at = new_app()
    at.text_area(key="enquiry_text").set_value("a" * 2001)
    find_button(at, "Submit").click().run()
    assert any("too long" in e.value.lower() for e in at.error)
    assert fake_ai.triage_calls == 0


def test_ui_patient_sample_dropdown_fills_text_box():
    at = new_app()
    first = list(sample_data.SAMPLE_ENQUIRIES)[0]
    at.selectbox(key="sample_choice").set_value(first).run()
    assert at.text_area(key="enquiry_text").value == sample_data.SAMPLE_ENQUIRIES[first]


def test_ui_patient_submit_sees_only_thank_you_not_ai_results(fake_ai):
    at = new_app()
    at.text_area(key="enquiry_text").set_value("I want to book an appointment")
    at.text_input[0].set_value("p@example.com")
    find_button(at, "Submit").click().run()
    assert not at.exception
    assert any("received" in s.value.lower() for s in at.success)
    text = page_text(at)
    for secret in ("summary_secret_xyz", "reason_secret_xyz", "reply_secret_xyz"):
        assert secret not in text                              # AI output hidden from patient
    assert "urgency" not in text and "category" not in text
    assert len(at.error) == 0                                  # low urgency: no emergency box
    df = logger.load_log()                                     # staff can still see it
    assert len(df) == 1 and df.loc[0, "status"] == "Pending review"
    assert df.loc[0, "patient_email"] == "p@example.com" and df.loc[0, "reply"] == "REPLY_SECRET_XYZ"


def test_ui_patient_emergency_gets_emergency_warning_but_no_triage_details(fake_ai):
    fake_ai.category, fake_ai.urgency = "Emergency", "High"
    at = new_app()
    at.text_area(key="enquiry_text").set_value("severe chest pain")
    find_button(at, "Submit").click().run()
    assert any("emergency services" in e.value.lower() for e in at.error)
    text = page_text(at)
    assert "high urgency" not in text and "summary_secret_xyz" not in text
    assert logger.load_log().loc[0, "urgency"] == "High"


def test_ui_patient_ai_failure_shows_friendly_error_and_logs_nothing(fake_ai):
    fake_ai.error = ai_engine.AIServiceError("Rate limit reached. Please wait a minute and try again.")
    at = new_app()
    at.text_area(key="enquiry_text").set_value("hello")
    find_button(at, "Submit").click().run()
    assert not at.exception
    assert any("rate limit" in e.value.lower() for e in at.error)
    assert len(at.success) == 0 and len(logger.load_log()) == 0


# ======================================================================
# UI: CLINIC STAFF VIEW
# ======================================================================
def test_ui_staff_locked_when_no_password_configured():
    at = new_app()
    at.sidebar.radio[0].set_value("Clinic Staff").run()
    assert any("staff_password" in e.value.lower() for e in at.error)
    assert len(at.tabs) == 0 and len(at.metric) == 0


def test_ui_staff_wrong_password_is_rejected():
    seed()
    at = new_app(STAFF)
    at.sidebar.radio[0].set_value("Clinic Staff").run()
    assert len(at.tabs) == 0                                   # login form first
    at.text_input[0].set_value("wrong")
    find_button(at, "Login").click().run()
    assert any("wrong password" in e.value.lower() for e in at.error)
    assert len(at.tabs) == 0 and len(at.metric) == 0 and len(at.dataframe) == 0


def test_ui_staff_correct_password_shows_three_tabs_and_demo_mode_by_default():
    seed()
    at = login_staff(new_app({"STAFF_PASSWORD": "pw123"}))     # DEMO_MODE secret missing -> default demo
    assert [t.label for t in at.tabs] == ["📥 Review Queue", "📜 History", "📊 Dashboard"]
    assert any("demo mode is on" in i.value.lower() for i in at.info)


def test_ui_staff_review_queue_high_urgency_first_and_email_disabled_in_demo(fake_smtp):
    seed("Low", "Billing", enquiry="low one")
    seed("High", "Emergency", enquiry="high one")
    at = login_staff(new_app(STAFF))
    queue = [s for s in at.selectbox if s.options and "|" in s.options[0]][0]
    assert "High" in queue.options[0] and "Low" in queue.options[1]
    assert "seed reply text" in [t.value for t in at.text_area]            # editable reply shown
    send = find_button(at, "disabled in demo mode")
    assert send is not None and send.disabled
    assert find_button(at, "Send Email") is send                           # no enabled send button
    assert fake_smtp.used == 0 and fake_smtp.sent == []                    # nothing sent in demo


def test_ui_staff_dashboard_numbers():
    seed("High", "Emergency")
    seed("Low", "Billing")
    at = login_staff(new_app(STAFF))
    values = {m.label: m.value for m in at.metric}
    assert values == {"Total enquiries": "2", "High urgency": "1", "Pending review": "2"}


def test_ui_staff_history_tab_shows_log_table():
    seed("High", "Emergency")
    at = login_staff(new_app(STAFF))
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 1


def test_ui_staff_mark_as_reviewed_updates_log_and_queue():
    seed("High", "Emergency", enquiry="first")
    seed("Low", "Billing", enquiry="second")
    at = login_staff(new_app(STAFF))
    find_button(at, "Mark as reviewed").click().run()
    assert not at.exception
    df = logger.load_log()
    assert sorted(df["status"]) == ["Pending review", "Reviewed"]
    assert df[df["urgency"] == "High"].iloc[0]["status"] == "Reviewed"     # High one was on top
    queue = [s for s in at.selectbox if s.options and "|" in s.options[0]][0]
    assert len(queue.options) == 1 and "Low" in queue.options[0]


def test_ui_staff_logout_by_switching_to_patient_requires_password_again():
    seed()
    at = login_staff(new_app(STAFF))
    assert len(at.tabs) == 3
    at.sidebar.radio[0].set_value("Patient").run()
    assert len(at.tabs) == 0 and find_button(at, "Submit") is not None
    at.sidebar.radio[0].set_value("Clinic Staff").run()
    assert len(at.tabs) == 0 and len(at.text_input) >= 1                   # login form again


def test_ui_staff_real_email_sent_only_when_demo_mode_is_off(fake_smtp):
    seed("Low", "Billing", email="p@example.com")
    secrets = {"STAFF_PASSWORD": "pw123", "DEMO_MODE": False, "SMTP_HOST": "smtp.test",
               "SMTP_PORT": 587, "SMTP_USER": "clinic@test", "SMTP_PASSWORD": "x"}
    at = login_staff(new_app(secrets))
    assert not any("demo mode is on" in i.value.lower() for i in at.info)
    send = find_button(at, "Send Email")
    assert send is not None and not send.disabled
    send.click().run()
    assert not at.exception
    assert len(fake_smtp.sent) == 1 and fake_smtp.sent[0]["To"] == "p@example.com"
    assert logger.load_log().loc[0, "status"] == "Reply sent"


@pytest.mark.parametrize("value", [True, "true", "TRUE", "yes"])
def test_ui_staff_demo_mode_stays_on_for_true_like_values(fake_smtp, value):
    seed("Low", "Billing", email="p@example.com")
    at = login_staff(new_app({"STAFF_PASSWORD": "pw123", "DEMO_MODE": value}))
    assert find_button(at, "disabled in demo mode").disabled
    assert fake_smtp.used == 0

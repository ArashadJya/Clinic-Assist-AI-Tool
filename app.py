# app.py
# Streamlit user interface. Run with:  python -m streamlit run app.py
#
# TWO VIEWS:
#   1) Patient view      -> only a form. Patient sees a thank-you message (and an emergency
#                           warning if needed). NO dashboard, NO history, NO email option.
#   2) Clinic Staff view -> password protected. Review queue, history, dashboard, email.

import hmac                                   # safe password comparison
import html                                   # to safely show AI text inside HTML boxes
import smtplib                                # sends email via SMTP
from email.message import EmailMessage        # builds the email
import streamlit as st

from sample_data import SAMPLE_ENQUIRIES      # 10 fake enquiries
from ai_engine import triage_enquiry, draft_reply, AIServiceError
from logger import save_result, load_log, update_status

# ---------------- PAGE SETUP ----------------
st.set_page_config(page_title="ClinicAssist AI", page_icon="🏥", layout="wide")

MAX_CHARS = 2000                              # limit the input size
URGENCY_STYLE = {                             # colour of each alert box (staff view only)
    "High":   {"bg": "#fdecea", "border": "#d32f2f", "icon": "🔴"},
    "Medium": {"bg": "#fff3e0", "border": "#f57c00", "icon": "🟠"},
    "Low":    {"bg": "#e8f5e9", "border": "#388e3c", "icon": "🟢"},
}
URGENCY_RANK = {"High": 0, "Medium": 1, "Low": 2}   # used to show High urgency first


# ---------------- HELPER FUNCTIONS ----------------
def get_secret(key, default=None):
    """Read a secret safely. Return default if secrets file or key is missing."""
    try:
        return st.secrets[key]
    except Exception:
        return default


def is_demo_mode() -> bool:
    """DEMO_MODE defaults to True. Only the value false turns it off."""
    value = get_secret("DEMO_MODE", True)
    if isinstance(value, str):                # allow "false" written as text
        return value.strip().lower() != "false"
    return bool(value)


def send_email(to_address: str, subject: str, body: str) -> None:
    """Send a real email using SMTP settings from secrets. Used only if DEMO_MODE is false."""
    msg = EmailMessage()
    msg["From"] = get_secret("SMTP_FROM", get_secret("SMTP_USER"))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(get_secret("SMTP_HOST"), int(get_secret("SMTP_PORT", 587)), timeout=15) as server:
        server.starttls()                     # secure the connection
        server.login(get_secret("SMTP_USER"), get_secret("SMTP_PASSWORD"))
        server.send_message(msg)


def load_sample():
    """Callback: copy the chosen sample enquiry into the text box."""
    choice = st.session_state["sample_choice"]
    if choice in SAMPLE_ENQUIRIES:
        st.session_state["enquiry_text"] = SAMPLE_ENQUIRIES[choice]


def alert_box(urgency: str, category: str, summary: str, reason: str = ""):
    """Coloured urgency box. Only staff can see this."""
    style = URGENCY_STYLE.get(urgency, URGENCY_STYLE["Medium"])
    st.markdown(
        f"""<div style="background:{style['bg']};border-left:8px solid {style['border']};
        padding:14px;border-radius:6px;color:#222;">
        <b>{style['icon']} {html.escape(urgency)} urgency</b> &nbsp;|&nbsp;
        Category: <b>{html.escape(category)}</b><br>
        <b>Summary:</b> {html.escape(summary)}<br>
        <b>Reason:</b> {html.escape(reason or '-')}</div>""",
        unsafe_allow_html=True,
    )


# ======================================================================
# VIEW 1: PATIENT (form only)
# ======================================================================
def patient_view():
    st.subheader("📝 Send your enquiry to the clinic")

    st.selectbox(                              # demo helper: fills the box with a fake enquiry
        "Demo: load a sample enquiry (fake)",
        ["-- Type my own --"] + list(SAMPLE_ENQUIRIES.keys()),
        key="sample_choice",
        on_change=load_sample,
    )
    enquiry = st.text_area("Your enquiry", key="enquiry_text", height=160,
                           placeholder="Type your enquiry here (use FAKE details only)...")
    patient_email = st.text_input("Your email (optional, use a fake address in demo)",
                                  placeholder="patient@example.com")

    if st.button("📨 Submit enquiry", type="primary"):
        text = (enquiry or "").strip()
        if not text:                                          # empty input check
            st.error("Please enter your enquiry first.")
        elif len(text) > MAX_CHARS:                           # too long check
            st.error(f"Your enquiry is too long. Please keep it under {MAX_CHARS} characters.")
        else:
            try:
                with st.spinner("Sending your enquiry..."):
                    triage = triage_enquiry(text)             # AI call 1: classify (hidden from patient)
                    reply = draft_reply(text, triage)         # AI call 2: draft reply (hidden from patient)
                try:
                    save_result(text, triage, reply, patient_email.strip())  # save for staff
                except Exception:
                    st.warning("Your enquiry could not be saved. Please try again.")
                    return
                # Patient only sees a simple confirmation
                st.success("✅ Thank you. Your enquiry has been received. "
                           "Our team will review it and reply soon.")
                if triage["urgency"] == "High" or triage["category"] == "Emergency":
                    st.error("🚨 If this is a medical emergency, please call your local emergency "
                             "services or go to the nearest hospital immediately. "
                             "Do not wait for our reply.")
            except AIServiceError as err:                     # friendly AI errors
                st.error(f"⚠️ {err}")
            except Exception:
                st.error("Something went wrong. Please try again.")


# ======================================================================
# VIEW 2: CLINIC STAFF (password protected)
# ======================================================================
def staff_login() -> bool:
    """Show a password box. Return True if staff is logged in."""
    if st.session_state.get("staff_ok"):
        return True
    expected = get_secret("STAFF_PASSWORD")
    if not expected:                                          # no password set = staff area stays locked
        st.error("Staff area is locked. Add STAFF_PASSWORD in your secrets to enable it.")
        return False
    st.subheader("🔒 Clinic staff login")
    password = st.text_input("Staff password", type="password")
    if st.button("Login"):
        if hmac.compare_digest(password.encode(), str(expected).encode()):  # safe compare
            st.session_state["staff_ok"] = True
            st.rerun()                                        # reload as logged in
        else:
            st.error("Wrong password.")
    return False


def review_queue_tab(demo: bool):
    """Staff checks each enquiry, edits the reply, previews/sends email, updates status."""
    log_df = load_log()
    if log_df.empty:
        st.info("No enquiries yet. Ask a patient to submit one from the Patient view.")
        return

    only_pending = st.checkbox("Show only pending enquiries", value=True)
    view_df = log_df.copy()
    if only_pending:
        view_df = view_df[view_df["status"] == "Pending review"]
    if view_df.empty:
        st.success("🎉 No pending enquiries.")
        return

    # High urgency first, then newest first
    view_df["rank"] = view_df["urgency"].map(URGENCY_RANK).fillna(1)
    view_df = view_df.sort_values(["rank", "timestamp"], ascending=[True, False])

    def label(i):                                             # text shown in the dropdown
        r = view_df.loc[i]
        return f"{r['timestamp']} | {r['urgency']} | {r['category']} | {r['status']}"

    idx = st.selectbox("Select an enquiry", list(view_df.index), format_func=label)
    row = log_df.loc[idx]

    alert_box(row["urgency"], row["category"], row["summary"])
    if row["urgency"] == "High":
        st.error("🚨 High urgency: handle this first. Patient must be told to contact emergency services.")

    st.markdown("**Patient enquiry**")
    st.write(row["enquiry"])

    st.subheader("✉️ Drafted reply")
    subject = "Re: Your enquiry to ClinicAssist Demo Clinic"
    edited_reply = st.text_area("Edit the reply before sending", value=row["reply"],
                                height=220, key=f"reply_{idx}")

    st.subheader("📧 Email")
    to_address = st.text_input("Patient email", value=row["patient_email"], key=f"to_{idx}")
    if demo:
        with st.expander("Email preview (DEMO MODE: nothing is sent)", expanded=True):
            st.write(f"**To:** {to_address or '(no email given)'}")
            st.write(f"**Subject:** {subject}")
            st.write(edited_reply)
        st.button("Send Email (disabled in demo mode)", disabled=True, key=f"send_off_{idx}")
    else:
        if st.button("Send Email", key=f"send_{idx}"):
            if "@" not in to_address:
                st.error("Please enter a valid email address.")
            else:
                try:
                    send_email(to_address, subject, edited_reply)
                    update_status(int(idx), "Reply sent")
                    st.success("Email sent and status updated.")
                    st.rerun()
                except Exception:
                    st.error("Could not send the email. Check your SMTP settings.")

    if st.button("✅ Mark as reviewed", key=f"rev_{idx}"):   # works in demo mode too
        update_status(int(idx), "Reviewed")
        st.rerun()


def history_tab():
    st.subheader("History log")
    log_df = load_log()
    if log_df.empty:
        st.info("No enquiries yet.")
        return
    st.dataframe(log_df.sort_values("timestamp", ascending=False), use_container_width=True)
    st.download_button("⬇️ Download log as CSV", log_df.to_csv(index=False).encode("utf-8"),
                       file_name="clinic_log.csv", mime="text/csv")
    st.caption("Note: on Streamlit Cloud this file can reset when the app restarts.")


def dashboard_tab():
    st.subheader("Dashboard")
    log_df = load_log()
    if log_df.empty:
        st.info("No data yet.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Total enquiries", len(log_df))
    c2.metric("High urgency", int((log_df["urgency"] == "High").sum()))
    c3.metric("Pending review", int((log_df["status"] == "Pending review").sum()))

    st.markdown("**Enquiries by category**")
    st.bar_chart(log_df["category"].value_counts())

    st.markdown("**Enquiries by urgency**")
    order = ["High", "Medium", "Low"]
    st.bar_chart(log_df["urgency"].value_counts().reindex(order, fill_value=0))


def staff_view(demo: bool):
    tab_queue, tab_history, tab_dash = st.tabs(["📥 Review Queue", "📜 History", "📊 Dashboard"])
    with tab_queue:
        review_queue_tab(demo)
    with tab_history:
        history_tab()
    with tab_dash:
        dashboard_tab()


# ======================================================================
# MAIN: header, disclaimer, role selector
# ======================================================================
st.title("🏥 ClinicAssist AI")
st.caption("Patient Enquiry Auto-Triage & Reply System")
st.warning("⚠️ Demo only. Uses fake data. Not for real patient information. Not medical advice.")

DEMO = is_demo_mode()

role = st.sidebar.radio("I am a:", ["Patient", "Clinic Staff"])   # choose the view
if role == "Patient":
    st.session_state["staff_ok"] = False        # leaving staff area = logged out
    patient_view()
else:
    if staff_login():
        if st.sidebar.button("Log out"):
            st.session_state["staff_ok"] = False
            st.rerun()
        if DEMO:
            st.info("📧 DEMO MODE is ON: emails are previewed only and never sent.")
        staff_view(DEMO)

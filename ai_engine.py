# ai_engine.py
# ALL Gemini calls and ALL prompts live in this file.

import json                                   # to read the JSON that the AI returns
import re                                     # regular expressions, used to clean the AI text
import streamlit as st                        # used only to read st.secrets (API key)
import google.generativeai as genai           # official Gemini library
from google.api_core import exceptions as gexc  # error types from Google (rate limit etc.)

# ----------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------
DEFAULT_MODEL = "gemini-3.8-flash"            # model asked in the project brief
CATEGORIES = ["Appointment", "Reports", "Billing", "Prescription", "Emergency", "General"]
URGENCIES = ["High", "Medium", "Low"]

# ----------------------------------------------------------------------
# PROMPTS (named constants, so you can show and improve them in your video)
# ----------------------------------------------------------------------
TRIAGE_PROMPT = """You are a triage assistant for a medical clinic front desk.
Read the patient enquiry and classify it.

Return ONLY a valid JSON object. No markdown, no backticks, no extra text.
Use exactly this format:
{{"category": "...", "urgency": "...", "summary": "...", "reason": "..."}}

Rules:
- category must be exactly one of: Appointment, Reports, Billing, Prescription, Emergency, General
- urgency must be exactly one of: High, Medium, Low
- Use High urgency and category Emergency for any possible life-threatening symptom
  (chest pain, trouble breathing, severe bleeding, stroke signs, unconsciousness, etc.)
- summary: one short sentence describing what the patient wants
- reason: one short sentence explaining why you chose this category and urgency
- Do NOT diagnose and do NOT give medical advice.

Patient enquiry:
\"\"\"{enquiry}\"\"\"
"""

REPLY_PROMPT = """You are a polite front-desk assistant at a medical clinic.
Write a short, professional reply email to the patient enquiry below.

Context from triage:
- Category: {category}
- Urgency: {urgency}
- Summary: {summary}

Strict rules:
- Maximum 120 words. Start with a greeting and end with a courteous sign-off
  from "ClinicAssist Demo Clinic Team".
- NEVER give a medical diagnosis, medical advice, medicine names or dosages.
- Do not promise exact times, prices or refunds. Say the team will confirm shortly.
- Write only the email body. No subject line, no markdown.
{extra_rule}

Patient enquiry:
\"\"\"{enquiry}\"\"\"
"""

# Extra rule added to the reply prompt only when urgency is High or category is Emergency
EMERGENCY_RULE = (
    "- This may be an emergency. The reply MUST clearly tell the patient to call "
    "their local emergency services or go to the nearest hospital IMMEDIATELY, "
    "and not to wait for an email response."
)

# Safety sentence that is added by code if the AI forgets the emergency instruction
EMERGENCY_FALLBACK_LINE = (
    "\n\nIMPORTANT: If this is an emergency, please call your local emergency "
    "services or go to the nearest hospital immediately. Do not wait for our reply."
)

# Words used by the backup (fallback) triage if the AI fails twice
EMERGENCY_KEYWORDS = [
    "chest pain", "can't breathe", "cannot breathe", "difficulty breathing",
    "severe bleeding", "unconscious", "stroke", "seizure", "heart attack",
    "emergency", "suicide",
]


# ----------------------------------------------------------------------
# CUSTOM ERROR (so app.py can show a friendly message)
# ----------------------------------------------------------------------
class AIServiceError(Exception):
    """Raised when the AI service fails. The message is safe to show to users."""


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def _get_model(json_mode: bool = False):
    """Create the Gemini model object using the key stored in st.secrets."""
    try:
        api_key = st.secrets["GEMINI_API_KEY"]      # key comes from secrets, never hardcoded
    except Exception:
        raise AIServiceError(
            "Gemini API key not found. Add GEMINI_API_KEY in .streamlit/secrets.toml "
            "(local) or in the Streamlit Cloud Secrets box (deployed)."
        )
    try:
        model_name = st.secrets.get("GEMINI_MODEL", DEFAULT_MODEL)  # optional override
    except Exception:
        model_name = DEFAULT_MODEL
    genai.configure(api_key=api_key)                # give the key to the library
    config = {"temperature": 0.2 if json_mode else 0.5}  # low temperature = more consistent
    if json_mode:
        config["response_mime_type"] = "application/json"  # ask Gemini to return JSON only
    return genai.GenerativeModel(model_name, generation_config=config)


def _call_gemini(prompt: str, json_mode: bool = False) -> str:
    """Send a prompt to Gemini and return plain text. Converts errors to friendly ones."""
    try:
        model = _get_model(json_mode)
        response = model.generate_content(prompt)   # the actual API call
        return response.text                        # the text answer from the AI
    except AIServiceError:
        raise                                       # already friendly, pass it on
    except gexc.ResourceExhausted:                  # HTTP 429: too many requests / quota over
        raise AIServiceError("Rate limit reached. Please wait a minute and try again.")
    except gexc.NotFound:                           # wrong or retired model name
        raise AIServiceError(
            "The AI model name was not found. Set GEMINI_MODEL in secrets to a "
            "currently available Gemini Flash model."
        )
    except (gexc.PermissionDenied, gexc.Unauthenticated):  # bad API key
        raise AIServiceError("The Gemini API key looks invalid. Please check your secrets.")
    except Exception as err:                        # anything else (network, blocked content...)
        raise AIServiceError(f"The AI service is not available right now. ({type(err).__name__})")


def clean_json_text(text: str) -> str:
    """Remove ```json fences and extra words, keep only the {...} part."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()  # remove opening fence
    text = re.sub(r"```$", "", text).strip()                                # remove closing fence
    start, end = text.find("{"), text.rfind("}")    # find first { and last }
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]                  # keep only the JSON object
    return text


def _validate_triage(data: dict) -> dict:
    """Check the JSON has the right keys and allowed values. Raise ValueError if not."""
    for key in ("category", "urgency", "summary", "reason"):
        if key not in data:
            raise ValueError(f"Missing key: {key}")
    category = str(data["category"]).strip().title()
    urgency = str(data["urgency"]).strip().title()
    if category not in CATEGORIES or urgency not in URGENCIES:
        raise ValueError("Invalid category or urgency value")
    return {
        "category": category,
        "urgency": urgency,
        "summary": str(data["summary"]).strip(),
        "reason": str(data["reason"]).strip(),
    }


def _fallback_triage(enquiry: str) -> dict:
    """Backup triage if the AI output is unusable. Uses simple keyword matching."""
    lowered = enquiry.lower()
    if any(word in lowered for word in EMERGENCY_KEYWORDS):  # safety first
        return {"category": "Emergency", "urgency": "High",
                "summary": "Possible emergency symptoms mentioned.",
                "reason": "Fallback: emergency keyword found. Needs immediate human review."}
    return {"category": "General", "urgency": "Medium",
            "summary": "Enquiry could not be auto-classified.",
            "reason": "Fallback: AI output was invalid, so a staff member should review it."}


# ----------------------------------------------------------------------
# MAIN FUNCTIONS (used by app.py)
# ----------------------------------------------------------------------
def triage_enquiry(enquiry: str) -> dict:
    """Classify an enquiry. Retry once if JSON is bad, then use fallback."""
    prompt = TRIAGE_PROMPT.format(enquiry=enquiry)       # put the enquiry inside the prompt
    for attempt in range(2):                             # try at most 2 times
        raw = _call_gemini(prompt, json_mode=True)       # call Gemini
        try:
            data = json.loads(clean_json_text(raw))      # clean + convert text to dict
            result = _validate_triage(data)              # check the values
            result["used_fallback"] = False
            return result
        except (json.JSONDecodeError, ValueError):
            continue                                     # bad JSON, so retry once
    result = _fallback_triage(enquiry)                   # both attempts failed
    result["used_fallback"] = True
    return result


def draft_reply(enquiry: str, triage: dict) -> str:
    """Write a polite reply email. Adds a safety line for High urgency if missing."""
    is_urgent = triage["urgency"] == "High" or triage["category"] == "Emergency"
    prompt = REPLY_PROMPT.format(
        category=triage["category"],
        urgency=triage["urgency"],
        summary=triage["summary"],
        enquiry=enquiry,
        extra_rule=EMERGENCY_RULE if is_urgent else "",  # emergency rule only when needed
    )
    reply = _call_gemini(prompt).strip()                 # normal text mode
    if is_urgent and "emergency" not in reply.lower():   # double-check the safety message exists
        reply += EMERGENCY_FALLBACK_LINE
    return reply

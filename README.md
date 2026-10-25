# 🏥 ClinicAssist AI: Patient Enquiry Auto-Triage & Reply System

> ⚠️ Demo only. Uses fake data. Not for real patient information. Not medical advice.

## Project Overview
A clinic receives many patient enquiries. ClinicAssist AI reads each one, classifies it,
sets an urgency level, and drafts a polite reply for staff to review. Everything is logged.

## Features
- **Two separate views**
  - **Patient view:** only an enquiry form. After submitting, the patient sees a thank-you message
    (and an emergency warning if needed). No dashboard, no history, no AI results, no email option.
  - **Clinic Staff view (password protected):** review queue (High urgency first), urgency alerts,
    editable reply draft, email preview/send, history with CSV download, and dashboard charts.
- AI triage into 6 categories (Appointment, Reports, Billing, Prescription, Emergency, General)
- Urgency: High (red), Medium (orange), Low (green)
- Reply drafts never give medical advice; High urgency replies tell the patient to contact emergency services
- Safe JSON handling: strips markdown fences, retries once, then uses a rule-based fallback
- 10 fake sample enquiries
- Email sending is OFF by default (`DEMO_MODE = true`): staff only see an email preview

## Tech Stack
Python 3.10+, Streamlit, Google Gemini API (`google-generativeai`), pandas, smtplib

## Project Structure
| File | Purpose |
|---|---|
| `app.py` | Streamlit UI (patient view and staff view) |
| `ai_engine.py` | All Gemini calls and all prompts |
| `logger.py` | CSV logging with pandas, enquiry status |
| `sample_data.py` | 10 fake enquiries |
| `tests/test_regression.py` | 44 regression tests (fake AI, no API key needed) |
| `check_before_push.py` | Safety check before pushing to GitHub |

## Run Locally
```bash
python -m venv venv
venv\Scripts\activate            # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
mkdir .streamlit                 # skip if the folder already exists
copy .streamlit\secrets.toml.example .streamlit\secrets.toml     # Mac/Linux: cp ...
# open .streamlit/secrets.toml and fill in your real values (see "Secrets" below)
python -m streamlit run app.py
```

## Secrets
Put these in `.streamlit/secrets.toml` (local) or in the Streamlit Cloud **Secrets** box (deployed).
Never write them in any other file, and never push `secrets.toml` to GitHub.
```toml
GEMINI_API_KEY = "your-real-key"
GEMINI_MODEL = "gemini-3.8-flash"
STAFF_PASSWORD = "choose-a-strong-password"
DEMO_MODE = true
```
- `STAFF_PASSWORD`: if missing, the Clinic Staff area stays locked.
- Keep `DEMO_MODE = true` on the public link so no real emails are ever sent.
- Get a free Gemini key at aistudio.google.com.

## Push to a NEW GitHub repository
1. On github.com click **New repository**. Name it (for example `clinicassist-ai`), choose **Public**,
   and do NOT tick "Add a README" or ".gitignore". Click **Create repository**.
2. Open a terminal **inside this project folder** (the folder that directly contains `app.py`).
3. Run:
   ```bash
   git init
   git branch -M main
   git add .
   python check_before_push.py
   ```
   It must print `OK: ... No secrets found.` If it prints `NOT SAFE TO PUSH`, fix what it says first.
4. Then:
   ```bash
   git commit -m "ClinicAssist AI: patient and staff views"
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
5. Refresh the GitHub page. `app.py` must be visible at the top level of the repo
   (not inside another folder).

## Deploy on Streamlit Community Cloud
1. Go to **share.streamlit.io** and sign in with GitHub.
2. Click **Create app** and choose **Deploy a public app from GitHub**.
3. Repository: `<your-username>/<your-repo>`, Branch: `main`, Main file path: `app.py`.
4. Open **Advanced settings → Secrets** and paste the 4 secret lines from the "Secrets" section above.
5. Click **Deploy** and wait 1 to 2 minutes.
6. Open the public link. You should see the Patient form. Choose **Clinic Staff** in the sidebar
   and log in with your `STAFF_PASSWORD` to see the dashboard.

To update later: change files, then `git add .`, `python check_before_push.py`, `git commit -m "..."`,
`git push`. Streamlit Cloud redeploys automatically.

## Troubleshooting
| Message | Fix |
|---|---|
| "Gemini API key not found" | Add `GEMINI_API_KEY` in Secrets, then save and reboot the app |
| "AI model name was not found" | Set `GEMINI_MODEL` in Secrets to a model your key can use |
| "Staff area is locked" | Add `STAFF_PASSWORD` in Secrets |
| "Rate limit reached" | Wait a minute and try again |
| `ModuleNotFoundError` | Check that `requirements.txt` is in the repo root |
| "Main file does not exist" | `app.py` must be at the repo root; set Main file path to `app.py` |

## Screenshots
_Add screenshots here:_
- `screenshots/patient.png`: Patient view
- `screenshots/staff-queue.png`: Staff review queue
- `screenshots/dashboard.png`: Dashboard

## How AI Was Used
- **Gemini Flash** classifies enquiries (strict JSON prompt) and writes reply drafts (second prompt).
- Prompts are named constants at the top of `ai_engine.py`, so they can be improved easily.
- Safety layers: prompt rules, code that adds an emergency line if missing, keyword fallback.
- AI assistants were also used to help generate, review and test the project code.
- A human must always review AI output before it reaches a patient.

## Testing
```bash
pip install pytest
python -m pytest tests -v
```

## Limitations
Demo only, fake data only. The CSV log can reset when Streamlit Cloud restarts.
The staff password is a demo-level protection, not a full login system.

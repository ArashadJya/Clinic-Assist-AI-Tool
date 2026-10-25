# logger.py
# Saves every enquiry to a CSV file using pandas. Also keeps a "status" for each enquiry.

import os                       # to create folders and check if file exists
from datetime import datetime   # for the timestamp
import pandas as pd             # table handling

LOG_DIR = "data"                                  # folder for the log file
LOG_FILE = os.path.join(LOG_DIR, "clinic_log.csv")
COLUMNS = ["timestamp", "patient_email", "enquiry", "category",
           "urgency", "summary", "reply", "status"]
DEFAULT_STATUS = "Pending review"                 # every new enquiry starts here


def load_log() -> pd.DataFrame:
    """Read the whole log. Return an empty table if there is no log yet."""
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(LOG_FILE)
    except Exception:                             # broken or empty file
        return pd.DataFrame(columns=COLUMNS)
    df = df.reindex(columns=COLUMNS)              # old files with fewer columns still work
    df["status"] = df["status"].fillna(DEFAULT_STATUS)
    return df.fillna("")                          # empty cells become "" (easier to show)


def _write(df: pd.DataFrame) -> None:
    """Save the full table back to the CSV file."""
    os.makedirs(LOG_DIR, exist_ok=True)           # create data/ folder if missing
    df.to_csv(LOG_FILE, index=False)


def save_result(enquiry: str, triage: dict, reply: str, patient_email: str = "") -> None:
    """Add one new row to the CSV log."""
    df = load_log()                               # existing rows
    new_row = pd.DataFrame([{
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "patient_email": patient_email,
        "enquiry": enquiry,
        "category": triage["category"],
        "urgency": triage["urgency"],
        "summary": triage["summary"],
        "reply": reply,
        "status": DEFAULT_STATUS,
    }], columns=COLUMNS)
    df = new_row if df.empty else pd.concat([df, new_row], ignore_index=True)
    _write(df)


def update_status(row_index: int, status: str) -> None:
    """Change the status of one row (for example 'Reviewed' or 'Reply sent')."""
    df = load_log()
    if 0 <= row_index < len(df):                  # make sure the row exists
        df.loc[row_index, "status"] = status
        _write(df)

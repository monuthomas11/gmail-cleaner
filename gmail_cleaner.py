import imaplib
import json
import time
import sys
import os
from dotenv import load_dotenv

# Load variables from .env in the current directory (or parent tree)
load_dotenv()  # looks for a .env file automatically

EMAIL_USER = os.getenv("GMAIL_USER")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
BATCH_SIZE = 500          # delete 500 mails per batch
SLEEP_BETWEEN_BATCHES = 0.5


# Convert Gmail query → IMAP-compatible search
def gmail_to_imap(query):
    parts = query.split()
    imap_terms = []

    for p in parts:
        if p.startswith("from:"):
            imap_terms += ['FROM', p[5:]]
        elif p.startswith("subject:"):
            imap_terms += ['SUBJECT', p[8:]]
        elif p.startswith("to:"):
            imap_terms += ['TO', p[3:]]
        else:
            imap_terms += ['TEXT', p]

    return imap_terms


def load_filters():
    with open("filters.json", "r", encoding="utf-8") as f:
        return json.load(f)


def search_messages(imap, imap_query):
    search_string = " ".join(imap_query)
    status, data = imap.search(None, *search_string.split())

    if status != "OK":
        print("IMAP search failed:", data)
        return []

    ids = data[0].split()
    return ids


def delete_batch(imap, ids):
    if not ids:
        return 0

    str_ids = b",".join(ids)          # RFC compliant batch
    imap.store(str_ids, "+FLAGS", "\\Deleted")
    imap.expunge()
    return len(ids)


def process_filters(email_user, app_password):
    filters = load_filters()

    print("Connecting to Gmail IMAP...")
    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)

    imap.login(email_user, app_password)
    print("Login successful.")

    # 🔥 IMPORTANT — search entire Gmail mailbox
    imap.select('"[Gmail]/All Mail"')

    total_deleted = 0

    for flt in filters:
        query = flt["query"]
        actions = flt["actions"]

        if not actions.get("trash", False):
            print(f"Skipping filter (no trash action): {query}")
            continue

        print(f"\n=== FILTER: {query} ===")

        imap_query = gmail_to_imap(query)
        print("IMAP query:", imap_query)

        ids = search_messages(imap, imap_query)
        print(f"Found {len(ids)} messages")

        for i in range(0, len(ids), BATCH_SIZE):
            batch = ids[i:i + BATCH_SIZE]
            deleted = delete_batch(imap, batch)
            total_deleted += deleted
            print(f"Deleted batch: {deleted} emails (total {total_deleted})")

            time.sleep(SLEEP_BETWEEN_BATCHES)

    print("\n----------------------------------------------")
    print(f"✔ DONE. Total deleted: {total_deleted} emails")
    print("----------------------------------------------")

    imap.logout()


if __name__ == "__main__":
    try:
        print("Gmail IMAP Cleaner (Python 3.14 Safe)")

        # email_user = input("Enter Gmail address: ").strip()
        # app_password = input("Enter Gmail App Password: ").strip()

        email_user = EMAIL_USER
        app_password = APP_PASSWORD

        process_filters(email_user, app_password)

    except Exception as e:
        print("\nERROR:", e)
        sys.exit(1)

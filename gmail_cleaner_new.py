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

# Folders to search; this approximates "Mail & spam & trash"
MAILBOXES = [
    '"[Gmail]/All Mail"',
    '"[Gmail]/Spam"',
    '"[Gmail]/Trash"',
]


def load_filters(path="filters.json"):
    """Load filter definitions from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def search_with_xgmraw(imap, gmail_query: str):
    """
    Search using Gmail's X-GM-RAW so the query behaves like Gmail web search.
    IMPORTANT: pass 'X-GM-RAW' and the query as separate arguments.
    """
    results = []

    # Variant 1: standard form (separate args)
    try:
        status, data = imap.search(None, "X-GM-RAW", gmail_query)
        if status == 'OK' and data and data[0]:
            results = data[0].split()
            return results
    except Exception:
        pass

    # Variant 2: single criteria string including quotes
    try:
        crit = f'X-GM-RAW "{gmail_query}"'
        status, data = imap.search(None, crit)
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    # Variant 3: UID SEARCH (several argument shapes)
    try:
        status, data = imap.uid('SEARCH', None, 'X-GM-RAW', gmail_query)
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    try:
        status, data = imap.uid('SEARCH', 'X-GM-RAW', f'"{gmail_query}"')
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    # Last-resort: TEXT search
    try:
        status, data = imap.search(None, 'TEXT', gmail_query)
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    return []


def search_with_from(imap, gmail_query: str):
    """
    Fallback: if query is exactly 'from:address', use plain IMAP FROM search.
    """
    if not gmail_query.startswith("from:"):
        return []

    addr = gmail_query[len("from:"):].strip()
    status, data = imap.search(None, "FROM", addr)

    if status != "OK":
        return []

    ids = data[0].split()
    return ids


def search_messages_in_box(imap, mailbox: str, gmail_query: str):
    """
    Select a mailbox and run X-GM-RAW (with FROM fallback) inside it.
    Returns the list of IDs to delete in that mailbox.
    """
    status, data = imap.select(mailbox)
    if status != "OK":
        print(f"  [WARN] Failed to select {mailbox}, skipping.")
        return []

    ids = search_with_xgmraw(imap, gmail_query)
    if ids:
        return ids

    ids_from = search_with_from(imap, gmail_query)
    if ids_from:
        return ids_from

    return []


def delete_batch(imap, ids):
    """Mark a batch of messages as \\Deleted and expunge them."""
    if not ids:
        return 0
    # ids may be bytes or strings
    if isinstance(ids[0], bytes):
        msgset = b",".join(ids).decode()
    else:
        msgset = ",".join(ids)

    # First, try to COPY messages to Trash so they appear in Gmail's Trash folder
    trash_box = '"[Gmail]/Trash"'
    try:
        imap.copy(msgset, trash_box)
    except Exception:
        pass

    # Then mark as \Deleted and expunge in the currently selected mailbox
    try:
        status, _ = imap.store(msgset.encode(), "+FLAGS", "\\Deleted")
    except Exception:
        status = None

    if status != "OK":
        return 0

    imap.expunge()
    return len(ids)


def process_filters(email_user, app_password, filters_path="filters.json"):
    filters = load_filters(filters_path)
    print("Connecting to Gmail IMAP...")

    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(email_user, app_password)

    total_deleted = 0

    for flt in filters:
        query = flt.get("query", "").strip()
        actions = flt.get("actions", {})

        if not query:
            print("Skipping filter with empty query.")
            continue

        if not actions.get("trash", False):
            print(f"Skipping filter (no trash action): {query}")
            continue

        print(f"Filter: {query}")

        # Search in all configured mailboxes
        for mailbox in MAILBOXES:
            ids = search_messages_in_box(imap, mailbox, query)
            if not ids:
                continue

            for i in range(0, len(ids), BATCH_SIZE):
                batch = ids[i:i + BATCH_SIZE]
                deleted = delete_batch(imap, batch)
                total_deleted += deleted

                time.sleep(SLEEP_BETWEEN_BATCHES)
        
        print(f"  Deleted: {len(ids)} messages in {mailbox}")

    print("\\n----------------------------------------------")
    print(f"✔ DONE. Total deleted: {total_deleted} emails")
    print("----------------------------------------------")

    imap.logout()


if __name__ == "__main__":
    try:
        print("Gmail IMAP Cleaner (X-GM-RAW + multi-folder)")

        # email_user = input("Enter Gmail address: ").strip()
        # app_password = input("Enter Gmail App Password: ").strip()

        email_user = EMAIL_USER
        app_password = APP_PASSWORD

        if not email_user or not app_password:
            print("ERROR: Missing GMAIL_USER or GMAIL_APP_PASSWORD. Set them in .env or environment variables.")
            sys.exit(1)

        print(f"Starting cleanup (user: {email_user})...")

        process_filters(email_user, app_password)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print("\nERROR:", e)
        sys.exit(1)

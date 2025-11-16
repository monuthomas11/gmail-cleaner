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
    print(f"  [DEBUG] IMAP SEARCH (X-GM-RAW, query={gmail_query!r})")

    results = []

    # Variant 1: standard form (separate args)
    try:
        status, data = imap.search(None, "X-GM-RAW", gmail_query)
        print(f"    [VARIANT1] search None,'X-GM-RAW',query -> {status}, {data}")
        if status == 'OK' and data and data[0]:
            results = data[0].split()
            return results
    except Exception as e:
        print(f"    [VARIANT1] raised: {e}")

    # Variant 2: single criteria string including quotes
    try:
        crit = f'X-GM-RAW "{gmail_query}"'
        status, data = imap.search(None, crit)
        print(f"    [VARIANT2] search None,crit -> {status}, {data} (crit={crit!r})")
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception as e:
        print(f"    [VARIANT2] raised: {e}")

    # Variant 3: UID SEARCH (several argument shapes)
    try:
        status, data = imap.uid('SEARCH', None, 'X-GM-RAW', gmail_query)
        print(f"    [VARIANT3] uid SEARCH None,'X-GM-RAW',query -> {status}, {data}")
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception as e:
        print(f"    [VARIANT3] raised: {e}")

    try:
        status, data = imap.uid('SEARCH', 'X-GM-RAW', f'"{gmail_query}"')
        print(f"    [VARIANT4] uid SEARCH 'X-GM-RAW',quoted -> {status}, {data}")
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception as e:
        print(f"    [VARIANT4] raised: {e}")

    # Last-resort: TEXT search
    try:
        status, data = imap.search(None, 'TEXT', gmail_query)
        print(f"    [VARIANT5] TEXT search -> {status}, {data}")
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception as e:
        print(f"    [VARIANT5] raised: {e}")

    return []


def search_with_from(imap, gmail_query: str):
    """
    Fallback: if query is exactly 'from:address', use plain IMAP FROM search.
    """
    if not gmail_query.startswith("from:"):
        return []

    addr = gmail_query[len("from:"):].strip()
    print(f"  [DEBUG] IMAP SEARCH (FROM): {addr!r}")

    status, data = imap.search(None, "FROM", addr)
    print(f"  [DEBUG] FROM status: {status}, raw data: {data}")

    if status != "OK":
        return []

    ids = data[0].split()
    return ids


def search_messages_in_box(imap, mailbox: str, gmail_query: str):
    """
    Select a mailbox and run X-GM-RAW (with FROM fallback) inside it.
    Returns the list of IDs to delete in that mailbox.
    """
    print(f'\n[INFO] Selecting mailbox: {mailbox}')
    status, data = imap.select(mailbox)
    print(f"  [DEBUG] SELECT {mailbox}: {status}, {data}")
    if status != "OK":
        print(f"  [WARN] Failed to select {mailbox}, skipping.")
        return []

    ids = search_with_xgmraw(imap, gmail_query)
    if ids:
        print(f"  [INFO] X-GM-RAW in {mailbox} matched {len(ids)} messages")
        return ids

    print(f"  [INFO] X-GM-RAW in {mailbox} returned 0; trying plain FROM (if applicable)")
    ids_from = search_with_from(imap, gmail_query)
    if ids_from:
        print(f"  [INFO] FROM in {mailbox} matched {len(ids_from)} messages")
        return ids_from

    print(f"  [INFO] No messages matched in {mailbox}")
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

    print(f"  [DEBUG] Deleting message set: {msgset[:160]!r} ...")

    # First, try to COPY messages to Trash so they appear in Gmail's Trash folder
    trash_box = '"[Gmail]/Trash"'
    try:
        status_copy, data_copy = imap.copy(msgset, trash_box)
        print(f"  [DEBUG] COPY -> {trash_box}: {status_copy}, {data_copy}")
    except Exception as e:
        print(f"  [DEBUG] COPY to Trash raised: {e}")

    # Then mark as \Deleted and expunge in the currently selected mailbox
    try:
        status, _ = imap.store(msgset.encode(), "+FLAGS", "\\Deleted")
    except Exception:
        status = None

    if status != "OK":
        print("  [WARN] STORE failed for batch, skipping")
        return 0

    imap.expunge()
    return len(ids)


def process_filters(email_user, app_password, filters_path="filters.json"):
    filters = load_filters(filters_path)
    print("Connecting to Gmail IMAP...")

    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(email_user, app_password)
    print("Login successful.")
    # Print server capabilities for diagnostics
    try:
        caps = imap.capabilities
    except Exception:
        caps = None
    print(f"Server capabilities: {caps}")

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

        print(f"\n=== FILTER: {query} ===")

        # Search in all configured mailboxes
        for mailbox in MAILBOXES:
            ids = search_messages_in_box(imap, mailbox, query)
            print(f"Found {len(ids)} messages to delete in {mailbox}")

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
        print("Gmail IMAP Cleaner (X-GM-RAW + multi-folder)")

        # email_user = input("Enter Gmail address: ").strip()
        # app_password = input("Enter Gmail App Password: ").strip()

        email_user = EMAIL_USER
        app_password = APP_PASSWORD

        print(f"Using email user: {email_user}")

        process_filters(email_user, app_password)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print("\nERROR:", e)
        sys.exit(1)

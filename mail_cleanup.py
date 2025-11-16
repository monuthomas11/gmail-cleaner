#!/usr/bin/env python3
"""
Gmail IMAP Cleaner with Important Message Protection

1. Deletes emails matching filters (moves to Trash)
2. Restores important/starred messages from Trash to Inbox
3. Permanently deletes remaining trash

Uses .env for credentials:
  GMAIL_USER=you@gmail.com
  GMAIL_APP_PASSWORD=your_app_password
"""

import imaplib
import json
import time
import sys
import os
import re
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

EMAIL_USER = os.getenv("GMAIL_USER")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

BATCH_SIZE = 500
SLEEP_BETWEEN_BATCHES = 0.5

# Folders to search for deletion
MAILBOXES = [
    '"[Gmail]/All Mail"',
    '"[Gmail]/Spam"',
]


def load_filters(path="filters.json"):
    """Load filter definitions from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def connect_imap():
    """Connect and login to Gmail IMAP."""
    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(EMAIL_USER, APP_PASSWORD)
    return imap


def search_with_xgmraw(imap, gmail_query: str):
    """Search using Gmail's X-GM-RAW."""
    # Try multiple variants to ensure compatibility
    try:
        status, data = imap.search(None, "X-GM-RAW", gmail_query)
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    try:
        status, data = imap.uid('SEARCH', None, 'X-GM-RAW', gmail_query)
        if status == 'OK' and data and data[0]:
            return data[0].split()
    except Exception:
        pass

    return []


def search_with_from(imap, gmail_query: str):
    """Fallback: if query is 'from:address', use plain IMAP FROM search."""
    if not gmail_query.startswith("from:"):
        return []

    addr = gmail_query[len("from:"):].strip()
    status, data = imap.search(None, "FROM", addr)

    if status != "OK":
        return []

    return data[0].split()


def search_messages_in_box(imap, mailbox: str, gmail_query: str):
    """Select a mailbox and search for messages."""
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


def move_to_trash_batch(imap, ids):
    """Move messages to Trash."""
    if not ids:
        return 0

    if isinstance(ids[0], bytes):
        msgset = b",".join(ids).decode()
    else:
        msgset = ",".join(ids)

    trash_box = '"[Gmail]/Trash"'
    try:
        # COPY to Trash
        status, _ = imap.copy(msgset, trash_box)
        if status != 'OK':
            return 0
        
        # Mark as deleted in current mailbox
        status, _ = imap.store(msgset.encode(), "+FLAGS", "\\Deleted")
        if status != 'OK':
            return 0
        
        imap.expunge()
        return len(ids)
    except Exception as e:
        print(f"  [ERROR] Move to trash failed: {e}", file=sys.stderr)
        return 0


def step1_delete_matching_emails(imap, filters):
    """Step 1: Delete emails matching filters (move to Trash)."""
    print("\n" + "="*60)
    print("STEP 1: Moving filtered emails to Trash")
    print("="*60)

    total_moved = 0

    for flt in filters:
        query = flt.get("query", "").strip()
        actions = flt.get("actions", {})

        if not query:
            continue

        if not actions.get("trash", False):
            print(f"Skipping filter (no trash action): {query}")
            continue

        print(f"\nFilter: {query}")

        for mailbox in MAILBOXES:
            ids = search_messages_in_box(imap, mailbox, query)
            if not ids:
                continue

            moved_here = 0
            for i in range(0, len(ids), BATCH_SIZE):
                batch = ids[i:i + BATCH_SIZE]
                moved = move_to_trash_batch(imap, batch)
                moved_here += moved
                total_moved += moved
                time.sleep(SLEEP_BETWEEN_BATCHES)

            print(f"  Moved to Trash: {moved_here} messages from {mailbox}")

    print(f"\n✔ Step 1 complete: {total_moved} emails moved to Trash")
    return total_moved


def step2_restore_important_from_trash(imap):
    """Step 2: Restore important/starred messages from Trash to Inbox."""
    print("\n" + "="*60)
    print("STEP 2: Restoring important messages from Trash to Inbox")
    print("="*60)

    trash = '"[Gmail]/Trash"'
    
    # Select Trash
    typ, sel = imap.select(trash)
    if typ != 'OK':
        print("Unable to select Trash mailbox", file=sys.stderr)
        return 0

    # Search for important OR starred messages
    print('Searching Trash for important/starred messages...')
    
    # Try to find important messages
    important_uids = []
    try:
        typ, data = imap.uid('SEARCH', None, 'X-GM-RAW', 'is:important OR is:starred')
        if typ == 'OK' and data and data[0]:
            important_uids = data[0].split()
    except Exception:
        # Fallback: search separately
        try:
            typ1, data1 = imap.uid('SEARCH', None, 'X-GM-RAW', 'is:important')
            typ2, data2 = imap.uid('SEARCH', None, 'X-GM-RAW', 'is:starred')
            
            uids_set = set()
            if typ1 == 'OK' and data1 and data1[0]:
                uids_set.update(data1[0].split())
            if typ2 == 'OK' and data2 and data2[0]:
                uids_set.update(data2[0].split())
            
            important_uids = list(uids_set)
        except Exception as e:
            print(f"  [ERROR] Search failed: {e}", file=sys.stderr)
            return 0

    print(f"Found {len(important_uids)} important/starred messages in Trash")

    if not important_uids:
        return 0

    # Restore in batches
    RESTORE_BATCH_SIZE = 100
    restored = 0
    batch_index = 0

    while batch_index < len(important_uids):
        batch = important_uids[batch_index:batch_index + RESTORE_BATCH_SIZE]
        msgset = b','.join(batch).decode()
        
        try:
            # COPY back to INBOX
            typ, _ = imap.uid('COPY', msgset, 'INBOX')
            if typ != 'OK':
                print(f"  [WARN] Failed to copy batch {batch_index // RESTORE_BATCH_SIZE + 1}", 
                      file=sys.stderr)
                batch_index += RESTORE_BATCH_SIZE
                continue

            # Mark as deleted in Trash
            typ, _ = imap.uid('STORE', msgset, '+FLAGS', '(\\Deleted)')
            if typ == 'OK':
                restored += len(batch)
            
            batch_index += RESTORE_BATCH_SIZE
            
        except imaplib.IMAP4.abort as e:
            print(f"  [WARN] Connection error, reconnecting: {e}", file=sys.stderr)
            try:
                imap.logout()
            except:
                pass
            imap = connect_imap()
            imap.select(trash)
            # Retry same batch
            continue

    # Expunge deleted messages from Trash
    imap.expunge()
    
    print(f"✔ Step 2 complete: {restored} important messages restored to Inbox")
    return restored


def step3_permanently_delete_trash(imap):
    """Step 3: Permanently delete remaining messages in Trash."""
    print("\n" + "="*60)
    print("STEP 3: Permanently deleting remaining Trash")
    print("="*60)

    trash = '"[Gmail]/Trash"'
    
    # Select Trash
    typ, sel = imap.select(trash)
    if typ != 'OK':
        print("Unable to select Trash mailbox", file=sys.stderr)
        return 0

    # Get all messages in Trash
    typ, data = imap.uid('SEARCH', None, 'ALL')
    if typ != 'OK' or not data or not data[0]:
        print("No messages in Trash to delete")
        return 0

    all_uids = data[0].split()
    print(f"Found {len(all_uids)} messages in Trash to permanently delete")

    if not all_uids:
        return 0

    # Delete in batches
    deleted = 0
    for i in range(0, len(all_uids), BATCH_SIZE):
        batch = all_uids[i:i + BATCH_SIZE]
        msgset = b','.join(batch).decode()
        
        try:
            typ, _ = imap.uid('STORE', msgset, '+FLAGS', '(\\Deleted)')
            if typ == 'OK':
                deleted += len(batch)
            time.sleep(SLEEP_BETWEEN_BATCHES)
        except Exception as e:
            print(f"  [ERROR] Delete batch failed: {e}", file=sys.stderr)

    # Expunge to permanently delete
    imap.expunge()
    
    print(f"✔ Step 3 complete: {deleted} messages permanently deleted from Trash")
    return deleted


def main():
    if not EMAIL_USER or not APP_PASSWORD:
        print("ERROR: GMAIL_USER or GMAIL_APP_PASSWORD not set in .env")
        sys.exit(1)

    print("Gmail IMAP Cleaner (3-step with Important Protection)")
    print(f"User: {EMAIL_USER}\n")

    # Load filters
    filters = load_filters("filters.json")

    # Connect to Gmail
    print("Connecting to Gmail IMAP...")
    imap = connect_imap()
    print("Login successful.\n")

    try:
        # Step 1: Move filtered emails to Trash
        moved = step1_delete_matching_emails(imap, filters)

        # Step 2: Restore important messages from Trash
        restored = step2_restore_important_from_trash(imap)

        # Step 3: Permanently delete remaining trash
        deleted = step3_permanently_delete_trash(imap)

        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"Emails moved to Trash:        {moved}")
        print(f"Important emails restored:    {restored}")
        print(f"Emails permanently deleted:   {deleted}")
        print(f"Net emails deleted:           {moved - restored}")
        print("="*60)

    finally:
        try:
            imap.logout()
        except:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

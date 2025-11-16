#!/usr/bin/env python3
"""
restore_trash_mails.py

Move all Gmail messages marked Important from Trash back to Inbox using IMAP.
Uses .env for credentials:
  GMAIL_USER=you@gmail.com
  GMAIL_APP_PASSWORD=your_app_password
"""

import imaplib
import argparse
import re
import sys
import os
from dotenv import load_dotenv

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Load variables from .env in the current directory (or parent tree)
load_dotenv()  # looks for a .env file automatically

EMAIL_USER = os.getenv("GMAIL_USER")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def connect_imap(host, port, email_user, app_password):
    """Connect and login to IMAP."""
    imap = imaplib.IMAP4_SSL(host, port)
    imap.login(email_user, app_password)
    return imap


def choose_trash_mailbox(imap):
    """
    Try common Gmail trash mailbox names; fall back to the first mailbox
    that contains 'trash' (case-insensitive), else 'Trash'.
    """
    candidates = [b'[Gmail]/Trash', b'Trash', b'[Google Mail]/Trash',
                  b'[Gmail]/Bin', b'Bin']
    try:
        typ, mailboxes = imap.list()
        if typ != 'OK':
            return b'Trash'
        names = []
        for m in mailboxes:
            if not m:
                continue
            try:
                parts = m.decode(errors='ignore')
            except Exception:
                parts = str(m)
            # mailbox name usually after last space; get substring between
            # quotes or last token
            mname = None
            q = re.findall(r'"([^"]+)"', parts)
            if q:
                mname = q[-1].encode()
            else:
                tokens = parts.split()
                if tokens:
                    mname = tokens[-1].encode()
            if mname:
                names.append(mname)
        # prefer exact candidates
        for c in candidates:
            if c in names:
                return c
        # otherwise pick any that contains 'trash' (case-insensitive)
        for n in names:
            if b'trash' in n.lower():
                return n
    except Exception:
        pass
    return b'Trash'


def main():
    parser = argparse.ArgumentParser(
        description="Restore Important messages from Gmail Trash to Inbox."
    )
    parser.add_argument(
        '--host', default=IMAP_HOST, help='IMAP host (default imap.gmail.com)'
    )
    parser.add_argument(
        '--port', type=int, default=IMAP_PORT, help='IMAP port (default 993)'
    )
    parser.add_argument(
        '--no-expunge',
        action='store_true',
        help='Do not expunge after marking Deleted (for dry-run)',
    )
    args = parser.parse_args()

    email_user = EMAIL_USER
    app_password = APP_PASSWORD

    if not email_user or not app_password:
        print("ERROR: GMAIL_USER or GMAIL_APP_PASSWORD not set in .env",
              file=sys.stderr)
        sys.exit(1)

    # initial connect
    imap = connect_imap(args.host, args.port, email_user, app_password)

    try:
        trash = choose_trash_mailbox(imap).decode()
        print("Using Trash mailbox:", trash)

        # select Trash
        typ, sel = imap.select(f'"{trash}"')
        if typ != 'OK':
            typ, sel = imap.select(trash)
        if typ != 'OK':
            print("Unable to select Trash mailbox:", typ, sel, file=sys.stderr)
            imap.logout()
            sys.exit(1)

        # Search Important messages in Trash using Gmail's X-GM-RAW
        print('Searching Trash for important messages via X-GM-RAW "is:important"...')
        typ, data = imap.uid('SEARCH', None, 'X-GM-RAW', 'is:important')
        if typ != 'OK':
            print("UID SEARCH X-GM-RAW failed:", typ, data, file=sys.stderr)
            imap.logout()
            sys.exit(1)

        important_uids = data[0].split() if data and data[0] else []
        print(f"Important messages in Trash: {len(important_uids)}")

        if not important_uids:
            print("No Important messages found in Trash.")
            imap.logout()
            return

        # Batch copy + retry on IMAP4.abort (Gmail 'System Error')
        BATCH_SIZE = 100
        restored = 0
        batch_index = 0

        while batch_index < len(important_uids):
            batch = important_uids[batch_index:batch_index + BATCH_SIZE]
            msgset = b','.join(batch).decode()
            print(f"Processing batch {batch_index // BATCH_SIZE + 1}: "
                  f"{len(batch)} messages")

            try:
                # COPY batch to INBOX
                typ, copy_resp = imap.uid('COPY', msgset, 'INBOX')
                if typ != 'OK':
                    print(f"Failed to copy batch "
                          f"{batch_index // BATCH_SIZE + 1} to INBOX: "
                          f"{copy_resp}", file=sys.stderr)
                    batch_index += BATCH_SIZE
                    continue

                # mark originals in Trash as Deleted
                typ, store_resp = imap.uid('STORE', msgset, '+FLAGS',
                                           '(\\Deleted)')
                if typ != 'OK':
                    print(f"Failed to mark batch "
                          f"{batch_index // BATCH_SIZE + 1} Deleted: "
                          f"{store_resp}", file=sys.stderr)
                    batch_index += BATCH_SIZE
                    continue

                restored += len(batch)
                batch_index += BATCH_SIZE

            except imaplib.IMAP4.abort as e:
                # Gmail sent BYE System Error; reconnect and resume
                print(f"IMAP abort during COPY/STORE: {e}, "
                      f"reconnecting and resuming...", file=sys.stderr)
                try:
                    imap.logout()
                except Exception:
                    pass

                imap = connect_imap(args.host, args.port, email_user,
                                    app_password)
                trash = choose_trash_mailbox(imap).decode()
                typ, sel = imap.select(f'"{trash}"')
                if typ != 'OK':
                    typ, sel = imap.select(trash)
                if typ != 'OK':
                    print("Re-select Trash failed after reconnect:",
                          typ, sel, file=sys.stderr)
                    break
                # continue loop with same batch_index; some messages
                # in this batch may already have been copied

        if restored:
            if not args.no_expunge:
                imap.expunge()
                print(f"Restored {restored} messages and expunged Trash.")
            else:
                print(f"Restored {restored} messages "
                      f"(Trash not expunged due to --no-expunge).")
        else:
            print("No messages restored (all COPY/STORE operations failed).")

    finally:
        try:
            imap.logout()
        except Exception:
            pass


if __name__ == '__main__':
    main()

import imaplib
import getpass
import argparse
import re
import sys
import os
from dotenv import load_dotenv

# Load variables from .env in the current directory (or parent tree)
load_dotenv()  # looks for a .env file automatically

EMAIL_USER = os.getenv("GMAIL_USER")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

#!/usr/bin/env python3
"""
restore_trash_mails.py

Move all Gmail messages marked Important from Trash back to Inbox using IMAP.

Usage:
    python restore_trash_mails.py --user you@gmail.com
    (Password is prompted interactively. Use an App Password or OAuth2 token as required.)
"""


IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

def choose_trash_mailbox(imap):
        # Try common Gmail trash mailbox names; fall back to first mailbox that contains "trash"
        candidates = [b'[Gmail]/Trash', b'Trash', b'[Google Mail]/Trash', b'[Gmail]/Bin', b'Bin']
        try:
                typ, mailboxes = imap.list()
                if typ != 'OK':
                        return b'Trash'
                names = []
                for m in mailboxes:
                        if not m: 
                                continue
                        try:
                                # m example: b'(\\HasNoChildren) "/" "[Gmail]/Trash"'
                                parts = m.decode(errors='ignore')
                        except Exception:
                                parts = str(m)
                        # mailbox name usually after last space
                        # get substring between the last pair of quotes, or last token
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
                # otherwise pick any that contains 'trash' case-insensitive
                for n in names:
                        if b'trash' in n.lower():
                                return n
        except Exception:
                pass
        return b'Trash'

def parse_x_gm_labels(fetch_data):
        # fetch_data: raw bytes content from FETCH response; return list of labels
        labels = []
        if not fetch_data:
                return labels
        # decode to string
        s = None
        if isinstance(fetch_data, bytes):
                s = fetch_data.decode(errors='ignore')
        else:
                s = str(fetch_data)
        m = re.search(r'X-GM-LABELS \((.*?)\)', s)
        if not m:
                return labels
        inner = m.group(1).strip()
        # split but keep quoted tokens intact
        parts = re.findall(r'"([^"]+)"|\\[^\s()]+|[^\s()]+', inner)
        for p in parts:
                if isinstance(p, tuple):
                        # unlikely, but handle
                        p = next((x for x in p if x), '')
                labels.append(p)
        # normalize labels to simple strings
        labels = [lbl.strip().strip('"') for lbl in labels if lbl is not None]
        return labels

def main():
        parser = argparse.ArgumentParser(description="Restore Important messages from Gmail Trash to Inbox.")
        parser.add_argument('--user', '-u', required=False, help='Gmail address (or set GMAIL_USER / EMAIL_USER in .env)')
        parser.add_argument('--host', default=IMAP_HOST, help='IMAP host (default imap.gmail.com)')
        parser.add_argument('--port', type=int, default=IMAP_PORT, help='IMAP port (default 993)')
        parser.add_argument('--no-expunge', action='store_true', help='Do not expunge after marking Deleted (for dry-run)')
        args = parser.parse_args()

       

        # Determine user and password: prefer CLI args, then env vars, then prompt for password
        email_user = EMAIL_USER
        app_password = APP_PASSWORD

        imap = imaplib.IMAP4_SSL(args.host, args.port)
        try:
                typ, data = imap.login(email_user, app_password)
        except imaplib.IMAP4.error as e:
                print("Login failed:", e, file=sys.stderr)
                imap.logout()
                sys.exit(1)

        trash = choose_trash_mailbox(imap).decode()
        print("Using Trash mailbox:", trash)

        typ, sel = imap.select(f'"{trash}"')
        if typ != 'OK':
                # try without quotes
                typ, sel = imap.select(trash)
        if typ != 'OK':
                print("Unable to select Trash mailbox:", typ, sel, file=sys.stderr)
                imap.logout()
                sys.exit(1)

        # Get all message UIDs in Trash
        typ, data = imap.uid('SEARCH', None, 'ALL')
        if typ != 'OK':
                print("UID SEARCH failed", file=sys.stderr)
                imap.logout()
                sys.exit(1)

        uids = []
        if data and data[0]:
                uids = data[0].split()
        print(f"Found {len(uids)} messages in Trash")

        important_uids = []
        # Increase socket timeout to avoid long blocking reads
        try:
                if hasattr(imap, 'sock') and imap.sock is not None:
                        imap.sock.settimeout(120)  # seconds
        except Exception:
                pass

        # Fetch X-GM-LABELS in batches to avoid per-UID roundtrips which can timeout
        BATCH_SIZE = 200
        idx = 0
        while idx < len(uids):
                batch = uids[idx:idx + BATCH_SIZE]
                idx += BATCH_SIZE
                # compose message set like "1,2,3"
                if isinstance(batch[0], bytes):
                        msgset = b','.join(batch).decode()
                else:
                        msgset = ','.join(batch)

                try:
                        typ, fetch_data = imap.uid('FETCH', msgset, '(X-GM-LABELS)')
                except (TimeoutError, OSError) as e:
                        print(f"Timeout/network error during FETCH: {e}. Attempting one reconnect and retry.", file=sys.stderr)
                        # attempt a single reconnect and retry this batch
                        try:
                                imap.logout()
                        except Exception:
                                pass
                        try:
                                imap = imaplib.IMAP4_SSL(args.host, args.port)
                                if imap:
                                        typ_login, data_login = imap.login(email_user, app_password)
                                        # re-select trash mailbox
                                        trash = choose_trash_mailbox(imap).decode()
                                        imap.select(f'"{trash}"')
                                        if hasattr(imap, 'sock') and imap.sock is not None:
                                                imap.sock.settimeout(120)
                                        typ, fetch_data = imap.uid('FETCH', msgset, '(X-GM-LABELS)')
                        except Exception as e2:
                                print(f"Reconnect/retry failed: {e2}", file=sys.stderr)
                                continue

                if typ != 'OK' or not fetch_data:
                        # nothing useful returned for this batch
                        continue

                # parse returned parts for each message by joining all returned bytes
                blob = b''
                for part in fetch_data:
                        if isinstance(part, tuple):
                                blob += part[0] + b' '
                        elif isinstance(part, bytes):
                                blob += part + b' '

                text = blob.decode(errors='ignore')

                # Find per-message X-GM-LABELS blocks: capture UID and the inner labels text
                # Examples to match: 123 (X-GM-LABELS (\Important))
                for m in re.finditer(r"(\d+)\s+\([^)]*?X-GM-LABELS\s+\((.*?)\)\)", text, flags=re.IGNORECASE | re.DOTALL):
                        uid_str = m.group(1)
                        labels_inner = m.group(2)
                        # parse tokens: quoted labels, backslash labels (\Important), or bare tokens
                        tokens = re.findall(r'"([^\"]+)"|\\[^\s()]+|[^\s()]+', labels_inner)
                        # normalize tokens and check for 'important'
                        labels = [t for t in (tok if isinstance(tok, str) else tok for tok in tokens) if t]
                        for lbl in labels:
                                ln = lbl.lower().lstrip('\\')
                                if 'important' == ln or 'important' in ln:
                                        important_uids.append(uid_str.encode())
                                        break

        print(f"Important messages in Trash: {len(important_uids)}")

        if not important_uids:
                imap.logout()
                return

        restored = 0
        for uid in important_uids:
                # COPY to INBOX
                typ, copy_resp = imap.uid('COPY', uid, 'INBOX')
                if typ != 'OK':
                        print(f"Failed to copy UID {uid.decode()} to INBOX: {copy_resp}", file=sys.stderr)
                        continue
                # mark as Deleted in Trash mailbox so it is removed from Trash after expunge
                typ, store_resp = imap.uid('STORE', uid, '+FLAGS', '(\\Deleted)')
                if typ != 'OK':
                        print(f"Failed to mark UID {uid.decode()} Deleted: {store_resp}", file=sys.stderr)
                        continue
                restored += 1

        if restored:
                if not args.no_expunge:
                        imap.expunge()
                        print(f"Restored {restored} messages and expunged Trash.")
                else:
                        print(f"Restored {restored} messages (Trash not expunged due to --no-expunge).")
        else:
                print("No messages restored.")

        imap.logout()

if __name__ == '__main__':
        main()
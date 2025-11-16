# gmail_cleaner_new.py

**Purpose**
- `gmail_cleaner_new.py` is a small IMAP-based "cleaner" that searches for messages that match filters defined in `filters.json` and deletes them (moves to Trash and expunges) in batches.

**What it does**
- Connects to Gmail IMAP (`imap.gmail.com:993`).
- Loads filter definitions from `filters.json` (an array of filter objects).
- For each filter with `actions.trash == true`, it searches multiple mailboxes (configurable) using Gmail's `X-GM-RAW` search so the query behaves like Gmail web search.
- When matches are found it copies messages to Trash (best-effort), marks them `\Deleted` and calls `EXPUNGE` in batches.
- Prints diagnostic/debug info about searches, server capabilities and progress.

**Key configuration (in the script)**
- `IMAP_SERVER`, `IMAP_PORT` — IMAP host/port (default: `imap.gmail.com`, `993`).
- `MAILBOXES` — list of mailboxes to search, defaults to `"[Gmail]/All Mail"`, `"[Gmail]/Spam"`, `"[Gmail]/Trash"`.
- `BATCH_SIZE` — how many messages to mark/delete per batch (default: `500`).
- `SLEEP_BETWEEN_BATCHES` — pause between batches (default: `0.5` seconds).
- Credentials: the script currently sets `email_user` and `app_password` near the bottom. Update these before running (or use one of the suggested safer approaches below).

**filters.json format**
- The script expects `filters.json` to be a JSON array where each element is an object with at least a `query` string and an `actions` object. Example:

```json
[
  {
    "query": "from:news@example.com",
    "actions": { "trash": true }
  },
  {
    "query": "subject:Invoice",
    "actions": { "trash": true }
  }
]
```

- `query` is a Gmail-style query (e.g. `from:`, `label:`, `subject:`, free text). The script uses `X-GM-RAW` to more closely match Gmail's web search behavior, and falls back to a plain `FROM` search for queries of the form `from:address`.

**Safety notes**
- This script permanently deletes messages by using `EXPUNGE`. Test carefully on a non-critical account or by making a small controlled test filter first.
- Do not commit real credentials. Prefer using an App Password for accounts with 2FA.

**Run examples (PowerShell)**
1) Quick run (edit credentials in-file)
- Open `gmail_cleaner_new.py` and update these lines near the bottom:

```python
email_user = "you@example.com"
app_password = "your-app-password"
```

- Run:

```powershell
python .\gmail_cleaner_new.py
```

2) Run without editing the file (temporary run via Python `-c` call)
- This imports the module and calls `process_filters()` with your credentials directly. Useful for one-off runs without editing the file.

```powershell
python -c "import gmail_cleaner_new as g; g.process_filters('you@example.com','your-app-password')"
```

Note: quoting is important in PowerShell. If your password contains special characters, wrap arguments appropriately or use a short wrapper script.

3) Safer: modify the script to read credentials from environment variables
- Example change (replace hard-coded variables near the bottom):

```python
import os
email_user = os.environ.get('GMAIL_USER')
app_password = os.environ.get('GMAIL_APP_PASSWORD')
```

- Then run in PowerShell:

```powershell
$env:GMAIL_USER = 'you@example.com'; $env:GMAIL_APP_PASSWORD = 'your-app-password'; python .\gmail_cleaner_new.py
```

This avoids keeping credentials in the repository.

**Troubleshooting**
- Authentication errors: ensure IMAP is enabled in Gmail settings and use an App Password if 2FA is enabled.
- No matches for a filter: try the same query in Gmail web UI to confirm results; `X-GM-RAW` aims to mirror that behavior.
- Folder names: Gmail folder names can vary by language; use the IMAP `LIST` command to discover mailbox names if `"[Gmail]/Trash"` cannot be selected.
- Server capabilities: the script prints `imap.capabilities` at login for debugging.

**Suggested improvements (future)**
- Add a `--dry-run` flag to list matches without deleting.
- Add CLI arguments for credentials and filters path.
- Read credentials from a config file or environment variables by default.
- Add logging to a file and better retry/backoff for transient network issues.

**Location**
- Script: `gmail_cleaner_new.py`
- Filters: `filters.json` (expected in the same directory)

---

If you want, I can add a `--dry-run` option and a small CLI wrapper next (I can implement environment-variable credentials reading too). Which would you like next?
import json
from imapclient import IMAPClient
import sys
import traceback
import time

# -----------------------------
# CONFIG
# -----------------------------
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
BATCH_SIZE = 500     # delete 500 emails per IMAP request (safe + fast)
WAIT_BETWEEN_BATCHES = 0.5  # seconds

# -----------------------------
# HELPER: Convert Gmail search to IMAP search
# -----------------------------
def gmail_to_imap(query):
    """
    Supports only simple Gmail filters of pattern:
    from:xyz, subject:abc, to:someone
    """

    parts = query.split()
    imap_terms = []

    for p in parts:
        if p.startswith("from:"):
            imap_terms += ["FROM", p[5:]]
        elif p.startswith("subject:"):
            imap_terms += ["SUBJECT", p[8:]]
        elif p.startswith("to:"):
            imap_terms += ["TO", p[3:]]
        else:
            # fallback to text search
            imap_terms += ["TEXT", p]

    return imap_terms

# -----------------------------
# Load Filters JSON
# -----------------------------
def load_filters(path="filters.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# -----------------------------
# Main IMAP logic
# -----------------------------
def process_filters(email_user, app_password):
    filters = load_filters()

    print(f"Connecting to Gmail IMAP as {email_user} ...")
    with IMAPClient(IMAP_SERVER, port=IMAP_PORT, ssl=True) as server:
        server.login(email_user, app_password)
        print("Login successful.")

        server.select_folder("INBOX")

        total_deleted = 0

        for flt in filters:
            query = flt["query"]
            actions = flt["actions"]

            if "trash" not in actions or actions["trash"] is not True:
                print(f"Skipping filter (not trashing): {query}")
                continue

            print(f"\n=== FILTER: {query} ===")
            imap_query = gmail_to_imap(query)

            print("Searching IMAP for:", imap_query)
            msg_ids = server.search(imap_query)

            print(f"Found {len(msg_ids)} messages.")

            # Batch deletion
            for i in range(0, len(msg_ids), BATCH_SIZE):
                batch = msg_ids[i:i+BATCH_SIZE]

                print(f"Deleting batch {i//BATCH_SIZE + 1} "
                      f"({len(batch)} messages)...")

                # IMAP delete
                server.add_flags(batch, [r"\Deleted"])
                server.expunge()

                total_deleted += len(batch)
                time.sleep(WAIT_BETWEEN_BATCHES)

        print("\n-----------------------------------------")
        print(f"✔ DONE. Total deleted: {total_deleted} emails")
        print("-----------------------------------------")


# -----------------------------
# Entry point
# -----------------------------
if __name__ == "__main__":
    try:
        print("Gmail IMAP Cleaner")

        # email_user = input("Enter Gmail address: ").strip()
        # app_password = input("Enter Gmail App Password: ").strip()

        email_user = "monuthomas123@gmail.com"
        app_password = "crrb foxa anfx xnjm"

        process_filters(email_user, app_password)

    except Exception as e:
        print("\n‼ ERROR occurred:")
        print(str(e))
        traceback.print_exc()
        sys.exit(1)

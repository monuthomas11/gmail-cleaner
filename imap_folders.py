import imaplib
import os
from dotenv import load_dotenv

# Load variables from .env in the current directory (or parent tree)
load_dotenv()  # looks for a .env file automatically

EMAIL_USER = os.getenv("GMAIL_USER")
APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

email_user = EMAIL_USER
app_password = APP_PASSWORD

imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
imap.login(email_user, app_password)

print("\n=== Your IMAP folders ===")
status, folders = imap.list()

for f in folders:
    print(f.decode())

imap.logout()

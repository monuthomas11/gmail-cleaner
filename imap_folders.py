import imaplib

email_user = "monuthomas123@gmail.com"
app_password = "crrb foxa anfx xnjm"

imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
imap.login(email_user, app_password)

print("\n=== Your IMAP folders ===")
status, folders = imap.list()

for f in folders:
    print(f.decode())

imap.logout()

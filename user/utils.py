from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from datetime import datetime
from common.logging_config import logger


def get_gmail_service(creds_json):
    logger.info("Initializing Gmail service client.")
    creds = Credentials.from_authorized_user_info(creds_json)
    return build("gmail", "v1", credentials=creds)

def fetch_recent_emails(account, query="subject:(transaction OR payment)", max_results=10):
    logger.info(f"Fetching recent emails for account: {account.email_address}")

    try:
        service = get_gmail_service(account.creds)
        logger.debug(f"Gmail service initialized for {account.email_address}")

        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = results.get("messages", [])
        logger.info(f"Found {len(messages)} messages for {account.email_address}")

        emails = []
        for i, m in enumerate(messages, start=1):
            try:
                msg = service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()
                headers = msg["payload"].get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "")
                snippet = msg.get("snippet", "")
                emails.append({
                    "account": account.email_address,
                    "subject": subject,
                    "from": sender,
                    "snippet": snippet,
                })
                logger.debug(f"[{i}/{len(messages)}] Processed email: {subject[:60]}")
            except Exception as inner_e:
                logger.warning(f"Error fetching message {m['id']} for {account.email_address}: {inner_e}")

        account.last_synced_at = datetime.now()
        account.save(update_fields=["last_synced_at"])
        logger.info(f"Updated last_synced_at for {account.email_address}")

        return emails

    except Exception as e:
        logger.exception(f"Failed to fetch emails for {account.email_address}: {e}")
        raise

def fetch_all_user_emails(user, query="", max_results=100):
    logger.info(f"Starting email fetch for user: {user}")
    all_emails = []

    for acc in user.gmailaccount_created.filter(active=True):
        logger.info(f"Processing Gmail account: {acc.email_address}")
        try:
            account_emails = fetch_recent_emails(acc, query, max_results)
            logger.info(f"Fetched {len(account_emails)} emails for {acc.email_address}")
            all_emails.extend(account_emails)
        except Exception as e:
            logger.error(f"Error fetching from {acc.email_address}: {e}")
            all_emails.append({
                "account": acc.email_address,
                "error": str(e)
            })

    logger.info(f"Completed fetching emails for {user}. Total: {len(all_emails)} emails")
    return all_emails

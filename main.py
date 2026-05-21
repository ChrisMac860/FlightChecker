import html
import imaplib
import json
import os
import re
import sys
import urllib.request
import email
from email.header import decode_header


def get_env(name, required=True, default=None):
    value = os.getenv(name, default)
    if required and not value:
        print(f"ERROR: missing required environment variable {name}")
        sys.exit(1)
    return value


def decode_mime_header(value):
    if not value:
        return ""
    decoded = decode_header(value)
    parts = []
    for part, charset in decoded:
        if isinstance(part, bytes):
            try:
                part = part.decode(charset or "utf-8", errors="replace")
            except Exception:
                part = part.decode("utf-8", errors="replace")
        parts.append(part)
    return "".join(parts)


def extract_text(message):
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/html" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    return html_to_text(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return ""
    payload = message.get_payload(decode=True)
    if not payload:
        return ""
    return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


def html_to_text(html_body):
    body = re.sub(r"<style.*?>.*?</style>", "", html_body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    return re.sub(r"\s+", " ", body).strip()


def parse_alert(subject, body):
    combined = f"{subject}\n{body}"
    price_match = re.search(r"(?<!\d)(?:US\$|\$|USD\s?)(\d{2,4}(?:[.,]\d{2})?)", combined, re.I)
    price = price_match.group(0) if price_match else None

    route_match = re.search(
        r"\b([A-Z]{2,3}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*(?:→|->|—|-|to)\s*([A-Z]{2,3}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\b",
        combined,
        re.I,
    )
    if route_match:
        route = f"{route_match.group(1).strip()} → {route_match.group(2).strip()}"
    else:
        route = None

    if not route:
        route_match = re.search(
            r"from\s+([A-Z]{2,3}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+to\s+([A-Z]{2,3}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)",
            combined,
            re.I,
        )
        if route_match:
            route = f"{route_match.group(1).strip()} → {route_match.group(2).strip()}"

    summary = []
    if route:
        summary.append(route)
    if price:
        summary.append(price)
    return summary


def send_telegram_message(token, chat_id, text):
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"Telegram send failed: {result}")
    return result


def select_label_mailbox(imap_conn, label):
    try:
        status, _ = imap_conn.select(f'"{label}"')
        if status == "OK":
            return True
    except imaplib.IMAP4.error:
        pass
    return False


def main():
    gmail_user = get_env("GMAIL_USER")
    gmail_password = get_env("GMAIL_APP_PASSWORD")
    gmail_label = get_env("GMAIL_LABEL", required=False, default="Travel/FlightAlerts")
    telegram_token = get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = get_env("TELEGRAM_CHAT_ID")

    print("Connecting to Gmail IMAP...")
    imap_conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap_conn.login(gmail_user, gmail_password)

    selected_label = select_label_mailbox(imap_conn, gmail_label)
    if selected_label:
        status, data = imap_conn.search(None, "UNSEEN")
    else:
        print(f"Warning: could not select mailbox '{gmail_label}'. Falling back to INBOX search with label filter.")
        imap_conn.select("INBOX")
        status, data = imap_conn.search(None, "UNSEEN", "X-GM-LABELS", f'"{gmail_label}"')

    if status != "OK":
        raise RuntimeError("Failed to search for unread messages")

    message_ids = data[0].split() if data and data[0] else []
    if not message_ids:
        print("No new flight alerts found.")
        imap_conn.logout()
        return

    print(f"Found {len(message_ids)} unread message(s) in label '{gmail_label}'.")
    for num in message_ids:
        num_str = num.decode("utf-8") if isinstance(num, bytes) else str(num)
        status, msg_data = imap_conn.fetch(num, "(RFC822)")
        if status != "OK":
            print(f"Skipping message {num_str}: fetch failed.")
            continue

        raw_email = msg_data[0][1]
        message = email.message_from_bytes(raw_email)
        subject = decode_mime_header(message.get("Subject"))
        from_header = decode_mime_header(message.get("From"))
        body = extract_text(message)

        alert_parts = parse_alert(subject, body)
        summary = " | ".join(alert_parts) if alert_parts else "New flight alert found"
        message_text = (
            f"✈️ Flight Alert\n"
            f"Subject: {subject or 'No subject'}\n"
            f"From: {from_header or 'Unknown'}\n"
            f"Label: {gmail_label}\n"
            f"Summary: {summary}\n"
        )
        if body:
            snippet = body.strip().replace("\n", " ")[:400]
            message_text += f"\nSnippet: {snippet}"

        print(f"Sending Telegram notification for message {num_str}...")
        send_telegram_message(telegram_token, telegram_chat_id, message_text)
        imap_conn.store(num, "+FLAGS", "\\Seen")
        print(f"Marked message {num_str} as read.")

    imap_conn.logout()
    print("Done.")


if __name__ == "__main__":
    main()

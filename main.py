import html
import imaplib
import json
import os
import re
import sys
import urllib.request
import email
import calendar
import datetime as dt
from email.header import decode_header


def get_env(name, required=True, default=None):
    value = os.getenv(name)
    if value:
        return value.strip()
    if default is not None:
        return default
    if required:
        print(f"ERROR: missing required environment variable {name}")
        sys.exit(1)
    return value


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def normalize_gmail_app_password(password):
    return re.sub(r"\s+", "", password)


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


PRICE_RE = r"(?:US\$|USD\s?|\$|\u00a3|GBP\s?|\u20ac|EUR\s?)\s?\d{2,4}(?:[.,]\d{2})?"
DAY_RE = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
DATE_RANGE_RE = (
    rf"{DAY_RE}\s+\d{{1,2}}\s+[A-Z][a-z]{{2}}\s*[-\u2013]\s*"
    rf"{DAY_RE}\s+\d{{1,2}}\s+[A-Z][a-z]{{2}}"
)
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
MIN_NIGHTS = 2
MAX_DAYS_OFF = 1


def normalize_alert_text(value):
    value = re.sub(r"\(https?://\S+\)", "", value)
    value = re.sub(r"https?://\S+", "", value)
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value).strip()


def clean_place(value):
    value = normalize_alert_text(value)
    return re.sub(r"\s+flights?\b.*$", "", value, flags=re.I).strip(" .,-:")


def extract_route(text):
    patterns = (
        r"\bfrom\s+([A-Z][A-Za-z .'-]+?)\s+to\s+([A-Z][A-Za-z .'-]+?)(?=\s+flights?\b|[\.,;:]|$)",
        r"\b([A-Z][A-Za-z .'-]+?)\s+to\s+([A-Z][A-Za-z .'-]+?)\s+flights?\b",
        r"\b([A-Z]{3})\s*[-\u2013]\s*([A-Z]{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            origin = clean_place(match.group(1))
            destination = clean_place(match.group(2))
            if origin and destination:
                return f"{origin} -> {destination}"
    return None


def extract_price(text):
    match = re.search(PRICE_RE, text, re.I)
    if not match:
        return None
    return normalize_alert_text(match.group(0))


def first_weekday(year, month, weekday):
    day = dt.date(year, month, 1)
    while day.weekday() != weekday:
        day += dt.timedelta(days=1)
    return day


def last_weekday(year, month, weekday):
    day = dt.date(year, month, calendar.monthrange(year, month)[1])
    while day.weekday() != weekday:
        day -= dt.timedelta(days=1)
    return day


def easter_sunday(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def add_fixed_holidays_with_observed(holidays, fixed_dates):
    holidays.update(fixed_dates)
    for holiday in sorted(fixed_dates):
        if holiday.weekday() < 5:
            continue
        observed = holiday + dt.timedelta(days=7 - holiday.weekday())
        while observed.weekday() >= 5 or observed in holidays:
            observed += dt.timedelta(days=1)
        holidays.add(observed)


def ireland_days_off(year):
    holidays = set()
    fixed_dates = {
        dt.date(year, 1, 1),
        dt.date(year, 3, 17),
        dt.date(year, 12, 25),
        dt.date(year, 12, 26),
    }
    add_fixed_holidays_with_observed(holidays, fixed_dates)

    feb_1 = dt.date(year, 2, 1)
    holidays.add(feb_1 if feb_1.weekday() == 4 else first_weekday(year, 2, 0))
    holidays.add(easter_sunday(year) - dt.timedelta(days=2))
    holidays.add(easter_sunday(year) + dt.timedelta(days=1))
    holidays.add(first_weekday(year, 5, 0))
    holidays.add(first_weekday(year, 6, 0))
    holidays.add(first_weekday(year, 8, 0))
    holidays.add(last_weekday(year, 10, 0))
    return holidays


def extract_context_date(text):
    match = re.search(r"\b(\d{1,2})\s+([A-Z][a-z]+)\s+(20\d{2})\b", text)
    if match:
        month = MONTHS.get(match.group(2)[:3].lower())
        if month:
            return dt.date(int(match.group(3)), month, int(match.group(1)))

    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if match:
        return dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1)))

    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return dt.date(int(match.group(1)), 1, 1)

    return dt.date.today()


def parse_deal_date_range(date_range, context_date):
    match = re.search(
        rf"{DAY_RE}\s+(?P<start_day>\d{{1,2}})\s+(?P<start_month>[A-Z][a-z]{{2}})\s*-\s*"
        rf"{DAY_RE}\s+(?P<end_day>\d{{1,2}})\s+(?P<end_month>[A-Z][a-z]{{2}})",
        normalize_alert_text(date_range),
        re.I,
    )
    if not match:
        return None

    start_month = MONTHS.get(match.group("start_month").lower())
    end_month = MONTHS.get(match.group("end_month").lower())
    if not start_month or not end_month:
        return None

    start_date = dt.date(context_date.year, start_month, int(match.group("start_day")))
    end_year = context_date.year
    if (end_month, int(match.group("end_day"))) < (start_month, int(match.group("start_day"))):
        end_year += 1
    end_date = dt.date(end_year, end_month, int(match.group("end_day")))
    if start_date < context_date - dt.timedelta(days=2):
        start_date = dt.date(context_date.year + 1, start_month, int(match.group("start_day")))
        end_year = context_date.year + 1
        if (end_month, int(match.group("end_day"))) < (start_month, int(match.group("start_day"))):
            end_year += 1
        end_date = dt.date(end_year, end_month, int(match.group("end_day")))
    return start_date, end_date


def count_days_off(start_date, end_date):
    holidays = ireland_days_off(start_date.year) | ireland_days_off(end_date.year)
    days_off = 0
    day = start_date
    while day <= end_date:
        if day.weekday() < 5 and day not in holidays:
            days_off += 1
        day += dt.timedelta(days=1)
    return days_off


def add_filter_details(deal, context_date):
    dates = parse_deal_date_range(deal["dates"], context_date)
    if not dates:
        deal["eligible"] = False
        deal["filter_reason"] = "could not parse travel dates"
        return deal

    start_date, end_date = dates
    nights = (end_date - start_date).days
    days_off = count_days_off(start_date, end_date)
    deal.update({
        "start_date": start_date,
        "end_date": end_date,
        "nights": nights,
        "days_off": days_off,
        "eligible": nights >= MIN_NIGHTS and days_off <= MAX_DAYS_OFF,
    })
    if nights < MIN_NIGHTS:
        deal["filter_reason"] = f"{nights} night(s), minimum is {MIN_NIGHTS}"
    elif days_off > MAX_DAYS_OFF:
        deal["filter_reason"] = f"{days_off} day(s) off, maximum is {MAX_DAYS_OFF}"
    else:
        deal["filter_reason"] = "matched filters"
    return deal


def filter_deals(deals, context_text):
    context_date = extract_context_date(context_text)
    detailed = [add_filter_details(dict(deal), context_date) for deal in deals]
    return [deal for deal in detailed if deal["eligible"]], detailed


def parse_flight_deals(body):
    text = normalize_alert_text(body)
    deal_pattern = re.compile(
        rf"(?P<dates>{DATE_RANGE_RE})\s+"
        rf"(?:SAVE\s+\d+%\s+)?From\s+(?P<price>{PRICE_RE})\s+"
        rf"(?:View\s+)?(?P<airline>[A-Z][A-Za-z0-9 .&'-]+?)\s*\u00b7\s*"
        rf"(?P<stops>Non-stop|\d+\s+stops?)\s*\u00b7\s*"
        rf"(?P<route>[A-Z]{{3}}\s*[-\u2013]\s*[A-Z]{{3}})\s*\u00b7\s*"
        rf"(?P<duration>\d+\s*hrs?(?:\s+\d+\s*min)?)",
        re.I,
    )
    deals = []
    for match in deal_pattern.finditer(text):
        deals.append({
            "dates": normalize_alert_text(match.group("dates")),
            "price": normalize_alert_text(match.group("price")),
            "airline": normalize_alert_text(match.group("airline")),
            "stops": normalize_alert_text(match.group("stops")),
            "route": normalize_alert_text(match.group("route")),
            "duration": normalize_alert_text(match.group("duration")),
        })
    return deals


def parse_alert(subject, body):
    combined = f"{subject}\n{body}"
    route = extract_route(combined)
    price = extract_price(combined)

    summary = []
    if route:
        summary.append(route)
    if price:
        summary.append(price)
    return summary


def format_deal(deal):
    route = deal["route"].replace(" ", "").replace("\u2013", "-")
    trip_details = ""
    if "nights" in deal and "days_off" in deal:
        night_label = "night" if deal["nights"] == 1 else "nights"
        day_off_label = "day off" if deal["days_off"] == 1 else "days off"
        trip_details = f" ({deal['nights']} {night_label}, {deal['days_off']} {day_off_label})"
    return (
        f"- {deal['dates']}: {deal['price']}, {deal['airline']}, "
        f"{deal['stops']}, {route}, {deal['duration']}{trip_details}"
    )


def build_alert_message(subject, from_header, gmail_label, body, deals):
    alert_parts = parse_alert(subject, body)

    if deals:
        route = extract_route(f"{subject}\n{body}")
        summary_parts = []
        if route:
            summary_parts.append(route)
        summary_parts.append(f"{len(deals)} matching deal(s)")
        if deals[0].get("price"):
            summary_parts.append(f"from {deals[0]['price']}")
        summary = " | ".join(summary_parts)
    else:
        summary = " | ".join(alert_parts) if alert_parts else "New flight alert found"

    message_text = (
        f"Flight Alert\n"
        f"Subject: {subject or 'No subject'}\n"
        f"From: {from_header or 'Unknown'}\n"
        f"Label: {gmail_label}\n"
        f"Summary: {summary}\n"
    )

    if deals:
        message_text += "\nDeals:\n" + "\n".join(format_deal(deal) for deal in deals[:6])
        if len(deals) > 6:
            message_text += f"\n- {len(deals) - 6} more deal(s) in the email"
    elif body:
        snippet = normalize_alert_text(body)[:400]
        message_text += f"\nSnippet: {snippet}"

    return message_text


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


def select_all_mailbox(imap_conn):
    for mailbox in ("[Gmail]/All Mail", "[GoogleMail]/All Mail"):
        try:
            status, _ = imap_conn.select(f'"{mailbox}"')
            if status == "OK":
                return mailbox
        except imaplib.IMAP4.error:
            pass
    return None


def connect_to_gmail(gmail_user, gmail_password):
    print("Connecting to Gmail IMAP...")
    imap_conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        imap_conn.login(gmail_user, normalize_gmail_app_password(gmail_password))
    except imaplib.IMAP4.error as exc:
        try:
            imap_conn.logout()
        except imaplib.IMAP4.error:
            pass
        fail(
            "Gmail IMAP login failed. Use a Gmail App Password in the "
            "GMAIL_APP_PASSWORD secret, not your normal Google account password. "
            "The account must have 2-Step Verification enabled and IMAP access enabled. "
            f"Gmail response: {exc}"
        )
    return imap_conn


def main():
    gmail_user = get_env("GMAIL_USER")
    gmail_password = get_env("GMAIL_APP_PASSWORD")
    gmail_label = get_env("GMAIL_LABEL", required=False, default="Holidays/Flight alerts")
    telegram_token = get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = get_env("TELEGRAM_CHAT_ID")

    print(f"Checking Gmail label: {gmail_label}")
    imap_conn = connect_to_gmail(gmail_user, gmail_password)

    selected_label = select_label_mailbox(imap_conn, gmail_label)
    if selected_label:
        print(f"Selected Gmail label mailbox: {gmail_label}")
        status, data = imap_conn.search(None, "UNSEEN")
    else:
        print(
            f"Warning: could not select mailbox '{gmail_label}'. "
            "Make sure the label exists and is shown in IMAP. "
            "Falling back to All Mail search with label filter."
        )
        all_mailbox = select_all_mailbox(imap_conn)
        if not all_mailbox:
            imap_conn.logout()
            fail("Could not select Gmail All Mail mailbox for fallback search.")
        print(f"Selected Gmail fallback mailbox: {all_mailbox}")
        status, data = imap_conn.search(None, "UNSEEN", "X-GM-LABELS", f'"{gmail_label}"')

    if status != "OK":
        raise RuntimeError("Failed to search for unread messages")

    message_ids = data[0].split() if data and data[0] else []
    if not message_ids:
        print(f"No unread flight alerts found in label '{gmail_label}'.")
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
        deals = parse_flight_deals(body)

        if not deals:
            print(f"Skipping message {num_str}: no parseable flight deals found.")
            imap_conn.store(num, "+FLAGS", "\\Seen")
            print(f"Marked message {num_str} as read.")
            continue

        matching_deals, checked_deals = filter_deals(deals, f"{subject}\n{body}")
        if not matching_deals:
            reasons = sorted({deal["filter_reason"] for deal in checked_deals})
            print(f"Skipping message {num_str}: no deals matched filters ({'; '.join(reasons)}).")
            imap_conn.store(num, "+FLAGS", "\\Seen")
            print(f"Marked message {num_str} as read.")
            continue

        message_text = build_alert_message(subject, from_header, gmail_label, body, matching_deals)

        print(f"Sending Telegram notification for message {num_str}...")
        send_telegram_message(telegram_token, telegram_chat_id, message_text)
        imap_conn.store(num, "+FLAGS", "\\Seen")
        print(f"Marked message {num_str} as read.")

    imap_conn.logout()
    print("Done.")


if __name__ == "__main__":
    main()

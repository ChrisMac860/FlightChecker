import html
import imaplib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import email
import calendar
import datetime as dt
import unicodedata
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


def get_bool_env(name, default=False):
    value = os.getenv(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_int_env(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value.strip())
    except ValueError:
        fail(f"{name} must be an integer")


def get_float_env(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value.strip())
    except ValueError:
        fail(f"{name} must be a number")


def parse_csv(value, uppercase=False, lowercase=False):
    items = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if uppercase:
            item = item.upper()
        if lowercase:
            item = item.lower()
        items.append(item)
    return items


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
MONTH_RE = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
DATE_PART_RE = rf"(?:{DAY_RE}\s+)?\d{{1,2}}\s+{MONTH_RE}"
DATE_RANGE_RE = (
    rf"{DATE_PART_RE}\s*[-\u2013]\s*"
    rf"{DATE_PART_RE}"
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
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
MIN_NIGHTS = 2
MAX_DAYS_OFF = 1
MONTH_OVERFLOW_DAYS = 2
DESTINATION_MONTHS = {
    "Budapest": {4, 5, 6, 9, 10},
    "Copenhagen": {5, 6, 7, 8, 9},
    "Krakow": {5, 6, 9, 10, 12},
    "Milan": {4, 5, 6, 9, 10},
    "Riga": {5, 6, 7, 8, 9},
}
DESTINATION_AIRPORTS = {
    "BGY": "Milan",
    "BUD": "Budapest",
    "CPH": "Copenhagen",
    "KRK": "Krakow",
    "LIN": "Milan",
    "MIL": "Milan",
    "MXP": "Milan",
    "RIX": "Riga",
}
KNOWN_ROUTE_PLACES = (
    "Copenhagen",
    "Budapest",
    "Krakow",
    "Krak\u00f3w",
    "Dublin",
    "Milan",
    "Riga",
    "BGY",
    "BUD",
    "CPH",
    "DUB",
    "KRK",
    "LIN",
    "MIL",
    "MXP",
    "RIX",
)
KNOWN_ROUTE_PLACE_RE = "|".join(re.escape(place) for place in KNOWN_ROUTE_PLACES)
RYANAIR_ROUTES_URL = "https://services-api.ryanair.com/views/locate/5/routes/en/airport/{origin}"
RYANAIR_ROUND_TRIP_FARES_URL = "https://www.ryanair.com/api/farfnd/v4/roundTripFares"
RYANAIR_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RYANAIR_DEFAULT_ORIGIN_AIRPORTS = "DUB"
RYANAIR_DEFAULT_MARKET = "en-ie"
RYANAIR_DEFAULT_SCAN_MONTHS = 12
RYANAIR_DEFAULT_MAX_RETURN_PRICE = 100.0
RYANAIR_DEFAULT_DIGEST_LIMIT = 12
RYANAIR_DEFAULT_MAX_TRIP_NIGHTS = 3
RYANAIR_DEFAULT_DESTINATIONS = "curated"
RYANAIR_DEFAULT_REQUEST_DELAY = 0.3
RYANAIR_DEFAULT_MAX_DESTINATIONS = 60

# Per-origin Ryanair market (drives response currency). Falls back to the
# configured default market for any origin not listed here.
ORIGIN_MARKETS = {
    "DUB": "en-ie",
    "BFS": "en-gb",
    "BHD": "en-gb",
}

# Approximate, static FX rates used only to normalise prices to EUR for
# comparison/ranking across currencies (e.g. GBP fares from Belfast). Display
# always keeps the fare's native currency. These do not need to be exact.
FX_TO_EUR = {
    "EUR": 1.0,
    "GBP": 1.17,
    "USD": 0.92,
    "PLN": 0.23,
    "DKK": 0.134,
    "SEK": 0.088,
    "NOK": 0.086,
    "CHF": 1.06,
    "HUF": 0.0026,
    "CZK": 0.040,
    "RON": 0.20,
    "BGN": 0.51,
}

AVIASALES_PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
AVIASALES_SEARCH_URL = "https://www.aviasales.com"
AVIASALES_DEFAULT_CURRENCY = "eur"
AVIASALES_DEFAULT_SCAN_MONTHS = 6
AVIASALES_DEFAULT_DIGEST_LIMIT = 12

STATE_DEFAULT_PATH = "state/seen_deals.json"
PRICE_DROP_DEFAULT_EUR = 5.0

VALID_FLIGHT_SOURCES = {"gmail", "ryanair", "aviasales"}
GMAIL_FALLBACK_SEARCHES = (
    ("Google Flights sender", ("UNSEEN", "FROM", '"noreply-travel@google.com"')),
    (
        "Skyscanner sender",
        ("UNSEEN", "FROM", '"no-reply@sender.skyscanner.com"', "SUBJECT", '"Latest prices for your flights"'),
    ),
)


def normalize_alert_text(value):
    value = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", value)
    value = re.sub(r"\(https?://\S+\)", "", value)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"\[([^\]]+)\]", r"\1", value)
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value).strip()


def clean_place(value):
    value = normalize_alert_text(value)
    return re.sub(r"\s+flights?\b.*$", "", value, flags=re.I).strip(" .,-:")


def extract_route(text):
    patterns = (
        rf"\b({KNOWN_ROUTE_PLACE_RE})\s+(?:to|->)\s+({KNOWN_ROUTE_PLACE_RE})\b",
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


def month_number(value):
    normalized = value.strip().lower()
    return MONTHS.get(normalized) or MONTHS.get(normalized[:3])


def normalize_city_name(value):
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def destination_from_context(context_text):
    normalized_context = normalize_city_name(context_text)
    for destination in DESTINATION_MONTHS:
        if normalize_city_name(destination) in normalized_context:
            return destination
    return None


def destination_from_place(place):
    airport_destination = DESTINATION_AIRPORTS.get(place.upper())
    if airport_destination:
        return airport_destination

    normalized_place = normalize_city_name(place)
    for destination in DESTINATION_MONTHS:
        if normalize_city_name(destination) == normalized_place:
            return destination
    return None


def destination_from_deal(deal, context_text):
    route_text = deal.get("route") or ""
    named_route_match = re.search(
        rf"\b({KNOWN_ROUTE_PLACE_RE})\s*(?:->|to)\s*({KNOWN_ROUTE_PLACE_RE})\b",
        route_text,
        re.I,
    )
    if named_route_match:
        first_place = named_route_match.group(1)
        second_place = named_route_match.group(2)
        destination_place = first_place if normalize_city_name(second_place) == "dublin" else second_place
        destination = destination_from_place(destination_place)
        if destination:
            return destination

    route_match = re.search(r"\b([A-Z]{3})\s*-\s*([A-Z]{3})\b", route_text)
    if route_match:
        first_code = route_match.group(1).upper()
        second_code = route_match.group(2).upper()
        destination_code = first_code if second_code == "DUB" else second_code
        destination = DESTINATION_AIRPORTS.get(destination_code)
        if destination:
            return destination

    return destination_from_context(context_text)


def month_name(month):
    return calendar.month_abbr[month]


def format_months(months):
    return ", ".join(month_name(month) for month in sorted(months))


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
        month = month_number(match.group(2))
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
        rf"(?:{DAY_RE}\s+)?(?P<start_day>\d{{1,2}})\s+(?P<start_month>{MONTH_RE})\s*-\s*"
        rf"(?:{DAY_RE}\s+)?(?P<end_day>\d{{1,2}})\s+(?P<end_month>{MONTH_RE})",
        normalize_alert_text(date_range),
        re.I,
    )
    if not match:
        return None

    start_month = month_number(match.group("start_month"))
    end_month = month_number(match.group("end_month"))
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


def overlaps_allowed_month(start_date, end_date, allowed_months):
    for year in range(start_date.year - 1, end_date.year + 2):
        for month in allowed_months:
            month_start = dt.date(year, month, 1)
            month_end = dt.date(year, month, calendar.monthrange(year, month)[1])
            has_actual_overlap = start_date <= month_end and end_date >= month_start
            if not has_actual_overlap:
                continue
            allowed_start = month_start - dt.timedelta(days=MONTH_OVERFLOW_DAYS)
            allowed_end = month_end + dt.timedelta(days=MONTH_OVERFLOW_DAYS)
            if start_date >= allowed_start and end_date <= allowed_end:
                return True
    return False


def add_filter_details(deal, context_date, context_text, month_gated=True):
    if isinstance(deal.get("start_date"), dt.date) and isinstance(deal.get("end_date"), dt.date):
        dates = (deal["start_date"], deal["end_date"])
    else:
        dates = parse_deal_date_range(deal["dates"], context_date)
    if not dates:
        deal["eligible"] = False
        deal["filter_reason"] = "could not parse travel dates"
        return deal

    start_date, end_date = dates
    nights = (end_date - start_date).days
    days_off = count_days_off(start_date, end_date)
    destination = deal.get("destination") or destination_from_deal(deal, context_text)
    if "price_eur" not in deal and "price_value" in deal:
        deal["price_eur"] = to_eur(deal["price_value"], deal.get("currency", "EUR"))
    allowed_months = DESTINATION_MONTHS.get(destination, set())
    if month_gated:
        month_allowed = bool(allowed_months) and overlaps_allowed_month(start_date, end_date, allowed_months)
    else:
        month_allowed = True
    deal.update({
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "nights": nights,
        "days_off": days_off,
        "eligible": nights >= MIN_NIGHTS and days_off <= MAX_DAYS_OFF and month_allowed,
    })
    if nights < MIN_NIGHTS:
        deal["filter_reason"] = f"{nights} night(s), minimum is {MIN_NIGHTS}"
    elif days_off > MAX_DAYS_OFF:
        deal["filter_reason"] = f"{days_off} day(s) off, maximum is {MAX_DAYS_OFF}"
    elif month_gated and not destination:
        deal["filter_reason"] = "destination not configured"
    elif not month_allowed:
        deal["filter_reason"] = (
            f"{destination} is only enabled for {format_months(allowed_months)} "
            f"(with {MONTH_OVERFLOW_DAYS}-day overflow)"
        )
    else:
        deal["filter_reason"] = "matched filters"
    return deal


def filter_deals(deals, context_text):
    context_date = extract_context_date(context_text)
    detailed = [add_filter_details(dict(deal), context_date, context_text) for deal in deals]
    return [deal for deal in detailed if deal["eligible"]], detailed


def parse_flight_sources(value):
    sources = parse_csv(value or "gmail", lowercase=True)
    if not sources:
        sources = ["gmail"]
    unknown = sorted(set(sources) - VALID_FLIGHT_SOURCES)
    if unknown:
        fail(f"unknown FLIGHT_SOURCES value(s): {', '.join(unknown)}")
    return sources


def get_airport_code(airport):
    if not isinstance(airport, dict):
        return ""
    return (airport.get("iataCode") or airport.get("code") or "").upper()


def get_airport_city(airport):
    if not isinstance(airport, dict):
        return ""
    city = airport.get("city")
    if isinstance(city, dict) and city.get("name"):
        return city["name"]
    if isinstance(city, str) and city:
        return city
    return airport.get("name") or get_airport_code(airport)


def to_eur(value, currency):
    """Normalise a price to EUR using static approximate rates for comparison."""
    rate = FX_TO_EUR.get((currency or "EUR").upper())
    if rate is None:
        return float(value)
    return round(float(value) * rate, 2)


def filter_ryanair_destination_airports(origin, routes, destination_airports):
    origin = origin.upper()
    available = set()
    for route in routes:
        if get_airport_code(route.get("departureAirport")) != origin:
            continue
        arrival_code = get_airport_code(route.get("arrivalAirport"))
        if arrival_code in destination_airports:
            available.add(arrival_code)
    return sorted(available)


def parse_ryanair_datetime(value):
    if not value:
        raise ValueError("missing Ryanair datetime")
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_ryanair_date(value):
    return f"{calendar.day_abbr[value.weekday()]} {value.day} {calendar.month_abbr[value.month]}"


def format_ryanair_price(price):
    value = float(price["value"])
    currency = price.get("currencyCode") or "EUR"
    return f"{currency} {value:.2f}"


def normalize_ryanair_fare(fare):
    outbound = fare.get("outbound") or {}
    inbound = fare.get("inbound") or {}
    summary_price = (fare.get("summary") or {}).get("price") or {}
    origin_code = get_airport_code(outbound.get("departureAirport"))
    destination_code = get_airport_code(outbound.get("arrivalAirport"))
    destination_city = get_airport_city(outbound.get("arrivalAirport"))
    outbound_departure = parse_ryanair_datetime(outbound.get("departureDate"))
    inbound_departure = parse_ryanair_datetime(inbound.get("departureDate"))
    price_value = float(summary_price["value"])
    currency = summary_price.get("currencyCode") or "EUR"
    outbound_flight = outbound.get("flightNumber") or "FR"
    inbound_flight = inbound.get("flightNumber") or "FR"

    return {
        "source": "ryanair",
        "source_key": (
            f"ryanair:{origin_code}-{destination_code}:"
            f"{outbound.get('departureDate')}:{inbound.get('departureDate')}:{price_value:.2f}"
        ),
        "dedupe_key": (
            f"ryanair:{origin_code}-{destination_code}:"
            f"{outbound.get('departureDate')}:{inbound.get('departureDate')}"
        ),
        "dates": f"{format_ryanair_date(outbound_departure.date())} - {format_ryanair_date(inbound_departure.date())}",
        "price": format_ryanair_price(summary_price),
        "price_value": price_value,
        "price_eur": to_eur(price_value, currency),
        "currency": currency,
        "destination": destination_city or None,
        "airline": "Ryanair",
        "stops": "Non-stop",
        "route": f"{origin_code} - {destination_code}",
        "duration": f"{outbound_flight} / {inbound_flight}",
        "start_date": outbound_departure.date(),
        "end_date": inbound_departure.date(),
    }


def add_months(year, month, offset):
    month_index = year * 12 + month - 1 + offset
    return month_index // 12, month_index % 12 + 1


def ryanair_query_windows(today, scan_months, destination=None, month_gated=True):
    allowed_months = DESTINATION_MONTHS.get(destination, set()) if month_gated else None
    windows = []
    for offset in range(scan_months):
        year, month = add_months(today.year, today.month, offset)
        if allowed_months is not None and month not in allowed_months:
            continue
        month_start = dt.date(year, month, 1)
        month_end = dt.date(year, month, calendar.monthrange(year, month)[1])
        if allowed_months is not None:
            outbound_from = max(today, month_start - dt.timedelta(days=MONTH_OVERFLOW_DAYS))
            outbound_to = month_end + dt.timedelta(days=MONTH_OVERFLOW_DAYS)
        else:
            outbound_from = max(today, month_start)
            outbound_to = month_end
        if outbound_from <= outbound_to:
            windows.append((outbound_from, outbound_to))
    return windows


def ryanair_destination_catalog(origin, routes, mode):
    """Map of arrival IATA code -> display city for a Ryanair origin.

    mode 'curated' keeps only the configured DESTINATION_AIRPORTS; mode 'all'
    returns every direct route so the search covers the whole network."""
    origin = origin.upper()
    catalog = {}
    for route in routes:
        departure_code = get_airport_code(route.get("departureAirport"))
        if departure_code and departure_code != origin:
            continue
        arrival = route.get("arrivalAirport")
        arrival_code = get_airport_code(arrival)
        if not arrival_code:
            continue
        if mode == "all":
            catalog[arrival_code] = get_airport_city(arrival) or arrival_code
        elif arrival_code in DESTINATION_AIRPORTS:
            catalog[arrival_code] = DESTINATION_AIRPORTS[arrival_code]
    return catalog


def fetch_json(url, params=None, timeout=30, headers=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": RYANAIR_USER_AGENT,
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fetch_json_with_retry(url, params=None, timeout=30, headers=None, retries=3, backoff=1.5):
    """fetch_json with retries/backoff for transient rate-limit (429) and
    forbidden (403, sometimes returned to datacenter IPs) responses."""
    attempt = 0
    while True:
        try:
            return fetch_json(url, params=params, timeout=timeout, headers=headers)
        except urllib.error.HTTPError as exc:
            attempt += 1
            if exc.code not in (403, 429, 500, 502, 503, 504) or attempt > retries:
                raise
            time.sleep(backoff ** attempt)
        except urllib.error.URLError:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff ** attempt)


def ryanair_request_headers():
    """Browser-like headers Ryanair's fare API expects from non-browser clients.
    The fr-correlation-id cookie just needs to be present; client-version is
    optional and only set when RYANAIR_CLIENT_VERSION is configured."""
    headers = {
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": "https://www.ryanair.com",
        "Referer": "https://www.ryanair.com/",
        "Cookie": "fr-correlation-id=flightchecker",
    }
    client_version = get_env("RYANAIR_CLIENT_VERSION", required=False, default="")
    if client_version:
        headers["client-version"] = client_version
    return headers


def fetch_ryanair_routes(origin):
    url = RYANAIR_ROUTES_URL.format(origin=urllib.parse.quote(origin.upper()))
    data = fetch_json_with_retry(url, headers=ryanair_request_headers())
    return data if isinstance(data, list) else []


def build_ryanair_fare_params(origin, destination_code, outbound_from, outbound_to, config, market=None):
    return {
        "departureAirportIataCode": origin,
        "arrivalAirportIataCode": destination_code,
        "market": market or config["market"],
        "adultPaxCount": "1",
        "searchMode": "ALL",
        "outboundDepartureDateFrom": outbound_from.isoformat(),
        "outboundDepartureDateTo": outbound_to.isoformat(),
        "inboundDepartureDateFrom": outbound_from.isoformat(),
        "inboundDepartureDateTo": outbound_to.isoformat(),
        "durationFrom": str(MIN_NIGHTS),
        "durationTo": str(config["max_trip_nights"]),
        "outboundDepartureTimeFrom": "00:00",
        "outboundDepartureTimeTo": "23:59",
        "inboundDepartureTimeFrom": "00:00",
        "inboundDepartureTimeTo": "23:59",
        "priceValueTo": f"{config['max_return_price']:g}",
    }


def fetch_ryanair_round_trip_fares(params):
    data = fetch_json_with_retry(
        RYANAIR_ROUND_TRIP_FARES_URL, params=params, headers=ryanair_request_headers()
    )
    if not isinstance(data, dict):
        return []
    return data.get("fares") or []


def get_ryanair_config():
    origins = parse_csv(
        get_env("RYANAIR_ORIGIN_AIRPORTS", required=False, default=RYANAIR_DEFAULT_ORIGIN_AIRPORTS),
        uppercase=True,
    )
    if not origins:
        fail("RYANAIR_ORIGIN_AIRPORTS must include at least one airport code")

    destinations = get_env(
        "RYANAIR_DESTINATIONS", required=False, default=RYANAIR_DEFAULT_DESTINATIONS
    ).lower()
    if destinations not in {"curated", "all"}:
        fail("RYANAIR_DESTINATIONS must be 'curated' or 'all'")

    config = {
        "origins": origins,
        "market": get_env("RYANAIR_MARKET", required=False, default=RYANAIR_DEFAULT_MARKET),
        "destinations": destinations,
        "scan_months": get_int_env("RYANAIR_SCAN_MONTHS", RYANAIR_DEFAULT_SCAN_MONTHS),
        "max_return_price": get_float_env("RYANAIR_MAX_RETURN_PRICE", RYANAIR_DEFAULT_MAX_RETURN_PRICE),
        "digest_limit": get_int_env("RYANAIR_DIGEST_LIMIT", RYANAIR_DEFAULT_DIGEST_LIMIT),
        "max_trip_nights": get_int_env("RYANAIR_MAX_TRIP_NIGHTS", RYANAIR_DEFAULT_MAX_TRIP_NIGHTS),
        "max_destinations": get_int_env("RYANAIR_MAX_DESTINATIONS", RYANAIR_DEFAULT_MAX_DESTINATIONS),
        "request_delay": get_float_env("RYANAIR_REQUEST_DELAY", RYANAIR_DEFAULT_REQUEST_DELAY),
    }
    if config["scan_months"] < 1:
        fail("RYANAIR_SCAN_MONTHS must be at least 1")
    if config["digest_limit"] < 1:
        fail("RYANAIR_DIGEST_LIMIT must be at least 1")
    if config["max_trip_nights"] < MIN_NIGHTS:
        fail(f"RYANAIR_MAX_TRIP_NIGHTS must be at least {MIN_NIGHTS}")
    if config["max_destinations"] < 1:
        fail("RYANAIR_MAX_DESTINATIONS must be at least 1")
    return config


def collect_ryanair_deals(config, today=None):
    today = today or dt.date.today()
    month_gated = config["destinations"] == "curated"
    deals_by_key = {}
    for origin in config["origins"]:
        market = ORIGIN_MARKETS.get(origin.upper(), config["market"])
        try:
            routes = fetch_ryanair_routes(origin)
        except Exception as exc:
            print(f"Warning: could not fetch Ryanair routes for {origin}: {exc}")
            continue

        catalog = ryanair_destination_catalog(origin, routes, config["destinations"])
        if not catalog:
            print(f"No Ryanair destinations are available from {origin}.")
            continue

        destination_codes = sorted(catalog)[: config["max_destinations"]]
        for destination_code in destination_codes:
            destination = catalog[destination_code]
            for outbound_from, outbound_to in ryanair_query_windows(
                today, config["scan_months"], destination, month_gated=month_gated
            ):
                params = build_ryanair_fare_params(
                    origin, destination_code, outbound_from, outbound_to, config, market=market
                )
                try:
                    fares = fetch_ryanair_round_trip_fares(params)
                except Exception as exc:
                    print(f"Warning: could not fetch Ryanair fares {origin}-{destination_code}: {exc}")
                    continue
                finally:
                    if config["request_delay"] > 0:
                        time.sleep(config["request_delay"])

                for fare in fares:
                    try:
                        deal = normalize_ryanair_fare(fare)
                    except (KeyError, TypeError, ValueError) as exc:
                        print(f"Warning: skipping malformed Ryanair fare {origin}-{destination_code}: {exc}")
                        continue
                    detailed = add_filter_details(
                        deal, today, f"{destination} {today.year}", month_gated=month_gated
                    )
                    if not detailed["eligible"]:
                        continue
                    if detailed["price_eur"] > config["max_return_price"]:
                        continue
                    deals_by_key[detailed["source_key"]] = detailed

    return sorted(
        deals_by_key.values(),
        key=lambda deal: (deal["price_eur"], deal["start_date"], deal["route"]),
    )


def deal_price_eur(deal):
    return deal.get("price_eur", deal.get("price_value", 0.0))


def deal_group_key(deal):
    return deal.get("destination") or deal.get("route") or deal.get("dates")


def dedupe_cheapest_per_destination(deals):
    """Keep only the single cheapest trip per destination so the digest shows
    breadth (many cities to visit) rather than several fares to the same place."""
    best = {}
    for deal in deals:
        key = deal_group_key(deal)
        if key not in best or deal_price_eur(deal) < deal_price_eur(best[key]):
            best[key] = deal
    return list(best.values())


def build_digest(deals, title, limit):
    unique = dedupe_cheapest_per_destination(deals)
    selected = sorted(
        unique, key=lambda deal: (deal_price_eur(deal), deal.get("start_date") or dt.date.max)
    )[:limit]
    if not selected:
        return f"{title}\nSummary: No matching fares found."

    message = f"{title}\nSummary: Showing {len(selected)} cheapest matching fare(s)"
    if len(unique) > len(selected):
        message += f" from {len(unique)} destinations"
    message += "\n\nDeals:\n" + "\n".join(format_deal(deal) for deal in selected)
    return message


def build_ryanair_digest(deals, limit=RYANAIR_DEFAULT_DIGEST_LIMIT):
    return build_digest(deals, "Ryanair Fare Digest", limit)


def parse_google_flight_deals(body):
    text = normalize_alert_text(body)
    deal_pattern = re.compile(
        rf"(?P<dates>{DATE_RANGE_RE})\s+"
        rf"(?:SAVE\s+\d+%\s*)?From\s*(?P<price>{PRICE_RE})\s+"
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


def is_skyscanner_price_alert(subject, from_header, body):
    text = f"{subject}\n{from_header}\n{body}".lower()
    if "skyscanner" not in text:
        return False
    return any(
        phrase in text
        for phrase in (
            "price alert",
            "price changed",
            "prices changed",
            "track prices",
            "tracked route",
            "tracked trip",
            "pricealerts",
        )
    )


def parse_skyscanner_flight_deals(body, subject="", from_header=""):
    if not is_skyscanner_price_alert(subject, from_header, body):
        return []

    combined = normalize_alert_text(f"{subject}\n{body}")
    card_pattern = re.compile(
        rf"(?P<route>(?:{KNOWN_ROUTE_PLACE_RE})\s+(?:to|->)\s+(?:{KNOWN_ROUTE_PLACE_RE}))\s+"
        rf"(?P<dates>{DATE_RANGE_RE})\s+"
        rf"Economy\s+"
        rf"Was\s+{PRICE_RE}\s+"
        rf"(?P<price>{PRICE_RE})\s+"
        rf"Total per traveller\s+"
        rf"This price has just gone (?P<direction>up|down)",
        re.I,
    )
    deals = []
    for match in card_pattern.finditer(combined):
        route = extract_route(match.group("route"))
        direction = match.group("direction").lower()
        deals.append({
            "dates": normalize_alert_text(match.group("dates")),
            "price": normalize_alert_text(match.group("price")),
            "airline": "Skyscanner",
            "stops": "Price alert",
            "route": route,
            "duration": f"Price went {direction}",
        })
    if deals:
        return deals

    route = extract_route(combined)
    price = extract_price(combined)
    date_match = re.search(DATE_RANGE_RE, combined, re.I)
    if not route or not price or not date_match:
        return []

    return [{
        "dates": normalize_alert_text(date_match.group(0)),
        "price": price,
        "airline": "Skyscanner",
        "stops": "Price alert",
        "route": route,
        "duration": "Tracked route",
    }]


def parse_flight_deals(body, subject="", from_header=""):
    google_deals = parse_google_flight_deals(body)
    if google_deals:
        return google_deals
    return parse_skyscanner_flight_deals(body, subject=subject, from_header=from_header)


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
    route = (deal.get("route") or "").replace(" ", "").replace("\u2013", "-")
    trip_details = ""
    if "nights" in deal and "days_off" in deal:
        night_label = "night" if deal["nights"] == 1 else "nights"
        day_off_label = "day off" if deal["days_off"] == 1 else "days off"
        trip_details = f" ({deal['nights']} {night_label}, {deal['days_off']} {day_off_label})"
    line = (
        f"- {deal['dates']}: {deal['price']}, {deal['airline']}, "
        f"{deal['stops']}, {route}, {deal['duration']}{trip_details}"
    )
    if deal.get("url"):
        line += f"\n  {deal['url']}"
    return line


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


def search_gmail_message_ids(imap_conn, criteria):
    status, data = imap_conn.search(None, *criteria)
    if status != "OK":
        raise RuntimeError("Failed to search for unread messages")
    return data[0].split() if data and data[0] else []


def process_gmail_message(imap_conn, num, gmail_label, telegram_token, telegram_chat_id, dry_run=False):
    num_str = num.decode("utf-8") if isinstance(num, bytes) else str(num)
    status, msg_data = imap_conn.fetch(num, "(RFC822)")
    if status != "OK":
        print(f"Skipping message {num_str}: fetch failed.")
        return

    raw_email = msg_data[0][1]
    message = email.message_from_bytes(raw_email)
    subject = decode_mime_header(message.get("Subject"))
    from_header = decode_mime_header(message.get("From"))
    body = extract_text(message)
    deals = parse_flight_deals(body, subject=subject, from_header=from_header)

    if not deals:
        print(f"Skipping message {num_str}: no parseable flight deals found.")
        if dry_run:
            print(f"DRY RUN: would mark message {num_str} as read.")
        else:
            imap_conn.store(num, "+FLAGS", "\\Seen")
            print(f"Marked message {num_str} as read.")
        return

    matching_deals, checked_deals = filter_deals(deals, f"{subject}\n{body}")
    if not matching_deals:
        reasons = sorted({deal["filter_reason"] for deal in checked_deals})
        print(f"Skipping message {num_str}: no deals matched filters ({'; '.join(reasons)}).")
        if dry_run:
            print(f"DRY RUN: would mark message {num_str} as read.")
        else:
            imap_conn.store(num, "+FLAGS", "\\Seen")
            print(f"Marked message {num_str} as read.")
        return

    message_text = build_alert_message(subject, from_header, gmail_label, body, matching_deals)

    if dry_run:
        print(f"DRY RUN: would send Telegram notification for message {num_str}:")
        print(message_text)
        print(f"DRY RUN: would mark message {num_str} as read.")
    else:
        print(f"Sending Telegram notification for message {num_str}...")
        send_telegram_message(telegram_token, telegram_chat_id, message_text)
        imap_conn.store(num, "+FLAGS", "\\Seen")
        print(f"Marked message {num_str} as read.")


def run_gmail_source(dry_run=False):
    gmail_user = get_env("GMAIL_USER")
    gmail_password = get_env("GMAIL_APP_PASSWORD")
    gmail_label = get_env("GMAIL_LABEL", required=False, default="Holidays/Flight alerts")
    telegram_token = None if dry_run else get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = None if dry_run else get_env("TELEGRAM_CHAT_ID")

    print(f"Checking Gmail label: {gmail_label}")
    imap_conn = connect_to_gmail(gmail_user, gmail_password)

    selected_label = select_label_mailbox(imap_conn, gmail_label)
    if selected_label:
        print(f"Selected Gmail label mailbox: {gmail_label}")
        message_ids = search_gmail_message_ids(imap_conn, ("UNSEEN",))
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
        message_ids = search_gmail_message_ids(imap_conn, ("UNSEEN", "X-GM-LABELS", f'"{gmail_label}"'))

    if not message_ids:
        print(f"No unread flight alerts found in label '{gmail_label}'.")
    else:
        print(f"Found {len(message_ids)} unread message(s) in label '{gmail_label}'.")
        for num in message_ids:
            process_gmail_message(imap_conn, num, gmail_label, telegram_token, telegram_chat_id, dry_run=dry_run)

    all_mailbox = select_all_mailbox(imap_conn)
    if not all_mailbox:
        print("Warning: could not select Gmail All Mail mailbox for fallback sender searches.")
    else:
        print(f"Selected Gmail fallback mailbox: {all_mailbox}")
        for description, criteria in GMAIL_FALLBACK_SEARCHES:
            fallback_message_ids = search_gmail_message_ids(imap_conn, criteria)
            if not fallback_message_ids:
                print(f"No unread flight alerts found from {description}.")
                continue
            print(f"Found {len(fallback_message_ids)} unread message(s) from {description}.")
            for num in fallback_message_ids:
                process_gmail_message(imap_conn, num, gmail_label, telegram_token, telegram_chat_id, dry_run=dry_run)

    imap_conn.logout()
    print("Done.")


def load_state(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def prune_state(state, today):
    """Drop entries whose travel dates have already passed."""
    today_iso = today.isoformat()
    return {key: entry for key, entry in state.items() if entry.get("end_date", "") >= today_iso}


def state_key(deal):
    return deal.get("dedupe_key") or deal.get("source_key")


def is_fresh(deal, state, drop_threshold_eur):
    """A deal is alert-worthy if it's new, or its EUR price dropped by at least
    drop_threshold_eur versus the last price we alerted on."""
    key = state_key(deal)
    if not key:
        return True
    entry = state.get(key)
    if entry is None:
        return True
    price = round(deal_price_eur(deal), 2)
    last_alerted = entry.get("last_alerted_price_eur", price)
    return (last_alerted - price) >= drop_threshold_eur


def commit_state(deals, state, today):
    for deal in deals:
        key = state_key(deal)
        if not key:
            continue
        entry = state.get(key, {})
        end_date = deal.get("end_date")
        state[key] = {
            "first_seen": entry.get("first_seen", today.isoformat()),
            "last_alerted_price_eur": round(deal_price_eur(deal), 2),
            "end_date": end_date.isoformat() if isinstance(end_date, dt.date) else entry.get("end_date", ""),
        }


def select_deals_to_alert(deals, limit, dry_run, today=None):
    """Dedupe to the cheapest trip per destination, rank by price, then keep only
    the new / price-dropped ones (using persisted state) up to the digest limit.
    State is saved only on real runs so dry runs and tests never mutate it."""
    today = today or dt.date.today()
    ranked = sorted(
        dedupe_cheapest_per_destination(deals),
        key=lambda deal: (deal_price_eur(deal), deal.get("start_date") or dt.date.max),
    )

    path = get_env("STATE_FILE", required=False, default=STATE_DEFAULT_PATH)
    if not path:
        return ranked[:limit]

    threshold = get_float_env("PRICE_DROP_EUR", PRICE_DROP_DEFAULT_EUR)
    state = prune_state(load_state(path), today)
    fresh = [deal for deal in ranked if is_fresh(deal, state, threshold)]
    shown = fresh[:limit]
    if not dry_run:
        commit_state(shown, state, today)
        save_state(path, state)
    return shown


def run_ryanair_source(dry_run=False):
    config = get_ryanair_config()
    print(
        "Checking Ryanair fares: "
        f"origins={', '.join(config['origins'])}, "
        f"destinations={config['destinations']}, "
        f"scan_months={config['scan_months']}, "
        f"max_return_price={config['max_return_price']:g}"
    )
    deals = collect_ryanair_deals(config)
    if not deals:
        print("No Ryanair fares matched the configured filters.")
        return

    shown = select_deals_to_alert(deals, config["digest_limit"], dry_run)
    if not shown:
        print("No new or cheaper Ryanair fares since the last run.")
        return

    message_text = build_digest(shown, "Ryanair Fare Digest", config["digest_limit"])
    if dry_run:
        print("DRY RUN: would send Ryanair Telegram digest:")
        print(message_text)
        return

    telegram_token = get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = get_env("TELEGRAM_CHAT_ID")
    print(f"Sending Ryanair Telegram digest with {len(shown)} deal(s)...")
    send_telegram_message(telegram_token, telegram_chat_id, message_text)
    print("Done.")


def get_aviasales_config():
    origins = parse_csv(
        get_env("AVIASALES_ORIGIN_AIRPORTS", required=False, default=RYANAIR_DEFAULT_ORIGIN_AIRPORTS),
        uppercase=True,
    )
    if not origins:
        fail("AVIASALES_ORIGIN_AIRPORTS must include at least one airport code")

    config = {
        "token": get_env("TRAVELPAYOUTS_TOKEN"),
        "origins": origins,
        "currency": get_env("AVIASALES_CURRENCY", required=False, default=AVIASALES_DEFAULT_CURRENCY).lower(),
        "market": get_env("AVIASALES_MARKET", required=False, default="ie").lower(),
        "scan_months": get_int_env("AVIASALES_SCAN_MONTHS", AVIASALES_DEFAULT_SCAN_MONTHS),
        "max_return_price": get_float_env("AVIASALES_MAX_RETURN_PRICE", RYANAIR_DEFAULT_MAX_RETURN_PRICE),
        "digest_limit": get_int_env("AVIASALES_DIGEST_LIMIT", AVIASALES_DEFAULT_DIGEST_LIMIT),
        "direct_only": get_bool_env("AVIASALES_DIRECT_ONLY", default=True),
    }
    if config["scan_months"] < 1:
        fail("AVIASALES_SCAN_MONTHS must be at least 1")
    if config["digest_limit"] < 1:
        fail("AVIASALES_DIGEST_LIMIT must be at least 1")
    return config


def aviasales_query_months(today, scan_months):
    months = []
    for offset in range(scan_months):
        year, month = add_months(today.year, today.month, offset)
        months.append(f"{year:04d}-{month:02d}")
    return months


def normalize_aviasales_offer(item):
    if not item.get("return_at"):
        raise ValueError("missing Aviasales return date")
    origin_code = (item.get("origin") or "").upper()
    destination_code = (item.get("destination") or "").upper()
    start_date = dt.datetime.fromisoformat(item["departure_at"]).date()
    end_date = dt.datetime.fromisoformat(item["return_at"]).date()
    price_value = float(item["price"])
    currency = (item.get("currency") or "EUR").upper()
    airline = item.get("airline") or "?"
    transfers = item.get("transfers") or 0
    stops = "Non-stop" if not transfers else f"{transfers} stop(s)"
    link = item.get("link") or ""
    url = f"{AVIASALES_SEARCH_URL}{link}" if link.startswith("/") else (link or None)

    return {
        "source": "aviasales",
        "source_key": (
            f"aviasales:{origin_code}-{destination_code}:"
            f"{item.get('departure_at')}:{item.get('return_at')}:{price_value:.2f}"
        ),
        "dedupe_key": (
            f"aviasales:{origin_code}-{destination_code}:"
            f"{item.get('departure_at')}:{item.get('return_at')}"
        ),
        "dates": f"{format_ryanair_date(start_date)} - {format_ryanair_date(end_date)}",
        "price": f"{currency} {price_value:.2f}",
        "price_value": price_value,
        "price_eur": to_eur(price_value, currency),
        "currency": currency,
        "destination": DESTINATION_AIRPORTS.get(destination_code) or destination_code,
        "airline": airline,
        "stops": stops,
        "route": f"{origin_code} - {destination_code}",
        "duration": f"flight {item.get('flight_number', '')}".strip(),
        "url": url,
        "start_date": start_date,
        "end_date": end_date,
    }


def fetch_aviasales_offers(origin, month, config):
    params = {
        "origin": origin,
        "departure_at": month,
        "one_way": "false",
        "currency": config["currency"],
        "market": config["market"],
        "sorting": "price",
        "limit": "1000",
    }
    if config["direct_only"]:
        params["direct"] = "true"
    data = fetch_json_with_retry(
        AVIASALES_PRICES_URL, params=params, headers={"X-Access-Token": config["token"]}
    )
    if not isinstance(data, dict):
        return []
    return data.get("data") or []


def collect_aviasales_deals(config, today=None):
    today = today or dt.date.today()
    deals_by_key = {}
    for origin in config["origins"]:
        for month in aviasales_query_months(today, config["scan_months"]):
            try:
                offers = fetch_aviasales_offers(origin, month, config)
            except Exception as exc:
                print(f"Warning: could not fetch Aviasales offers {origin} {month}: {exc}")
                continue

            for item in offers:
                try:
                    deal = normalize_aviasales_offer(item)
                except (KeyError, TypeError, ValueError) as exc:
                    print(f"Warning: skipping malformed Aviasales offer: {exc}")
                    continue
                if deal["start_date"] < today:
                    continue
                detailed = add_filter_details(deal, today, deal["destination"] or "", month_gated=False)
                if not detailed["eligible"]:
                    continue
                if detailed["price_eur"] > config["max_return_price"]:
                    continue
                deals_by_key[detailed["source_key"]] = detailed

    return sorted(
        deals_by_key.values(),
        key=lambda deal: (deal["price_eur"], deal["start_date"], deal["route"]),
    )


def run_aviasales_source(dry_run=False):
    config = get_aviasales_config()
    print(
        "Checking Aviasales fares: "
        f"origins={', '.join(config['origins'])}, "
        f"currency={config['currency']}, "
        f"scan_months={config['scan_months']}, "
        f"max_return_price={config['max_return_price']:g}"
    )
    deals = collect_aviasales_deals(config)
    if not deals:
        print("No Aviasales fares matched the configured filters.")
        return

    shown = select_deals_to_alert(deals, config["digest_limit"], dry_run)
    if not shown:
        print("No new or cheaper Aviasales fares since the last run.")
        return

    message_text = build_digest(shown, "Aviasales Fare Digest", config["digest_limit"])
    if dry_run:
        print("DRY RUN: would send Aviasales Telegram digest:")
        print(message_text)
        return

    telegram_token = get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = get_env("TELEGRAM_CHAT_ID")
    print(f"Sending Aviasales Telegram digest with {len(shown)} deal(s)...")
    send_telegram_message(telegram_token, telegram_chat_id, message_text)
    print("Done.")


def run_configured_sources():
    sources = parse_flight_sources(get_env("FLIGHT_SOURCES", required=False, default="gmail"))
    dry_run = get_bool_env("DRY_RUN", default=False)
    for source in sources:
        if source == "gmail":
            run_gmail_source(dry_run=dry_run)
        elif source == "ryanair":
            run_ryanair_source(dry_run=dry_run)
        elif source == "aviasales":
            run_aviasales_source(dry_run=dry_run)


def main():
    run_configured_sources()


if __name__ == "__main__":
    main()

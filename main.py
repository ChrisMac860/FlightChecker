import functools
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


def utc_now_iso():
    """Current UTC time as an ISO-8601 'Z' timestamp (second precision)."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

# Public-facing deals log that powers the GitHub Pages site (docs/index.html).
# Each eligible deal is upserted by a source-agnostic identity so re-seeing the
# same trip refreshes it in place (timestamp/price) instead of duplicating.
DEALS_LOG_DEFAULT_PATH = "docs/deals.json"

# Drop deals not re-seen within this many hours, so the page only lists fares
# that are still current (a deal missing from the last ~2 scans falls off).
DEALS_LOG_MAX_AGE_HOURS = 8

# Display city for the (few) origin airports we fly from.
ORIGIN_CITIES = {
    "DUB": "Dublin",
    "BFS": "Belfast",
    "BHD": "Belfast",
}

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


@functools.lru_cache(maxsize=None)
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


# --- Destination quality filter ---------------------------------------------
# Quality over quantity: skip too-close/commuter UK destinations and a handful
# of specifically-excluded cities (e.g. Paris). UK is matched by country code so
# every UK airport is caught; the code list covers non-country exclusions and
# sources (Aviasales) that don't return a country. Extend via env:
#   EXCLUDED_DESTINATIONS  - extra IATA codes (CSV) added to the defaults
#   EXCLUDED_COUNTRIES     - country codes (CSV) that REPLACE the default {gb}
DEFAULT_EXCLUDED_DESTINATION_CODES = {
    "LON", "LHR", "LGW", "LTN", "STN", "LCY", "SEN",           # London (LON = metro code)
    "BHX", "BRS", "MAN", "LPL", "LBA", "NCL", "EMA", "BOH",    # England
    "EXT", "NQY", "DSA", "MME", "HUY", "SOU", "NWI", "BLK",
    "EDI", "GLA", "PIK", "ABZ", "INV", "DND",                  # Scotland
    "CWL", "IOM", "JER", "GCI",                                # Wales / islands
    "PAR", "CDG", "ORY", "BVA",                                # Paris (PAR = metro code)
}
DEFAULT_EXCLUDED_COUNTRY_CODES = {"gb"}                        # United Kingdom


def excluded_destination_codes():
    extra = parse_csv(get_env("EXCLUDED_DESTINATIONS", required=False, default=""), uppercase=True)
    return DEFAULT_EXCLUDED_DESTINATION_CODES | set(extra)


def excluded_country_codes():
    override = parse_csv(get_env("EXCLUDED_COUNTRIES", required=False, default=""), lowercase=True)
    return set(override) if override else DEFAULT_EXCLUDED_COUNTRY_CODES


def is_excluded_destination(destination_code, country_code=None):
    """True for destinations we deliberately don't surface (UK + naff cities)."""
    if (destination_code or "").upper() in excluded_destination_codes():
        return True
    if country_code and country_code.lower() in excluded_country_codes():
        return True
    return False


def add_filter_details(deal, context_date, context_text, month_gated=True):
    dest_code = resolve_route_codes(deal.get("route"))[1]
    if is_excluded_destination(dest_code, deal.get("destination_country")):
        deal["eligible"] = False
        deal["filter_reason"] = "excluded destination (quality filter)"
        return deal
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
    # Resolve the curated key from the route's IATA code, because the fare API's
    # display city ('Kraków', 'Bergamo', 'Milan Bergamo') may not match the
    # DESTINATION_MONTHS keys ('Krakow', 'Milan'). Keep the city for display.
    resolved = destination_from_deal(deal, context_text)
    destination = deal.get("destination") or resolved
    month_destination = resolved or destination
    if "price_eur" not in deal and "price_value" in deal:
        deal["price_eur"] = to_eur(deal["price_value"], deal.get("currency", "EUR"))
    allowed_months = DESTINATION_MONTHS.get(month_destination, set())
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
            f"{month_destination} is only enabled for {format_months(allowed_months)} "
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


# Locale path used in Ryanair booking URLs, per origin (drives site language).
RYANAIR_BOOKING_MARKETS = {"DUB": "ie/en", "BFS": "gb/en", "BHD": "gb/en"}


def ryanair_booking_url(origin, destination, depart, ret):
    """Deep link to Ryanair's booking page pre-filled with this exact RETURN
    trip. Ryanair's flight-select SPA needs the 'tp*' (trip) params in addition
    to the plain ones, otherwise it opens a default/one-way search instead of
    the round trip for these dates."""
    market = RYANAIR_BOOKING_MARKETS.get((origin or "").upper(), "ie/en")
    date_out, date_in = depart.isoformat(), ret.isoformat()
    params = {
        "adults": "1", "teens": "0", "children": "0", "infants": "0",
        "dateOut": date_out, "dateIn": date_in,
        "isConnectedFlight": "false", "isReturn": "true",
        "discount": "0", "promoCode": "",
        "originIata": origin, "destinationIata": destination,
        # Trip params the new site actually reads to seed the return search.
        "tpAdults": "1", "tpTeens": "0", "tpChildren": "0", "tpInfants": "0",
        "tpStartDate": date_out, "tpEndDate": date_in,
        "tpDiscount": "0", "tpPromoCode": "",
        "tpOriginIata": origin, "tpDestinationIata": destination,
    }
    return f"https://www.ryanair.com/{market}/trip/flights/select?{urllib.parse.urlencode(params)}"


def normalize_ryanair_fare(fare):
    outbound = fare.get("outbound") or {}
    inbound = fare.get("inbound") or {}
    summary_price = (fare.get("summary") or {}).get("price") or {}
    origin_code = get_airport_code(outbound.get("departureAirport"))
    destination_code = get_airport_code(outbound.get("arrivalAirport"))
    destination_city = get_airport_city(outbound.get("arrivalAirport"))
    destination_country = ((outbound.get("arrivalAirport") or {}).get("city") or {}).get("countryCode") or ""
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
        # Source-agnostic, date-based identity: the same trip from Ryanair and
        # Aviasales shares this key, so alert state de-duplicates across sources.
        "dedupe_key": (
            f"{origin_code}-{destination_code}:"
            f"{outbound_departure.date().isoformat()}:{inbound_departure.date().isoformat()}"
        ),
        "dates": f"{format_ryanair_date(outbound_departure.date())} - {format_ryanair_date(inbound_departure.date())}",
        "price": format_ryanair_price(summary_price),
        "price_value": price_value,
        "price_eur": to_eur(price_value, currency),
        "currency": currency,
        "destination": destination_city or None,
        "destination_country": destination_country,
        "airline": "Ryanair",
        "stops": "Non-stop",
        "route": f"{origin_code} - {destination_code}",
        "duration": f"{outbound_flight} / {inbound_flight}",
        "url": ryanair_booking_url(
            origin_code, destination_code, outbound_departure.date(), inbound_departure.date()
        ),
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


def build_ryanair_fare_params(origin, outbound_from, outbound_to, config, market=None, destination_code=None):
    """Round-trip fare query params. With no destination_code the endpoint
    returns the cheapest fares to *every* reachable destination in one call.
    The inbound window is extended by max_trip_nights past the outbound window so
    weekends that straddle the window's end (e.g. Fri 31 Oct -> Sun 2 Nov) are
    still returned rather than falling between two monthly windows."""
    inbound_to = outbound_to + dt.timedelta(days=config["max_trip_nights"])
    params = {
        "departureAirportIataCode": origin,
        "market": market or config["market"],
        "adultPaxCount": "1",
        "searchMode": "ALL",
        "outboundDepartureDateFrom": outbound_from.isoformat(),
        "outboundDepartureDateTo": outbound_to.isoformat(),
        "inboundDepartureDateFrom": outbound_from.isoformat(),
        "inboundDepartureDateTo": inbound_to.isoformat(),
        "durationFrom": str(MIN_NIGHTS),
        "durationTo": str(config["max_trip_nights"]),
        "outboundDepartureTimeFrom": "00:00",
        "outboundDepartureTimeTo": "23:59",
        "inboundDepartureTimeFrom": "00:00",
        "inboundDepartureTimeTo": "23:59",
        "priceValueTo": f"{config['max_return_price']:g}",
    }
    if destination_code:
        params["arrivalAirportIataCode"] = destination_code
    return params


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
        "request_delay": get_float_env("RYANAIR_REQUEST_DELAY", RYANAIR_DEFAULT_REQUEST_DELAY),
    }
    if config["scan_months"] < 1:
        fail("RYANAIR_SCAN_MONTHS must be at least 1")
    if config["digest_limit"] < 1:
        fail("RYANAIR_DIGEST_LIMIT must be at least 1")
    if config["max_trip_nights"] < MIN_NIGHTS:
        fail(f"RYANAIR_MAX_TRIP_NIGHTS must be at least {MIN_NIGHTS}")
    return config


def collect_ryanair_deals(config, today=None):
    """Query Ryanair's round-trip fare finder once per origin per month window
    with no fixed destination, so a single call returns the cheapest fares to
    every reachable city. This replaces the old per-destination fan-out (which
    cost hundreds of calls per run and silently capped coverage to the
    alphabetically-first destinations). Per-destination month gating in
    `curated` mode is applied to each returned fare via add_filter_details."""
    today = today or dt.date.today()
    month_gated = config["destinations"] == "curated"
    deals_by_key = {}
    for origin in config["origins"]:
        market = ORIGIN_MARKETS.get(origin.upper(), config["market"])
        for outbound_from, outbound_to in ryanair_query_windows(
            today, config["scan_months"], month_gated=False
        ):
            params = build_ryanair_fare_params(
                origin, outbound_from, outbound_to, config, market=market
            )
            try:
                fares = fetch_ryanair_round_trip_fares(params)
            except Exception as exc:
                print(f"Warning: could not fetch Ryanair fares {origin} {outbound_from:%Y-%m}: {exc}")
                continue
            finally:
                if config["request_delay"] > 0:
                    time.sleep(config["request_delay"])

            for fare in fares:
                try:
                    deal = normalize_ryanair_fare(fare)
                except (KeyError, TypeError, ValueError) as exc:
                    print(f"Warning: skipping malformed Ryanair fare from {origin}: {exc}")
                    continue
                context = f"{deal.get('destination') or ''} {today.year}"
                detailed = add_filter_details(deal, today, context, month_gated=month_gated)
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


TELEGRAM_MAX_CHARS = 4096


def chunk_telegram_text(text, limit=TELEGRAM_MAX_CHARS):
    """Split text into <=limit-char chunks, preferring to break on a newline.
    Telegram rejects messages over 4096 chars, which would otherwise drop a long
    digest entirely."""
    chunks = []
    remaining = text or ""
    while len(remaining) > limit:
        window = remaining[:limit]
        split_at = window.rfind("\n")
        if split_at <= 0:
            split_at = limit
        chunk = remaining[:split_at].rstrip("\n")
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def _post_telegram_message(token, chat_id, text, retries=3, backoff=1.5):
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    attempt = 0
    while True:
        try:
            request = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
            if not result.get("ok"):
                raise RuntimeError(f"Telegram send failed: {result}")
            return result
        except urllib.error.HTTPError as exc:
            attempt += 1
            if exc.code not in (420, 429, 500, 502, 503, 504) or attempt > retries:
                raise
            time.sleep(backoff ** attempt)
        except urllib.error.URLError:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff ** attempt)


def send_telegram_message(token, chat_id, text):
    """Send `text` to Telegram, transparently splitting over-long messages into
    multiple chunks and retrying transient rate-limit/server errors."""
    result = None
    for chunk in chunk_telegram_text(text):
        result = _post_telegram_message(token, chat_id, chunk)
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


GMAIL_PROCESSED_DEFAULT_LABEL = "FlightChecker/Processed"


def mark_message_processed(imap_conn, num, dry_run, processed_label):
    """Mark a handled message read AND tag it with a processed label. The label
    (rather than read-state alone) means a parser regression is recoverable: the
    messages we consumed can be found and re-examined by searching that label,
    instead of being silently lost among genuinely-read mail."""
    num_str = num.decode("utf-8") if isinstance(num, bytes) else str(num)
    if dry_run:
        print(f"DRY RUN: would mark message {num_str} as processed.")
        return
    if processed_label:
        try:
            imap_conn.store(num, "+X-GM-LABELS", f'"{processed_label}"')
        except imaplib.IMAP4.error as exc:
            print(f"Warning: could not label message {num_str} as processed: {exc}")
    imap_conn.store(num, "+FLAGS", "\\Seen")
    print(f"Marked message {num_str} as processed.")


def process_gmail_message(imap_conn, num, gmail_label, telegram_token, telegram_chat_id,
                          processed_label, dry_run=False):
    """Process one message; return the list of matching deals (for the public
    log), or [] if it had nothing alert-worthy."""
    num_str = num.decode("utf-8") if isinstance(num, bytes) else str(num)
    status, msg_data = imap_conn.fetch(num, "(RFC822)")
    if status != "OK":
        print(f"Skipping message {num_str}: fetch failed.")
        return []

    raw_email = msg_data[0][1]
    message = email.message_from_bytes(raw_email)
    subject = decode_mime_header(message.get("Subject"))
    from_header = decode_mime_header(message.get("From"))
    body = extract_text(message)
    deals = parse_flight_deals(body, subject=subject, from_header=from_header)

    if not deals:
        print(f"Skipping message {num_str}: no parseable flight deals found.")
        mark_message_processed(imap_conn, num, dry_run, processed_label)
        return []

    matching_deals, checked_deals = filter_deals(deals, f"{subject}\n{body}")
    if not matching_deals:
        reasons = sorted({deal["filter_reason"] for deal in checked_deals})
        print(f"Skipping message {num_str}: no deals matched filters ({'; '.join(reasons)}).")
        mark_message_processed(imap_conn, num, dry_run, processed_label)
        return []

    message_text = build_alert_message(subject, from_header, gmail_label, body, matching_deals)

    if dry_run:
        print(f"DRY RUN: would send Telegram notification for message {num_str}:")
        print(message_text)
        mark_message_processed(imap_conn, num, dry_run, processed_label)
        return matching_deals

    print(f"Sending Telegram notification for message {num_str}...")
    send_telegram_message(telegram_token, telegram_chat_id, message_text)
    mark_message_processed(imap_conn, num, dry_run, processed_label)
    return matching_deals


def run_gmail_source(dry_run=False):
    gmail_user = get_env("GMAIL_USER")
    gmail_password = get_env("GMAIL_APP_PASSWORD")
    gmail_label = get_env("GMAIL_LABEL", required=False, default="Holidays/Flight alerts")
    processed_label = get_env("GMAIL_PROCESSED_LABEL", required=False, default=GMAIL_PROCESSED_DEFAULT_LABEL)
    telegram_token = None if dry_run else get_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = None if dry_run else get_env("TELEGRAM_CHAT_ID")

    print(f"Checking Gmail label: {gmail_label}")
    imap_conn = connect_to_gmail(gmail_user, gmail_password)
    matched_deals = []

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
            matched_deals.extend(process_gmail_message(
                imap_conn, num, gmail_label, telegram_token, telegram_chat_id,
                processed_label, dry_run=dry_run))

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
                matched_deals.extend(process_gmail_message(
                    imap_conn, num, gmail_label, telegram_token, telegram_chat_id,
                    processed_label, dry_run=dry_run))

    imap_conn.logout()
    # Only write the public log when email actually yielded a deal, so the
    # 15-minute Gmail schedule doesn't churn docs/deals.json on every empty run.
    if not dry_run and matched_deals:
        record_deals_to_log(matched_deals)
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


# --- Public deals log (powers the GitHub Pages site at docs/index.html) -------

def deals_log_path():
    """docs/deals.json by default; set DEALS_LOG_FILE='' to disable logging.
    Distinguishes unset (use default) from empty (disabled) -- unlike get_env,
    which would coerce '' back to the default."""
    value = os.getenv("DEALS_LOG_FILE")
    if value is None:
        return DEALS_LOG_DEFAULT_PATH
    return value.strip()


# City display name -> canonical IATA code, for resolving email-alert routes
# (Google Flights / Skyscanner) that use city names rather than codes. Keyed by
# normalize_city_name output so accents/case don't matter.
CITY_TO_AIRPORT = {
    "dublin": "DUB",
    "belfast": "BFS",
    "copenhagen": "CPH",
    "budapest": "BUD",
    "krakow": "KRK",
    "milan": "MIL",
    "riga": "RIX",
    "barcelona": "BCN",
}


def split_route_codes(route):
    """Best-effort (origin_code, destination_code) from a 'DUB - BCN' route."""
    match = re.search(r"\b([A-Z]{3})\b\s*(?:->|-|–|to)\s*\b([A-Z]{3})\b", route or "", re.I)
    if match:
        return match.group(1).upper(), match.group(2).upper()
    return "", ""


def place_to_code(place):
    """Resolve a 3-letter code or a city name to an IATA code (best effort)."""
    place = (place or "").strip()
    if re.fullmatch(r"[A-Za-z]{3}", place):
        return place.upper()
    return CITY_TO_AIRPORT.get(normalize_city_name(place), "")


def resolve_route_codes(route):
    """(origin_code, destination_code) from a route that may use codes or city
    names, e.g. 'DUB - CPH' or 'Dublin -> Copenhagen'. Empty strings if a side
    can't be resolved."""
    origin, destination = split_route_codes(route)
    if origin and destination:
        return origin, destination
    parts = re.split(r"\s*(?:->|→|to|-|–)\s*", route or "", maxsplit=1, flags=re.I)
    if len(parts) == 2:
        return place_to_code(parts[0]), place_to_code(parts[1])
    return origin, destination


def parse_price_string(price):
    """Extract (value, currency) from a display price like '£80' or 'EUR 89.98'.
    Email alerts carry only this string; the API sources already set numbers."""
    if not price:
        return None, None
    text = price.strip()
    currency = None
    for token, code in (("US$", "USD"), ("GBP", "GBP"), ("EUR", "EUR"), ("USD", "USD"),
                        ("£", "GBP"), ("€", "EUR"), ("$", "USD")):
        if token in text:
            currency = code
            break
    number = re.search(r"\d{1,4}(?:[.,]\d{2})?", text)
    if not number:
        return None, currency
    return float(number.group(0).replace(",", ".")), currency


def deal_numeric_price(deal):
    """(price_value, price_eur, currency) for a deal, parsing the display price
    string when the source (email) didn't supply numbers. Returns None values if
    no price can be determined."""
    price_value = deal.get("price_value")
    currency = deal.get("currency")
    if price_value is None:
        price_value, parsed_currency = parse_price_string(deal.get("price"))
        currency = currency or parsed_currency
    currency = currency or "EUR"
    price_eur = deal.get("price_eur")
    if price_eur is None and price_value is not None:
        price_eur = to_eur(price_value, currency)
    return price_value, (round(price_eur, 2) if price_eur is not None else None), currency


def deal_identity(deal):
    """Source-agnostic identity used to upsert the log: the same trip from any
    source (or run) maps to the same key, so re-seeing it replaces in place."""
    key = deal.get("dedupe_key")
    if key:
        return key
    start = deal.get("start_date")
    end = deal.get("end_date")
    start_iso = start.isoformat() if isinstance(start, dt.date) else str(deal.get("dates") or "")
    end_iso = end.isoformat() if isinstance(end, dt.date) else ""
    origin, destination = resolve_route_codes(deal.get("route"))
    if origin and destination:
        return f"{origin}-{destination}:{start_iso}:{end_iso}"
    # No resolvable codes (e.g. an unknown city in an email alert): fall back to a
    # slug of the route so distinct destinations on the same dates don't collide.
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_alert_text(deal.get("route") or "").lower()).strip("-")
    return f"{slug or 'unknown'}:{start_iso}:{end_iso}"


def deal_to_log_entry(deal, now_iso):
    origin, destination_code = resolve_route_codes(deal.get("route"))
    start = deal.get("start_date")
    end = deal.get("end_date")
    if origin and destination_code:
        route = f"{origin} → {destination_code}"
    else:
        route = (deal.get("route") or "").replace(" - ", " → ").replace("->", "→")
    price_value, price_eur, currency = deal_numeric_price(deal)
    return {
        "id": deal_identity(deal),
        "origin": origin,
        "origin_city": ORIGIN_CITIES.get(origin, origin),
        "destination": deal.get("destination") or destination_code,
        "destination_code": destination_code,
        "destination_country": deal.get("destination_country") or "",
        "route": route,
        "depart_date": start.isoformat() if isinstance(start, dt.date) else "",
        "return_date": end.isoformat() if isinstance(end, dt.date) else "",
        "dates_label": deal.get("dates") or "",
        "nights": deal.get("nights"),
        "days_off": deal.get("days_off"),
        "price": deal.get("price") or "",
        "price_value": price_value,
        "price_eur": price_eur,
        "currency": currency,
        "airline": deal.get("airline") or "",
        "stops": deal.get("stops") or "",
        "source": deal.get("source") or "gmail",
        "url": deal.get("url") or "",
        "first_seen": now_iso,
        "last_seen": now_iso,
        "seen_count": 1,
    }


def load_deals_log(path):
    """Return {id: entry} parsed from the JSON log file (empty on any error)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    deals = data.get("deals") if isinstance(data, dict) else None
    if not isinstance(deals, list):
        return {}
    return {entry["id"]: entry for entry in deals if isinstance(entry, dict) and entry.get("id")}


def upsert_deals_log(log, deals, now_iso):
    """Insert/refresh each deal. Re-seeing the same trip replaces it in place:
    last_seen is bumped, seen_count incremented, first_seen preserved, and the
    cheapest price/source/url ever seen for that trip is kept for display."""
    for deal in deals:
        entry = deal_to_log_entry(deal, now_iso)
        deal_id = entry["id"]
        existing = log.get(deal_id)
        if existing is None:
            log[deal_id] = entry
            continue
        entry["first_seen"] = existing.get("first_seen", now_iso)
        entry["seen_count"] = int(existing.get("seen_count", 1)) + 1
        entry["last_seen"] = now_iso
        # Keep the cheapest sighting's price + display block together. A None
        # price_eur (unparseable) is treated as more expensive than any number.
        existing_eur = existing.get("price_eur")
        new_eur = entry.get("price_eur")
        keep_existing = existing_eur is not None and (new_eur is None or existing_eur <= new_eur)
        if keep_existing:
            for field in ("price", "price_value", "price_eur", "currency", "airline",
                          "stops", "source", "url", "destination", "destination_code", "route"):
                entry[field] = existing.get(field, entry[field])
        log[deal_id] = entry
    return log


def prune_deals_log(log, today, now=None, max_age_hours=DEALS_LOG_MAX_AGE_HOURS):
    """Drop trips whose return date is in the past, trips not re-seen within
    max_age_hours (when `now` is given), and any destination that is now excluded
    — so changing the quality filter clears stale entries immediately rather than
    waiting for them to age out."""
    today_iso = today.isoformat()
    cutoff_iso = None
    if now is not None and max_age_hours:
        cutoff = now - dt.timedelta(hours=max_age_hours)
        cutoff_iso = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    kept = {}
    for deal_id, entry in log.items():
        return_date = entry.get("return_date") or ""
        if return_date and return_date < today_iso:
            continue
        if cutoff_iso is not None:
            last_seen = entry.get("last_seen") or ""
            if last_seen and last_seen < cutoff_iso:
                continue
        if is_excluded_destination(entry.get("destination_code"), entry.get("destination_country")):
            continue
        kept[deal_id] = entry
    return kept


def write_deals_log(path, log, now_iso):
    deals = sorted(
        log.values(),
        key=lambda entry: (
            entry["price_eur"] if entry.get("price_eur") is not None else float("inf"),
            entry.get("depart_date") or "9999-99-99",
        ),
    )
    payload = {"generated_at": now_iso, "deal_count": len(deals), "deals": deals}
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def record_deals_to_log(deals, today=None, now_iso=None):
    """Upsert eligible deals into the public log and prune past trips. No-op when
    DEALS_LOG_FILE is empty. Returns the path written, or None."""
    path = deals_log_path()
    if not path:
        return None
    today = today or dt.date.today()
    now_iso = now_iso or utc_now_iso()
    now_dt = dt.datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    log = load_deals_log(path)
    upsert_deals_log(log, deals, now_iso)
    log = prune_deals_log(log, today, now=now_dt)
    write_deals_log(path, log, now_iso)
    return path


# --- Telegram alert de-duplication state -------------------------------------

def alert_state_path():
    """state/seen_deals.json by default; set STATE_FILE='' to disable dedupe."""
    value = os.getenv("STATE_FILE")
    if value is None:
        return STATE_DEFAULT_PATH
    return value.strip()


def open_alert_state(today):
    """Load (path, state, threshold) for alert de-duplication, or (None, None,
    None) when STATE_FILE is disabled."""
    path = alert_state_path()
    if not path:
        return None, None, None
    threshold = get_float_env("PRICE_DROP_EUR", PRICE_DROP_DEFAULT_EUR)
    state = prune_state(load_state(path), today)
    return path, state, threshold


def select_fresh_deals(deals, limit, state, threshold):
    """Cheapest trip per destination, ranked by price, keeping only new or
    price-dropped trips (per state). Does NOT mutate or persist state -- call
    commit_alert_state only after the alert has actually been sent."""
    ranked = sorted(
        dedupe_cheapest_per_destination(deals),
        key=lambda deal: (deal_price_eur(deal), deal.get("start_date") or dt.date.max),
    )
    if state is None:
        return ranked[:limit]
    fresh = [deal for deal in ranked if is_fresh(deal, state, threshold)]
    return fresh[:limit]


def commit_alert_state(path, state, shown, today):
    """Persist that `shown` were alerted. Called only after a successful send so a
    failed delivery never suppresses a future re-alert."""
    if not path or state is None:
        return
    commit_state(shown, state, today)
    save_state(path, state)


def run_ryanair_source(dry_run=False):
    config = get_ryanair_config()
    print(
        "Checking Ryanair fares: "
        f"origins={', '.join(config['origins'])}, "
        f"destinations={config['destinations']}, "
        f"scan_months={config['scan_months']}, "
        f"max_return_price={config['max_return_price']:g}"
    )
    today = dt.date.today()
    deals = collect_ryanair_deals(config, today)
    if not dry_run:
        record_deals_to_log(deals, today)
    if not deals:
        print("No Ryanair fares matched the configured filters.")
        return

    path, state, threshold = open_alert_state(today)
    shown = select_fresh_deals(deals, config["digest_limit"], state, threshold)
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
    commit_alert_state(path, state, shown, today)
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
        # Source-agnostic, date-based identity (see normalize_ryanair_fare): keyed
        # on calendar dates so it matches the same trip from any source.
        "dedupe_key": (
            f"{origin_code}-{destination_code}:"
            f"{start_date.isoformat()}:{end_date.isoformat()}"
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
    # Resilience: a missing optional token skips just this source rather than
    # failing the whole run (which would block the Ryanair scan + page update).
    if not os.getenv("TRAVELPAYOUTS_TOKEN"):
        print("Skipping Aviasales: TRAVELPAYOUTS_TOKEN is not set.")
        return
    config = get_aviasales_config()
    print(
        "Checking Aviasales fares: "
        f"origins={', '.join(config['origins'])}, "
        f"currency={config['currency']}, "
        f"scan_months={config['scan_months']}, "
        f"max_return_price={config['max_return_price']:g}"
    )
    today = dt.date.today()
    deals = collect_aviasales_deals(config, today)
    if not dry_run:
        record_deals_to_log(deals, today)
    if not deals:
        print("No Aviasales fares matched the configured filters.")
        return

    path, state, threshold = open_alert_state(today)
    shown = select_fresh_deals(deals, config["digest_limit"], state, threshold)
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
    commit_alert_state(path, state, shown, today)
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

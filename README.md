# FlightChecker

A GitHub Actions-driven flight monitor that finds cheap weekend (Fri→Sun / Sat→Mon) trips from Dublin and Belfast and pushes them to Telegram. It combines email alerts (Google Flights, Skyscanner) with direct queries to the free Ryanair fare API and the free Travelpayouts/Aviasales fare data API.

Everything runs for free: make the repository **public** so GitHub Actions minutes are unlimited (private repos only get 2,000 minutes/month, which the 15-minute Gmail schedule would exceed).

## Architecture

- **Gmail source** runs every 15 minutes for Google Flights and Skyscanner email alerts.
- **Ryanair + Aviasales sources** run daily at 07:00 UTC.
- `main.py` selects sources from `FLIGHT_SOURCES`.
- Gmail connects through IMAP, parses unread Google Flights and Skyscanner messages, sends matching Telegram alerts, and marks processed messages as read.
- Ryanair discovers direct routes from each origin airport (all 120+ routes from Dublin in `all` mode), queries round-trip fares, applies the weekend trip filters, and sends one compact Telegram digest with the cheapest trip per destination.
- Aviasales (Travelpayouts) queries cached cheapest round-trip prices across many airlines (Aer Lingus, Wizz, easyJet, Vueling…) for breadth Ryanair's own API misses.
- The API sources persist a small state file (`state/seen_deals.json`) so you are only alerted about **new** or **price-dropped** trips, never the same digest twice. The daily state commit also keeps the repo active so GitHub does not auto-disable the scheduled workflow after 60 days.

## Sources

- `gmail` — email alert parser for Google Flights and Skyscanner price alerts. Default when `FLIGHT_SOURCES` is not set.
- `ryanair` — unauthenticated Ryanair web fare endpoints. No API key needed.
- `aviasales` — Travelpayouts/Aviasales cached fare data (free token). Prices are indicative/cached (~48h); the Telegram link opens the live search to confirm before booking.

API failures on any source are logged as warnings so they never affect the others.

## Filters

- Minimum trip length: 2 nights
- Maximum Ryanair trip length: 3 nights by default (weekend-focused)
- Maximum annual leave needed: 1 weekday
- Weekends do not count as annual leave
- Ireland public holidays and Good Friday do not count as annual leave (so a trip over a bank-holiday weekend can cost zero or one day of leave)
- Default max return price: EUR 100 (prices in other currencies, e.g. GBP from Belfast, are normalised to EUR with approximate static rates for comparison, while the alert shows the native currency)
- Digest shows the single cheapest trip **per destination**, sorted by price, so you see many cities to visit rather than several fares to the same place
- `RYANAIR_DESTINATIONS=curated` keeps the original five seasonal cities (Budapest, Copenhagen, Krakow, Milan, Riga) with month windows; `RYANAIR_DESTINATIONS=all` scans every direct route across the next `RYANAIR_SCAN_MONTHS` months

## Setup

Add these GitHub secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GMAIL_USER` — required for the Gmail source
- `GMAIL_APP_PASSWORD` — required for the Gmail source; use a Gmail App Password, not your normal Google password
- `TRAVELPAYOUTS_TOKEN` — required for the Aviasales source; free token from the [Travelpayouts](https://www.travelpayouts.com/) dashboard

Optional repository variables (with their defaults):

- `GMAIL_LABEL` — `Holidays/Flight alerts`
- `RYANAIR_ORIGIN_AIRPORTS` — `DUB,BFS`
- `RYANAIR_DESTINATIONS` — `all` (`curated` for the original seasonal cities)
- `RYANAIR_SCAN_MONTHS` — `6`
- `RYANAIR_MAX_RETURN_PRICE` — `100` (EUR)
- `RYANAIR_DIGEST_LIMIT` — `12`
- `RYANAIR_MAX_TRIP_NIGHTS` — `3`
- `RYANAIR_MAX_DESTINATIONS` — `60` (cap on routes scanned per origin per run)
- `RYANAIR_REQUEST_DELAY` — `0.3` (seconds between fare calls, to stay polite)
- `RYANAIR_CLIENT_VERSION` — unset (optional; set if Ryanair starts rejecting requests)
- `AVIASALES_ORIGIN_AIRPORTS` — `DUB,BFS`
- `AVIASALES_SCAN_MONTHS` — `6`
- `AVIASALES_MAX_RETURN_PRICE` — `100`
- `AVIASALES_DIRECT_ONLY` — `true`
- `PRICE_DROP_EUR` — `5` (minimum EUR drop before re-alerting a known trip)
- `STATE_FILE` — `state/seen_deals.json` (set empty to disable dedupe/state)

For Gmail, confirm the account has 2-Step Verification enabled, IMAP enabled, and the `Flight alerts` label set to "Show in IMAP".

The Gmail source checks unread messages in `Holidays/Flight alerts`, then falls back to unread messages from the known alert senders:

- Google Flights: from `noreply-travel@google.com`
- Skyscanner: from `no-reply@sender.skyscanner.com`, subject `Latest prices for your flights`

### Belfast / currencies

Ryanair returns prices in the market's currency. The per-origin market map sends Dublin queries to `en-ie` (EUR) and Belfast (`BFS`/`BHD`) to `en-gb` (GBP); all prices are normalised to EUR only for ranking and the price cap, while each alert line keeps its native currency. The Ireland annual-leave calendar is always used (the traveller's leave is Irish regardless of departure airport).

### Free always-on

- Make the repo **public** for unlimited free Action minutes.
- The daily job commits `state/seen_deals.json` and `state/last_run.txt`, which both de-duplicates alerts and keeps the repository active so scheduled workflows are not auto-disabled after 60 days of inactivity.

## Run Locally

Run the Gmail source:

```powershell
$env:FLIGHT_SOURCES = "gmail"
$env:GMAIL_USER = "you@example.com"
$env:GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
$env:GMAIL_LABEL = "Holidays/Flight alerts"
$env:TELEGRAM_BOT_TOKEN = "123456:ABC-DEF"
$env:TELEGRAM_CHAT_ID = "-1001234567890"
python main.py
```

Dry-run the broadened Ryanair search from Dublin and Belfast without sending Telegram:

```powershell
$env:FLIGHT_SOURCES = "ryanair"
$env:DRY_RUN = "true"
$env:STATE_FILE = ""
$env:RYANAIR_ORIGIN_AIRPORTS = "DUB,BFS"
$env:RYANAIR_DESTINATIONS = "all"
$env:RYANAIR_MAX_RETURN_PRICE = "100"
python main.py
```

Dry-run the Aviasales source (needs a free Travelpayouts token):

```powershell
$env:FLIGHT_SOURCES = "aviasales"
$env:DRY_RUN = "true"
$env:STATE_FILE = ""
$env:TRAVELPAYOUTS_TOKEN = "your-token"
python main.py
```

Run all sources:

```powershell
$env:FLIGHT_SOURCES = "gmail,ryanair,aviasales"
python main.py
```

## Tests

```powershell
python -m unittest discover -s tests
```

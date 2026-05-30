# FlightChecker

A GitHub Actions-driven flight monitor that checks Gmail flight alerts and can also query Ryanair fare APIs for cheap direct return trips.

## Architecture

- Gmail source runs every 15 minutes by default.
- Ryanair source runs daily at 07:00 UTC by default.
- `main.py` selects sources from `FLIGHT_SOURCES`.
- Gmail connects through IMAP, parses unread messages in the configured label, sends matching Telegram alerts, and marks processed messages as read.
- Ryanair discovers direct routes from the configured origin airports, queries round-trip fares, applies the same trip filters, and sends one compact Telegram digest.

## Sources

- `gmail` - existing email alert parser. This remains the default when `FLIGHT_SOURCES` is not set.
- `ryanair` - unauthenticated Ryanair web fare endpoints. API failures are logged as warnings so they do not affect Gmail checks.

## Filters

- Minimum trip length: 2 nights
- Maximum Ryanair trip length: 7 nights by default
- Maximum annual leave needed: 1 weekday
- Weekends do not count as annual leave
- Ireland public holidays and Good Friday do not count as annual leave
- Destination month filters allow 2 days of overflow at the start or end of an enabled month
- Ryanair default max return price: EUR 100
- Ryanair default digest size: 6 cheapest matching fares
- Budapest: April, May, June, September, October
- Copenhagen: May, June, July, August, September
- Krakow: May, June, September, October, December
- Milan: April, May, June, September, October
- Riga: May, June, July, August, September
- Non-matching Gmail flight alert emails are marked as read after being checked

## Setup

Add these GitHub secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GMAIL_USER` - required for the Gmail source
- `GMAIL_APP_PASSWORD` - required for the Gmail source; use a Gmail App Password, not your normal Google password

Optional repository variables:

- `GMAIL_LABEL` - defaults to `Holidays/Flight alerts`
- `RYANAIR_ORIGIN_AIRPORTS` - defaults to `DUB`
- `RYANAIR_MARKET` - defaults to `en-ie`
- `RYANAIR_SCAN_MONTHS` - defaults to `12`
- `RYANAIR_MAX_RETURN_PRICE` - defaults to `100`
- `RYANAIR_DIGEST_LIMIT` - defaults to `6`
- `RYANAIR_MAX_TRIP_NIGHTS` - defaults to `7`

For Gmail, confirm the account has 2-Step Verification enabled, IMAP enabled, and the `Flight alerts` label set to "Show in IMAP".

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

Run the Ryanair source in dry-run mode without sending Telegram:

```powershell
$env:FLIGHT_SOURCES = "ryanair"
$env:DRY_RUN = "true"
$env:RYANAIR_ORIGIN_AIRPORTS = "DUB"
$env:RYANAIR_MAX_RETURN_PRICE = "100"
python main.py
```

Run both sources:

```powershell
$env:FLIGHT_SOURCES = "gmail,ryanair"
python main.py
```

# FlightChecker

A GitHub Actions-driven flight alert monitor that checks Gmail for new messages under a specific label and sends Telegram notifications.

## Architecture

- Gmail message arrives with label `Travel/FlightAlerts`
- GitHub Actions runs every 15 minutes
- `main.py` connects to Gmail via IMAP using app password
- It searches unread messages in the configured label
- It sends a Telegram message for each new alert
- It marks processed messages as read

## Setup

1. Add secrets to GitHub:
   - `GMAIL_USER`
   - `GMAIL_APP_PASSWORD`
   - `GMAIL_LABEL` (optional, default: `Travel/FlightAlerts`)
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

2. Confirm Gmail account has 2-Step Verification enabled and create an App Password.
3. Add the repository workflow file in `.github/workflows/flight-alerts.yml`.

## Run locally

```powershell
$env:GMAIL_USER = "you@example.com"
$env:GMAIL_APP_PASSWORD = "app-password"
$env:GMAIL_LABEL = "Travel/FlightAlerts"
$env:TELEGRAM_BOT_TOKEN = "123456:ABC-DEF"
$env:TELEGRAM_CHAT_ID = "-1001234567890"
python main.py
```

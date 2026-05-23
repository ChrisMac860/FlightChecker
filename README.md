# FlightChecker

A GitHub Actions-driven flight alert monitor that checks Gmail for new messages under a specific label and sends Telegram notifications.

## Architecture

- Gmail message arrives with label `Holidays/Flight alerts`
- GitHub Actions runs every 15 minutes
- `main.py` connects to Gmail via IMAP using app password
- It searches unread messages in the configured label
- It sends a Telegram message for each new alert
- It marks processed messages as read

Only unread messages trigger a Telegram notification. If you open the email in Gmail before the workflow runs, Gmail marks it read and the bot skips it.

## Setup

1. Add secrets to GitHub:
   - `GMAIL_USER` - the Gmail address to check
   - `GMAIL_APP_PASSWORD` - a Gmail App Password, not your normal Google password
   - Optional repository variable `GMAIL_LABEL` if you want a label other than `Holidays/Flight alerts`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

2. Confirm the Gmail account has 2-Step Verification enabled.
3. Create a Gmail App Password for this workflow and save that 16-character value as `GMAIL_APP_PASSWORD`. Spaces are OK; the script removes whitespace before logging in.
4. In Gmail settings, confirm IMAP is enabled.
5. In Gmail label settings, confirm the `Flight alerts` label has "Show in IMAP" enabled.
6. Add the repository workflow file in `.github/workflows/flight-alerts.yml`.

## Run locally

```powershell
$env:GMAIL_USER = "you@example.com"
$env:GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
$env:GMAIL_LABEL = "Holidays/Flight alerts"
$env:TELEGRAM_BOT_TOKEN = "123456:ABC-DEF"
$env:TELEGRAM_CHAT_ID = "-1001234567890"
python main.py
```

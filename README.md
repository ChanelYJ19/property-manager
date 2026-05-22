# leanne-property-manager

Sends daily SMS reminders about property management deadlines and updates a Google Sheets spreadsheet when Leanne texts back a reply.

## How it works

1. **Scheduler** — APScheduler runs a job every morning at 9 AM. It reads the `Deadlines` tab of a Google Sheet and sends an SMS for any task due in 1, 3, or 7 days (unless the task is already marked `DONE` or `SKIPPED`).
2. **Webhook** — A Flask server listens for inbound SMS messages forwarded by Twilio. It parses the reply (e.g. `"Insurance DONE"`) using fuzzy matching and writes the new status back to the sheet.

## Project structure

```
leanne-property-manager/
├── app/
│   ├── reply_parser.py   # fuzzy-match SMS replies → (task, status)
│   ├── scheduler.py      # APScheduler daily reminder job
│   ├── sheets.py         # gspread read/write helpers
│   ├── sms.py            # Twilio outbound SMS
│   └── webhook.py        # Flask inbound SMS endpoint
├── config/
│   └── settings.py       # loads .env variables
├── tests/
│   ├── test_reply_parser.py
│   └── test_scheduler.py
├── run.py                # starts Flask + scheduler together
├── requirements.txt
└── .env.example
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in all values
```

### Google Sheets

- Create a Service Account in Google Cloud Console and download the JSON key.
- Share the spreadsheet with the service account email (Editor access).
- Paste the full JSON into `GOOGLE_SHEETS_CREDS_JSON` (single line, escaped).
- The sheet must have a tab named `Deadlines` with columns: `Task`, `Due Date` (YYYY-MM-DD), `Status`.

### Twilio

- Buy a Twilio phone number and note your Account SID and Auth Token.
- Set the SMS webhook URL for that number to `https://<your-domain>/sms`.

### Run locally

```bash
python run.py
```

Use [ngrok](https://ngrok.com/) to expose port 5000 for local Twilio testing:
```bash
ngrok http 5000
# then set your Twilio webhook to https://<ngrok-id>.ngrok.io/sms
```

### Run tests

```bash
pytest tests/
```

## TODO — Deployment

- [ ] Choose a hosting platform (Railway, Fly.io, Render, or a VPS)
- [ ] Set all environment variables as platform secrets (never commit `.env`)
- [ ] Switch `flask_app.run()` in `run.py` to Gunicorn: `gunicorn run:flask_app`
- [ ] Configure Twilio webhook URL to point at the deployed `/sms` endpoint
- [ ] Set up a process supervisor (e.g. systemd or platform restart policy) so the scheduler survives restarts
- [ ] Add a health-check endpoint and uptime monitor (e.g. UptimeRobot)
- [ ] Consider moving the scheduler to a separate worker process or a cron job at the platform level for reliability

# SMS Logger

Self-hosted SMS/MMS logging for people who want their text messages in their
own hands: an Android companion app forwards incoming messages to a small
Flask server, which keeps a per-contact history in SQLite, serves a browsing
dashboard, exports everything to an Obsidian vault as linked Markdown, and
exposes a read-only JSON API for downstream tools — including, optionally, an
AI assistant that can answer texts for you.

**No LLM lives here.** Logging never depends on an assistant; the AI hookup is
one optional environment variable.

## How it works

```
Android phone (notification listener)
        │  POST /webhook/android-sms
        ▼
  SMS Logger (Flask + SQLite)
        ├── Dashboard        — browse/search contacts and history
        ├── Obsidian export  — per-contact .md, daily logs, Inbox.md (60s loop)
        ├── Read-only API    — /api/contacts, /api/messages, /api/search, /api/recent
        └── Assistant relay  — optional: forward a message, text back the reply
```

The Android app reads messages via a **NotificationListenerService** — it never
requests `READ_SMS`/`RECEIVE_SMS` permissions and does not need to be your
default SMS app. See [`android/`](android/) for the app.

## Quick start (Docker)

```bash
cp .env.example .env            # set OWNER_NAME, OWNER_NUMBERS, WEBHOOK_SECRET
cp docker-compose.example.yml docker-compose.yml   # adjust the vault volume
docker compose up -d --build
```

Then open `http://<host>:8097/dashboard` (Basic auth: `DASHBOARD_USER` /
`DASHBOARD_PASSWORD`) and point the Android app at
`http://<host>:8097` with your `WEBHOOK_SECRET`.

If you deploy without the compose file: the export loop starts at import time
and is **not multi-worker safe** — run gunicorn with `--workers 1` (the
Dockerfile already does).

## Pieces

| Piece | What |
|---|---|
| `server.py` | Flask app: webhooks, dashboard, setup wizard, read-only API |
| `smslog/db.py` | SQLite layer — `messages`, `observed_messages`, `contacts`, `archive_messages`, `settings` |
| `smslog/sms_exporter.py` | 60s loop → per-contact `.md` + `Daily/` + `Inbox.md` in the Obsidian vault |
| `smslog/identity.py` | Transport key (SMS / `tg:` / `signal:`) → canonical phone resolution |
| `android/` | Android forwarder app (notification listener — no SMS permissions) |
| `attachments/` | MMS media, `<contact>/<file>` (mounted at `/app/attachments`) |

## Ingestion routes

- `POST /webhook/android-sms` — the Android app's forwarder (`event: sms:received`)
- `POST /webhook/mms` — media-aware MMS (`type: message.mms.received`, base64 attachments)
- `POST /webhook` — legacy gateway shape (`type: message.phone.received`)
- `POST /observe` — watcher-mode shape (also handy for iOS Shortcuts — see `android/README.md`)

All authenticated via the `X-Webhook-Secret` header.

## Obsidian export

Every minute, new messages are written into the vault folder set by
`OBSIDIAN_SMS_PATH`:

- `Contacts/<Name>.md` — one file per contact, YAML frontmatter with the phone
  number and a `person: "[[Name]]"` link so logs connect to your people notes
- `Daily/YYYY-MM-DD.md` — chronological daily log, known contacts written as
  `[[wikilinks]]`
- `Inbox.md` — rolling view of the last 100 messages (rewritten only when the
  content actually changes, so it won't churn file-sync tools)

Senders that are app notifications ("Messenger: Jane Doe") are filed under the
person's name; `Contacts/Unknown/` is reserved for unrecognized phone numbers.

## Read-only API

```
GET /api/contacts                                  # every contact + count + last_seen
GET /api/messages/<key>?since=<ISO>&limit=&order=  # unified history (sms/observed/archive)
GET /api/search?q=&contact=&limit=                 # plain-text search
GET /api/recent?limit=                             # recent observed msgs across all contacts
```

Same `X-Webhook-Secret` header. Rate-limiter exempt.

## Optional assistant integration

Set `ASSISTANT_REPLY_URL` and active-mode messages are POSTed there
(`{"phone": ..., "content": ...}`); a non-empty reply is returned to the phone
app, which sends it back to the sender as an SMS. `ASSISTANT_NAME` (default
`Vi`) is the display name used for those outbound replies in the Obsidian
logs. Leave both alone for pure logging.

## Dev run

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
DB_PATH=./scratch.db WEBHOOK_SECRET=test OWNER_NAME=Alex venv/bin/python server.py
```

## Privacy notes

- Your messages never leave your infrastructure; there are no third-party calls.
- Protect the dashboard (`DASHBOARD_PASSWORD`) and webhook (`WEBHOOK_SECRET`) —
  anyone with the secret can read your full history via the API.
- If the server is reachable outside your LAN, put it behind HTTPS or a VPN
  such as Tailscale.

## License

MIT — see [LICENSE](LICENSE).

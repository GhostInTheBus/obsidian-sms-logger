import json
import logging
import os
import re
import time
from datetime import datetime

from smslog.db import get_db, get_contact_name

STATE_FILE = os.getenv("SMS_EXPORT_STATE_FILE", "/app/data/obsidian_sms_export_state.json")
OBSIDIAN_SMS_PATH = os.getenv("OBSIDIAN_SMS_PATH", "/vault/SMS")
# Display name for the assistant whose outbound replies appear in the logs
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Vi")
INBOX_MAX = 100

_SKIP_EXACT = {"[MMS]", "%http_data", "%sms_body", "Image"}
# iMessage tapback reactions and similar noise
_SKIP_PATTERN = re.compile(
    r'^(Loved|Liked|Disliked|Emphasized|Laughed at|Questioned)\s+[“”‘’”\'«»]',
    re.IGNORECASE,
)

_ROLE_LABELS = {
    "user":      "📲 user",
    "assistant": f"🤖 {ASSISTANT_NAME}",
    "observed":  "👁 observed",
}


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_observed_id": 0, "last_message_id": 0}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s\-]", "", name).strip().replace(" ", "_") or "Unknown"


def _should_skip(content: str) -> bool:
    s = content.strip()
    return s in _SKIP_EXACT or bool(_SKIP_PATTERN.match(s))


def _escape_content(text: str) -> str:
    lines = text.splitlines()
    escaped = [("\\" + l if l.startswith("#") else l) for l in lines]
    return "\n".join(escaped)


# App notifications arrive with the notification title as the sender key,
# e.g. "Messenger: Crystal Renee' Guess" — the person's name is extractable.
_APP_SENDER = re.compile(
    r"^(Messenger|Instagram|WhatsApp|Signal|Telegram|Snapchat|Discord|Slack|Facebook)\s*:\s*(.+)$",
    re.IGNORECASE,
)


def _contact_label(phone: str) -> str:
    name = get_contact_name(phone)
    if name:
        return name
    key = phone.strip()
    m = _APP_SENDER.match(key)
    if m:
        return m.group(2).strip()
    # Non-numeric sender keys (Telegram titles, app senders without a known
    # prefix) are already names — reserve Unknown/ for unknown phone numbers.
    digits = sum(c.isdigit() for c in key)
    if key and digits < len(key) / 2:
        return key
    return f"Unknown {phone}"


def _daily_label(name: str) -> str:
    """Wikilink known contact names in daily-log headers so the vault graph
    connects logs to the rolodex; unknown senders stay plain text."""
    return name if name.startswith("Unknown") else f"[[{name}]]"


def _contact_filepath(phone: str, name: str) -> str:
    contacts_base = os.path.join(OBSIDIAN_SMS_PATH, "Contacts")
    if name.startswith("Unknown"):
        subdir = os.path.join(contacts_base, "Unknown")
        os.makedirs(subdir, exist_ok=True)
        return os.path.join(subdir, f"{phone}.md")
    os.makedirs(contacts_base, exist_ok=True)
    return os.path.join(contacts_base, f"{_safe_filename(name)}.md")


def _append_to_daily(date_str: str, time_str: str, label: str, role_label: str, content: str) -> None:
    daily_dir = os.path.join(OBSIDIAN_SMS_PATH, "Daily")
    os.makedirs(daily_dir, exist_ok=True)
    filepath = os.path.join(daily_dir, f"{date_str}.md")

    # Check existence before opening so the header is only written once
    is_new = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    section = f"### {time_str} · {label} ({role_label})\n{_escape_content(content)}\n"

    with open(filepath, "a") as f:
        if is_new:
            f.write(f"## {date_str}\n\n")
        f.write(section + "\n")


def _append_to_contact_safe(phone: str, name: str, date_str: str, time_str: str, role_label: str, content: str, written_headers: set) -> None:
    filepath = _contact_filepath(phone, name)
    is_new = not os.path.exists(filepath) or os.path.getsize(filepath) == 0
    header_key = (filepath, date_str)

    # Check file on disk only if we haven't tracked this header in memory yet
    if not is_new and header_key not in written_headers:
        with open(filepath, "r") as f:
            existing = f.read()
        if f"## {date_str}" in existing:
            written_headers.add(header_key)

    line = f"- {time_str} ({role_label}): {_escape_content(content)}\n"
    with open(filepath, "a") as f:
        if is_new:
            # Frontmatter links the log to the People/rolodex note of the same
            # name, so SMS history and address book connect in the vault graph.
            person = "" if name.startswith("Unknown") else f'person: "[[{name}]]"\n'
            f.write(
                f'---\nphone: "{phone}"\n{person}'
                f'tags: [sms-log, vi-assist]\nup: "[[SMS Contacts]]"\n---\n\n'
                f"# {name}\n\n"
            )
        if header_key not in written_headers:
            f.write(f"\n## {date_str}\n")
            written_headers.add(header_key)
        f.write(line)


def _rewrite_inbox(rows: list[tuple]) -> None:
    """Rewrite Inbox.md with the most recent INBOX_MAX messages.

    Skips the write when the message body is unchanged — otherwise the
    once-a-minute timestamp refresh churns the file and spawns Syncthing
    conflicts on every device syncing the vault."""
    inbox_path = os.path.join(OBSIDIAN_SMS_PATH, "Inbox.md")
    body = []
    for name, role_label, content, timestamp in rows:
        try:
            dt = datetime.fromisoformat(timestamp)
        except ValueError:
            dt = datetime.utcnow()
        ts = dt.strftime("%Y-%m-%d %H:%M")
        body.append(f"**{ts} · {name}** ({role_label})\n{_escape_content(content)}\n\n---\n\n")
    body_text = "".join(body)
    try:
        with open(inbox_path) as f:
            existing = f.read()
        # Compare everything after the "*Last N messages*" line
        if existing.split("\n\n", 1)[-1] == body_text:
            return
    except FileNotFoundError:
        pass
    header = f"# SMS Inbox\n*Last {INBOX_MAX} messages — updated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC*\n\n"
    with open(inbox_path, "w") as f:
        f.write(header + body_text)


def run_export_cycle() -> int:
    state = _load_state()
    exported = 0
    # Tracks (filepath, date_str) pairs that have had their section header written this cycle
    _written_headers: set[tuple[str, str]] = set()

    with get_db() as conn:
        observed_rows = conn.execute(
            "SELECT id, phone, content, timestamp FROM observed_messages WHERE id > ? ORDER BY id",
            (state["last_observed_id"],),
        ).fetchall()

        message_rows = conn.execute(
            "SELECT id, phone, role, content, timestamp FROM messages WHERE id > ? ORDER BY id",
            (state["last_message_id"],),
        ).fetchall()

        # Fetch recent messages for Inbox.md (both tables, newest first)
        inbox_rows = conn.execute("""
            SELECT phone, 'observed' as role, content, timestamp FROM observed_messages
            WHERE content NOT IN ('[MMS]', '%http_data', '%sms_body', 'Image')
            UNION ALL
            SELECT phone, role, content, timestamp FROM messages
            WHERE content NOT IN ('[MMS]', '%http_data', '%sms_body', 'Image')
            ORDER BY timestamp DESC
            LIMIT ?
        """, (INBOX_MAX,)).fetchall()

    new_observed_id = state["last_observed_id"]
    new_message_id = state["last_message_id"]

    for row_id, phone, content, timestamp in observed_rows:
        new_observed_id = row_id
        if _should_skip(content):
            continue
        try:
            dt = datetime.fromisoformat(timestamp)
        except ValueError:
            dt = datetime.utcnow()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        name = _contact_label(phone)
        _append_to_daily(date_str, time_str, _daily_label(name), "observed", content)
        _append_to_contact_safe(phone, name, date_str, time_str, "observed", content, _written_headers)
        exported += 1

    for row_id, phone, role, content, timestamp in message_rows:
        new_message_id = row_id
        if _should_skip(content):
            continue
        try:
            dt = datetime.fromisoformat(timestamp)
        except ValueError:
            dt = datetime.utcnow()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        name = _contact_label(phone)
        if role == "assistant":
            label = f"🤖 {ASSISTANT_NAME}"
            role_label = f"to {name}"
            daily_label, daily_role = label, f"to {_daily_label(name)}"
        else:
            label = name
            role_label = "📲 incoming"
            daily_label, daily_role = _daily_label(name), role_label
        _append_to_daily(date_str, time_str, daily_label, daily_role, content)
        _append_to_contact_safe(phone, name, date_str, time_str, role_label, content, _written_headers)
        exported += 1

    # Always refresh Inbox.md with latest messages
    inbox_data = [
        (_contact_label(phone), _ROLE_LABELS.get(role, role), content, timestamp)
        for phone, role, content, timestamp in inbox_rows
        if not _should_skip(content)
    ]
    try:
        _rewrite_inbox(inbox_data)
    except Exception as e:
        logging.warning(f"SMS exporter: Inbox.md write failed: {e}")

    if exported:
        _save_state({"last_observed_id": new_observed_id, "last_message_id": new_message_id})
        logging.info(f"SMS exporter: exported {exported} messages to Obsidian")
    elif new_observed_id != state["last_observed_id"] or new_message_id != state["last_message_id"]:
        # Skipped-only cycle — still advance cursors
        _save_state({"last_observed_id": new_observed_id, "last_message_id": new_message_id})

    return exported


def sms_export_loop() -> None:
    logging.info("SMS exporter: started (60s interval)")
    while True:
        try:
            run_export_cycle()
        except Exception as e:
            logging.error(f"SMS exporter error: {e}")
        time.sleep(60)

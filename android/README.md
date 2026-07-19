# Vi-Assist 🤖📲

**Vi-Assist** is the Android companion app for [SMS Logger](../README.md). It
watches incoming message notifications on your phone and forwards them to your
private SMS Logger server — for logging, Obsidian export, and (optionally) an
AI assistant that texts replies back.

## How it reads messages

Vi-Assist uses a **NotificationListenerService**. It does **not** request
`READ_SMS`/`RECEIVE_SMS` permissions and does not need to be your default SMS
app — it sees exactly what your notification shade sees (SMS, and messages
from apps like Messenger/WhatsApp/Telegram that post notifications). This
keeps the permission footprint minimal and Play-policy friendly.

## Features

- **Active mode**: forward a message → server relays it to your assistant →
  the reply is sent back to the sender as an SMS from your phone.
- **Watcher mode**: silent observation — messages are logged, nothing is sent.
- **Whitelist**: only process messages from specific numbers.
- **Privacy first**: you control the server, the secret, and the data.

## Installation

1. Build the APK (below) and sideload it, or grab one from your repo's
   Releases page.
2. Grant **notification access** when prompted (Settings → Notifications →
   Notification access → Vi-Assist).
3. Configure: your server URL (e.g. `http://192.168.1.100:8097` or a
   Tailscale hostname) and your `WEBHOOK_SECRET`.
4. Pick a mode: **Active** or **Watcher**.

> **Plain-HTTP note:** Android blocks cleartext traffic by default. Edit
> `app/src/main/res/xml/network_security_config.xml` and replace the example
> LAN IP / tailnet domain with your own before building, or serve over HTTPS.

## 🍏 iOS workaround

Apple doesn't allow silent SMS interception, but **iOS Shortcuts** gets close:

1. Shortcuts app → **Automation** → **+** → Personal Automation → **Message**.
2. Leave "Message contains" empty (all messages) or filter by sender.
3. Add **Get Contents of URL**:
   - Method: `POST`, URL: `https://your-server/observe`
   - Headers: `X-Webhook-Secret: YOUR_SECRET`
   - JSON body: `type` = `message.phone.received`, `data` → `contact` =
     Shortcut Input (Sender), `content` = Shortcut Input (Message Content)
4. Disable **"Ask Before Running"**.

## 🛠 Building from source

- Android Studio (or JDK 17+) and the Android SDK.
- `cd android && ./gradlew assembleRelease`
- Package: `com.vi.assist`.

### GitHub Actions CI/CD

Pushing a tag starting with `v` (e.g. `v1.0.2`) builds and signs a release
APK. Required repo secrets:

- `SIGNING_KEY`: Base64-encoded `.jks` file
- `ALIAS`: key alias
- `KEY_STORE_PASSWORD`: keystore password
- `KEY_PASSWORD`: key password

## 📜 License

MIT

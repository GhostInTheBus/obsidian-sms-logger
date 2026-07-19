package com.vi.assist

import android.app.Notification
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class SmsNotificationListener : NotificationListenerService() {

    companion object {
        private const val TAG = "ViObserver/NotifListener"

        /**
         * Dynamically find all installed apps that can handle SMS — works on any
         * Android phone regardless of manufacturer or default SMS app choice.
         */
        // Known messaging apps that don't register smsto: but should be monitored
        private val EXTRA_MESSAGING_PACKAGES = setOf(
            "com.google.android.apps.googlevoice",  // Google Voice
            "com.google.android.talk",               // Google Hangouts (legacy)
            "com.discord",                           // Discord DMs
            "org.thoughtcrime.securesms",            // Signal
            "com.whatsapp",                          // WhatsApp
            "com.whatsapp.w4b",                     // WhatsApp Business
            "com.instagram.android",                 // Instagram DMs
            "com.facebook.orca",                     // Messenger
            "com.facebook.mlite",                    // Messenger Lite
            "org.telegram.messenger",                // Telegram
            "org.telegram.messenger.web",            // Telegram X
        )

        private fun getSmsAppPackages(ctx: Context): Set<String> {
            val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:"))
            val resolved = ctx.packageManager.queryIntentActivities(intent, PackageManager.MATCH_ALL)
            return resolved.map { it.activityInfo.packageName }.toSet() + EXTRA_MESSAGING_PACKAGES
        }

        fun hasAccess(ctx: Context): Boolean {
            val flat = Settings.Secure.getString(
                ctx.contentResolver, "enabled_notification_listeners"
            ) ?: return false
            return flat.split(":").any { it.startsWith(ctx.packageName + "/") }
        }

        // Bounded set of recently-forwarded signatures — messaging-style
        // notifications re-post on every update, so dedup avoids re-logging.
        private const val DEDUP_MAX = 200
        private val recentSigs = object : LinkedHashSet<String>() {
            override fun add(element: String): Boolean {
                if (size >= DEDUP_MAX) iterator().let { if (it.hasNext()) { it.next(); it.remove() } }
                return super.add(element)
            }
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (!getSmsAppPackages(this).contains(sbn.packageName)) return
        if (!Prefs.isEnabled(this)) return

        val notification = sbn.notification
        val extras = notification.extras

        val sender = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: return

        // EXTRA_TEXT is the primary message body; fall back to big text for longer messages
        val body = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            ?: ""

        // Image parts, when the app puts them in the notification (Google Messages
        // big-picture; some messaging-style apps expose an image data URI).
        val images = extractImages(notification, extras)

        if (sender.isBlank() || (body.isBlank() && images.isEmpty())) return
        if (!Prefs.isAllowed(this, sender)) return

        val sig = synchronized(recentSigs) {
            val s = "${sbn.key}|$sender|${body.hashCode()}|${images.size}"
            if (!recentSigs.add(s)) return  // already forwarded this exact update
            s
        }

        Log.i(TAG, "notif from $sender: ${body.take(60)} (${images.size} img)")

        val serverUrl = Prefs.serverUrl(this)
        if (serverUrl.isEmpty()) {
            Log.w(TAG, "Server URL not configured in settings")
            return
        }

        val secret = Prefs.secret(this)

        scope.launch {
            val result = if (images.isNotEmpty()) {
                // MMS-with-media → /webhook/mms (logs text + attachments, no reply)
                val atts = JSONArray()
                images.forEachIndexed { i, bytes ->
                    atts.put(JSONObject().apply {
                        put("filename", "notif_${System.currentTimeMillis()}_$i.jpg")
                        put("mime", "image/jpeg")
                        put("base64", Base64.encodeToString(bytes, Base64.NO_WRAP))
                    })
                }
                ApiClient.postMms(serverUrl, secret, sender, body, atts)
            } else {
                val active = Prefs.mode(this@SmsNotificationListener) == "active"
                val path = if (active) "/webhook" else "/observe"
                val r = ApiClient.post(serverUrl, secret, path, sender, body)
                // Active mode: the response body is Vi's reply — send it back
                // through the notification's own inline-reply action (no SMS
                // permissions needed; the reply goes out via the messaging app).
                if (active && r.code == 200 && r.body.isNotBlank()) {
                    val sent = sendInlineReply(sbn, r.body.trim())
                    Prefs.appendLog(this@SmsNotificationListener, sender, r.code,
                        if (sent) "Vi replied" else "reply FAILED (no inline-reply action)")
                    Log.i(TAG, "Vi reply to $sender ${if (sent) "sent" else "FAILED"}: ${r.body.take(60)}")
                }
                r
            }
            Prefs.saveLastResult(this@SmsNotificationListener, sender, result.code)
            Prefs.appendLog(this@SmsNotificationListener, sender, result.code,
                if (images.isNotEmpty()) "MMS ${images.size} img" else "")
            Log.i(TAG, "Forwarded → HTTP ${result.code}")
        }
    }

    /** Fire the notification's inline "Reply" RemoteInput with [text].
     *  Returns false when the notification carries no reply action. */
    private fun sendInlineReply(sbn: StatusBarNotification, text: String): Boolean = runCatching {
        val actions = sbn.notification.actions ?: return false
        val action = actions.firstOrNull { !it.remoteInputs.isNullOrEmpty() } ?: return false
        val intent = Intent()
        val results = Bundle()
        action.remoteInputs!!.forEach { ri -> results.putCharSequence(ri.resultKey, text) }
        android.app.RemoteInput.addResultsToIntent(action.remoteInputs, intent, results)
        action.actionIntent.send(this, 0, intent)
        true
    }.getOrElse {
        Log.w(TAG, "inline reply failed: ${it.message}")
        false
    }

    /** Pull any image bytes the app attached to the notification. Preview-quality,
     *  app-dependent — not the full-resolution original. */
    private fun extractImages(notification: Notification, extras: Bundle): List<ByteArray> {
        val out = mutableListOf<ByteArray>()

        // 1. Big-picture style (Google Messages picture MMS)
        @Suppress("DEPRECATION")
        (extras.getParcelable(Notification.EXTRA_PICTURE) as? Bitmap)?.let { bmp ->
            bitmapToJpeg(bmp)?.let { out += it }
        }

        // 2. Messaging style — newest message may carry an image data URI
        runCatching {
            val style = NotificationCompat.MessagingStyle
                .extractMessagingStyleFromNotification(notification)
            val last = style?.messages?.lastOrNull()
            val uri = last?.dataUri
            if (uri != null && (last.dataMimeType?.startsWith("image/") == true)) {
                contentResolver.openInputStream(uri)?.use { out += it.readBytes() }
            }
        }.onFailure { Log.d(TAG, "messaging-style image extract skipped: ${it.message}") }

        return out
    }

    private fun bitmapToJpeg(bmp: Bitmap): ByteArray? = runCatching {
        ByteArrayOutputStream().use { baos ->
            bmp.compress(Bitmap.CompressFormat.JPEG, 90, baos)
            baos.toByteArray()
        }
    }.getOrNull()
}

package com.vi.assist

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.telephony.SmsManager
import android.telephony.SmsMessage
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class SmsReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "ViObserver/SmsReceiver"
    }

    // A scope that outlives the receiver's onReceive window via goAsync()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != "android.provider.Telephony.SMS_RECEIVED") return
        if (!Prefs.isEnabled(context)) return

        val pendingResult = goAsync()

        val pdus = intent.extras?.get("pdus") as? Array<*> ?: run {
            pendingResult.finish()
            return
        }

        val format = intent.getStringExtra("format")

        val messages = pdus.mapNotNull { pdu ->
            if (pdu !is ByteArray) null
            else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M)
                SmsMessage.createFromPdu(pdu, format)
            else
                @Suppress("DEPRECATION")
                SmsMessage.createFromPdu(pdu)
        }

        if (messages.isEmpty()) {
            pendingResult.finish()
            return
        }

        // Raw originating address — never contact display name
        val sender = messages.first().originatingAddress ?: "unknown"
        val body = messages.joinToString("") { it.messageBody ?: "" }

        if (!Prefs.isAllowed(context, sender)) {
            Log.i(TAG, "SMS from $sender ignored — not on whitelist")
            pendingResult.finish()
            return
        }

        Log.i(TAG, "SMS from $sender: ${body.take(80)}")

        // Ensure the foreground service is running so the process stays alive
        ViService.start(context)

        val serverUrl = Prefs.serverUrl(context)
        val secret = Prefs.secret(context)
        val mode = Prefs.mode(context)

        scope.launch {
            try {
                if (mode == "active") {
                    val result = ApiClient.post(serverUrl, secret, "/webhook", sender, body)
                    Prefs.saveLastResult(context, sender, result.code)
                    Log.i(TAG, "Webhook SMS → HTTP ${result.code}")
                    val reply = result.body.trim()
                    if (reply.isNotEmpty() && result.code in 200..299) {
                        @Suppress("DEPRECATION")
                        val smsManager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
                            context.getSystemService(SmsManager::class.java)
                        else
                            SmsManager.getDefault()
                        smsManager.sendTextMessage(sender, null, reply, null, null)
                        Log.i(TAG, "Sent reply SMS to $sender: ${reply.take(80)}")
                    } else {
                        Log.i(TAG, "No reply to send (body='$reply', code=${result.code})")
                    }
                } else {
                    val result = ApiClient.post(serverUrl, secret, "/observe", sender, body)
                    Prefs.saveLastResult(context, sender, result.code)
                    Log.i(TAG, "Forwarded SMS → HTTP ${result.code}")
                }
            } finally {
                pendingResult.finish()
            }
        }
    }
}

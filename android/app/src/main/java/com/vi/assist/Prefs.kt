package com.vi.assist

import android.content.Context
import androidx.preference.PreferenceManager

object Prefs {

    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_SECRET = "webhook_secret"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_LAST_SENDER = "last_sender"
    private const val KEY_LAST_STATUS = "last_status"
    private const val KEY_LAST_TIME = "last_time"
    private const val KEY_MODE = "mode"
    private const val KEY_WHITELIST = "whitelist_numbers"

    fun serverUrl(ctx: Context): String =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getString(KEY_SERVER_URL, "") ?: ""

    fun secret(ctx: Context): String =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getString(KEY_SECRET, "") ?: ""

    fun mode(ctx: Context): String =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getString(KEY_MODE, "observe") ?: "observe"

    fun isEnabled(ctx: Context): Boolean =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getBoolean(KEY_ENABLED, true)

    fun saveLastResult(ctx: Context, sender: String, statusCode: Int) {
        PreferenceManager.getDefaultSharedPreferences(ctx).edit()
            .putString(KEY_LAST_SENDER, sender)
            .putInt(KEY_LAST_STATUS, statusCode)
            .putLong(KEY_LAST_TIME, System.currentTimeMillis())
            .apply()
    }

    fun lastSender(ctx: Context): String =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getString(KEY_LAST_SENDER, "—") ?: "—"

    fun lastStatus(ctx: Context): Int =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getInt(KEY_LAST_STATUS, 0)

    fun lastTime(ctx: Context): Long =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getLong(KEY_LAST_TIME, 0L)

    fun whitelist(ctx: Context): Set<String> =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getStringSet(KEY_WHITELIST, emptySet()) ?: emptySet()

    fun saveWhitelist(ctx: Context, numbers: Set<String>) =
        PreferenceManager.getDefaultSharedPreferences(ctx).edit()
            .putStringSet(KEY_WHITELIST, numbers)
            .apply()

    fun isAllowed(ctx: Context, number: String): Boolean {
        val list = whitelist(ctx)
        if (list.isEmpty()) return true
        val normalized = number.filter { it.isDigit() }.trimStart('1')
        return list.any { it.filter { c -> c.isDigit() }.trimStart('1') == normalized }
    }

    // ── Event Log ─────────────────────────────────────────────────────────────

    private const val KEY_LOG = "event_log"
    private const val MAX_LOG = 50

    fun appendLog(ctx: Context, sender: String, statusCode: Int, note: String = "") {
        val prefs = PreferenceManager.getDefaultSharedPreferences(ctx)
        val existing = prefs.getString(KEY_LOG, "") ?: ""
        val timestamp = java.text.SimpleDateFormat("MM/dd HH:mm:ss", java.util.Locale.US)
            .format(java.util.Date())
        val result = when {
            statusCode == -1 -> "network error"
            statusCode == 0  -> note.ifEmpty { "—" }
            else             -> "HTTP $statusCode"
        }
        val newEntry = "$timestamp  $sender  →  $result"
        val lines = existing.lines().filter { it.isNotBlank() }.takeLast(MAX_LOG - 1)
        prefs.edit().putString(KEY_LOG, (lines + newEntry).joinToString("\n")).apply()
    }

    fun getLog(ctx: Context): String =
        PreferenceManager.getDefaultSharedPreferences(ctx)
            .getString(KEY_LOG, "") ?: ""
}

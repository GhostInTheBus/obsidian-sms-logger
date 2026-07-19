package com.vi.assist

import android.app.ActivityManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.format.DateFormat
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.util.Date
import android.Manifest

class MainActivity : AppCompatActivity() {

    private lateinit var tvServiceStatus: TextView
    private lateinit var tvLastSender: TextView
    private lateinit var tvLastStatus: TextView
    private lateinit var tvLastTime: TextView
    private lateinit var tvPermissionStatus: TextView
    private lateinit var tvWhitelistStatus: TextView
    private lateinit var tvLog: TextView
    private lateinit var btnToggleService: Button
    private lateinit var btnGrantAccess: Button

    private val refreshHandler = Handler(Looper.getMainLooper())
    private val refreshRunnable = object : Runnable {
        override fun run() {
            updateUi()
            refreshHandler.postDelayed(this, 3000)
        }
    }

    private val requestPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { updateUi() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        setSupportActionBar(findViewById(R.id.toolbar))

        tvServiceStatus    = findViewById(R.id.tvServiceStatus)
        tvLastSender       = findViewById(R.id.tvLastSender)
        tvLastStatus       = findViewById(R.id.tvLastStatus)
        tvLastTime         = findViewById(R.id.tvLastTime)
        tvPermissionStatus = findViewById(R.id.tvPermissionStatus)
        tvWhitelistStatus  = findViewById(R.id.tvWhitelistStatus)
        tvLog              = findViewById(R.id.tvLog)
        btnToggleService   = findViewById(R.id.btnToggleService)
        btnGrantAccess     = findViewById(R.id.btnGrantAccess)

        btnToggleService.setOnClickListener { toggleService() }
        btnGrantAccess.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }

        findViewById<Button>(R.id.btnSettings).setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        requestNeededPermissions()
    }

    override fun onResume() {
        super.onResume()
        updateUi()
        refreshHandler.postDelayed(refreshRunnable, 3000)
    }

    override fun onPause() {
        super.onPause()
        refreshHandler.removeCallbacks(refreshRunnable)
    }

    private fun updateUi() {
        val notifAccess  = SmsNotificationListener.hasAccess(this)
        val notifGranted = hasPermission(Manifest.permission.POST_NOTIFICATIONS)

        tvPermissionStatus.text = buildString {
            append("Notification Access: ${if (notifAccess) "✓" else "✗"}  ")
            append("Alerts: ${if (notifGranted) "✓" else "✗"}")
        }

        btnGrantAccess.visibility = if (notifAccess) android.view.View.GONE else android.view.View.VISIBLE

        val whitelist = Prefs.whitelist(this)
        tvWhitelistStatus.text = if (whitelist.isEmpty()) "Whitelist: all numbers"
            else "Whitelist: ${whitelist.size} number${if (whitelist.size == 1) "" else "s"}"

        val running = isServiceRunning()
        val mode    = Prefs.mode(this)
        tvServiceStatus.text = buildString {
            append(if (running) "● Running" else "○ Stopped")
            append("  [${if (mode == "active") "Active" else "Observer"}]")
        }
        tvServiceStatus.setTextColor(
            getColor(if (running) android.R.color.holo_green_dark else android.R.color.holo_red_dark)
        )
        btnToggleService.text = if (running) "Stop Service" else "Start Service"

        val lastSender = Prefs.lastSender(this)
        val lastStatus = Prefs.lastStatus(this)
        val lastTime   = Prefs.lastTime(this)

        tvLastSender.text = lastSender
        tvLastStatus.text = when {
            lastStatus == 0  -> "—"
            lastStatus == -1 -> "Network error"
            else             -> "HTTP $lastStatus ✓"
        }
        tvLastStatus.setTextColor(getColor(
            if (lastStatus in 200..299) android.R.color.holo_green_dark
            else if (lastStatus == 0) android.R.color.darker_gray
            else android.R.color.holo_red_dark
        ))
        tvLastTime.text = if (lastTime == 0L) "—"
            else DateFormat.format("MMM d, h:mm a", Date(lastTime)).toString()

        val log = Prefs.getLog(this)
        tvLog.text = if (log.isBlank()) "No events yet." else log.lines().takeLast(20).reversed().joinToString("\n")
    }

    private fun toggleService() {
        if (isServiceRunning()) {
            ViService.stop(this)
        } else {
            ViService.start(this)
        }
        updateUi()
    }

    @Suppress("DEPRECATION")
    private fun isServiceRunning(): Boolean {
        val am = getSystemService(ActivityManager::class.java)
        return am.getRunningServices(Int.MAX_VALUE)
            .any { it.service.className == ViService::class.java.name }
    }

    private fun hasPermission(permission: String) =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    private fun requestNeededPermissions() {
        val needed = mutableListOf<String>()
        if (!hasPermission(Manifest.permission.POST_NOTIFICATIONS))
            needed += Manifest.permission.POST_NOTIFICATIONS
        if (needed.isNotEmpty())
            requestPermissions.launch(needed.toTypedArray())
    }
}

package com.vi.assist

import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class ApiResult(val code: Int, val body: String)

object ApiClient {

    private const val TAG = "ViObserver/ApiClient"

    // readTimeout must cover Vi's full reply pipeline in active mode
    // (LLM + memory work can take 10-30s; nginx allows 120s).
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private val JSON = "application/json; charset=utf-8".toMediaType()

    /**
     * Post an SMS to the given path. Returns the HTTP status code and response body,
     * or code=-1 and empty body on network error.
     */
    fun post(serverUrl: String, secret: String, path: String, sender: String, body: String): ApiResult {
        val endpoint = serverUrl.trimEnd('/') + path

        val payload = JSONObject().apply {
            put("type", "message.phone.received")
            put("data", JSONObject().apply {
                put("contact", sender)
                put("content", body)
            })
        }

        val request = Request.Builder()
            .url(endpoint)
            .addHeader("X-Webhook-Secret", secret)
            .addHeader("Content-Type", "application/json")
            .post(payload.toString().toRequestBody(JSON))
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                val responseBody = response.body?.string() ?: ""
                Log.i(TAG, "POST $endpoint → ${response.code}")
                ApiResult(response.code, responseBody)
            }
        } catch (e: Exception) {
            Log.e(TAG, "POST $endpoint failed: ${e.message}")
            ApiResult(-1, "")
        }
    }

    /**
     * Post an MMS (text + base64 media attachments) to /webhook/mms.
     * Returns the HTTP status code, or code=-1 on network error.
     */
    fun postMms(serverUrl: String, secret: String, sender: String, text: String, attachments: JSONArray): ApiResult {
        val endpoint = serverUrl.trimEnd('/') + "/webhook/mms"

        val payload = JSONObject().apply {
            put("type", "message.mms.received")
            put("payload", JSONObject().apply {
                put("phoneNumber", sender)
                put("content", text)
                put("attachments", attachments)
            })
        }

        val request = Request.Builder()
            .url(endpoint)
            .addHeader("X-Webhook-Secret", secret)
            .addHeader("Content-Type", "application/json")
            .post(payload.toString().toRequestBody(JSON))
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                Log.i(TAG, "POST $endpoint (${attachments.length()} media) → ${response.code}")
                ApiResult(response.code, response.body?.string() ?: "")
            }
        } catch (e: Exception) {
            Log.e(TAG, "MMS POST $endpoint failed: ${e.message}")
            ApiResult(-1, "")
        }
    }
}

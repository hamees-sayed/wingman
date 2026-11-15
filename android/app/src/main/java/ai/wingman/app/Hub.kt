package ai.wingman.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** What the Live screen shows, in the order it happened. */
sealed interface Entry {
    data class Line(val who: String, var label: String, val text: String) : Entry
    data class Whisper(
        val id: String?, val kind: String, val text: String, val why: String,
        val outcome: String, val latency: Double?,
    ) : Entry
    data class Promise(val by: String, val person: String, val what: String, val due: String) : Entry
    data class Note(val title: String, val body: String) : Entry
}

/** One turn in the chat with the agent. */
data class ChatMessage(
    val role: String, val text: String,
    val steps: List<String> = emptyList(), val sources: List<String> = emptyList(),
) {
    companion object {
        fun from(answer: JSONObject): ChatMessage {
            fun list(key: String) = answer.optJSONArray(key)?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
            return ChatMessage("wingman", answer.optString("reply"), list("steps"), list("sources"))
        }
    }
}

/** State shared by the listening service and the screens. */
object Hub {
    val entries = mutableStateListOf<Entry>()
    var interim by mutableStateOf("")
    var listening by mutableStateOf(false)
    var whispering by mutableStateOf(false)
    var hearing by mutableStateOf(false) // someone is speaking right now
    var level by mutableStateOf(0f) // how loud the microphone is, 0 to 1
    var status by mutableStateOf("Paused")
    var error by mutableStateOf<String?>(null)
    var ownerEnrolled by mutableStateOf(true)
    var enrolling by mutableStateOf(false)
    var enrolMessage by mutableStateOf("")
    var refresh by mutableStateOf(0) // bumped when a conversation ends, so lists reload
    val chat = mutableStateListOf<ChatMessage>()
    var shared by mutableStateOf<Pair<String, String>?>(null) // source and text shared in from another app
    var talking by mutableStateOf(false) // the talk button is held
    var thinking by mutableStateOf(false) // the agent is working on an answer

    private val main = Handler(Looper.getMainLooper())
    fun onMain(block: () -> Unit) = main.post(block)

    fun handle(event: JSONObject) = onMain {
        when (event.optString("type")) {
            "started" -> {
                if (!event.optBoolean("continued")) entries.clear()
                interim = ""; error = null
                listening = true; status = "Listening"
                ownerEnrolled = event.optBoolean("ownerEnrolled", true)
            }
            "speech" -> hearing = event.optBoolean("speaking")
            "interim" -> interim = event.optString("text")
            "line" -> {
                interim = ""
                entries += Entry.Line(event.optString("who"), event.optString("label"), event.optString("text"))
            }
            "relabel" -> {
                val from = event.optString("from"); val to = event.optString("to")
                for (index in entries.indices) {
                    val entry = entries[index]
                    if (entry is Entry.Line && entry.label == from) entries[index] = entry.copy(who = "other", label = to)
                }
            }
            "whisper" -> { refresh++; entries += Entry.Whisper(
                event.optString("id").ifEmpty { null }.takeIf { !event.isNull("id") },
                event.optString("kind"), event.optString("text"), event.optString("why"),
                event.optString("outcome"),
                if (event.isNull("latency")) null else event.optDouble("latency"),
            ) }
            "promise" -> {
                entries += Entry.Promise(
                    event.optString("by"), event.optString("person"), event.optString("what"), event.optString("due"),
                )
                refresh++
            }
            "person", "task", "suggestions" -> refresh++
            "reminder" -> { entries += Entry.Note("Reminder", event.optString("text")); refresh++ }
            "research" -> {
                entries += Entry.Note(if (event.optBoolean("ok", true)) "Research ready" else "Research could not be finished", event.optString("topic"))
                refresh++
            }
            "recap" -> {
                // Always-on closed one conversation by itself and is already in the next.
                if (!event.isNull("conversation")) {
                    entries += Entry.Note(event.optString("title", "Recap ready"), event.optString("summary"))
                }
                refresh++
            }
            "superseded" -> { listening = false; hearing = false; whispering = false; status = "Listening on your other device" }
            "ending" -> status = "Writing recap"
            "ended" -> {
                listening = false; whispering = false; hearing = false; status = "Paused"; interim = ""
                if (!event.isNull("conversation")) {
                    entries += Entry.Note(event.optString("title", "Recap ready"), event.optString("summary"))
                }
                refresh++
            }
            "enrolling" -> { enrolling = true; enrolMessage = "Recording… keep reading." }
            "enrolled" -> {
                enrolling = false
                if (event.optBoolean("ok")) { ownerEnrolled = true; enrolMessage = "Voice sample saved." }
                else enrolMessage = event.optString("message")
            }
            "error" -> error = event.optString("message")
            "clear_error" -> error = null
        }
    }
}

/** Where the Wingman server is, and plain JSON calls to it for the screens other than Live. */
object Server {
    private const val PREFS = "wingman"
    private const val KEY = "server"
    val DEFAULT: String = BuildConfig.WINGMAN_SERVER  // set in android/local.properties
    // Sent with every request so a server reachable from the internet only answers this app.
    private val APP_KEY: String = BuildConfig.WINGMAN_KEY  // set in android/local.properties
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val request = chain.request().newBuilder().header("X-Wingman-Key", APP_KEY)
            // Which account this install is. Everything Wingman keeps is kept per account.
            if (account.isNotEmpty() && chain.request().header("X-Wingman-User") == null) request.header("X-Wingman-User", account)
            chain.proceed(request.build())
        }
        .build()

    /** This install's account, sent with every request. Empty until [start] has run. */
    @Volatile var account: String = ""

    /**
     * Each install has its own account: a long random secret made on first launch and kept on
     * the phone. An install from before accounts existed keeps talking as it always did until
     * the server has moved its data into the new account (see [claim]).
     */
    fun start(context: Context) {
        var token = pref(context, "account")
        if (token == null) {
            val bytes = ByteArray(24).also { java.security.SecureRandom().nextBytes(it) }
            token = bytes.joinToString("") { "%02x".format(it) }
            setPref(context, "account", token)
            setPref(context, "claim", if (pref(context, "onboarded") == "yes") "pending" else "none")
        }
        account = if (pref(context, "claim") == "pending") "" else token
    }

    /** Moves the data of an install from before accounts into its account. Safe to call often. */
    suspend fun claim(context: Context) {
        if (pref(context, "claim") != "pending") return
        val token = pref(context, "account") ?: return
        val done = withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder().url("${base(context)}/api/account/claim").header("X-Wingman-User", token)
                    .post("{}".toRequestBody("application/json".toMediaType())).build()
                http.newCall(request).execute().use { it.isSuccessful && JSONObject(it.body?.string() ?: "{}").optBoolean("ok") }
            } catch (error: Exception) { false }
        }
        if (done) { setPref(context, "claim", "done"); account = token }
    }

    /** A page on the server opened in the browser, which cannot send the account any other way. */
    fun page(context: Context, path: String) = "${base(context)}$path" + if (account.isNotEmpty()) "?u=$account" else ""

    fun address(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, DEFAULT) ?: DEFAULT

    fun pref(context: Context, key: String): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(key, null)

    fun setPref(context: Context, key: String, value: String) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(key, value).apply()

    /**
     * The server that does the work runs close to its owner, at an address that changes when it
     * restarts. The fixed address built into the app is a front door that knows where it is now.
     * Asked at launch and again whenever the connection is lost.
     */
    fun locate(context: Context) {
        if (address(context) != DEFAULT) return  // the owner pointed the app at a server of their own
        try {
            val request = Request.Builder().url("https://$DEFAULT/where").build()
            val found = http.newCall(request).execute().use { if (it.isSuccessful) JSONObject(it.body?.string() ?: "{}").optString("url") else "" }
            if (found.startsWith("https://")) setPref(context, "found", found)
        } catch (error: Exception) { /* keep the last known address */ }
    }

    /** The server's web address: https for a public name, plain http for a local address and port. */
    fun base(context: Context): String {
        val address = address(context)
        if (address == DEFAULT) pref(context, "found")?.takeIf { it.startsWith("https://") }?.let { return it }
        return when {
            address.startsWith("http") -> address
            address.any { it.isLetter() } && !address.contains(":") -> "https://$address"
            else -> "http://$address"
        }
    }

    fun setAddress(context: Context, value: String) {
        val clean = value.trim().removePrefix("http://").removePrefix("ws://").removePrefix("wss://").trimEnd('/')
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, clean).apply()
    }

    fun socketUrl(context: Context) = base(context).replaceFirst("http", "ws") + "/ws"

    suspend fun call(context: Context, method: String, path: String, body: JSONObject? = null): String? =
        withContext(Dispatchers.IO) {
            try {
                val payload = (body ?: JSONObject()).toString().toRequestBody("application/json".toMediaType())
                val request = Request.Builder().url("${base(context)}$path").let {
                    when (method) {
                        "POST" -> it.post(payload)
                        "DELETE" -> it.delete()
                        else -> it.get()
                    }
                }.build()
                http.newCall(request).execute().use { response ->
                    if (response.isSuccessful) response.body?.string() else null
                }
            } catch (error: Exception) {
                null
            }
        }
}

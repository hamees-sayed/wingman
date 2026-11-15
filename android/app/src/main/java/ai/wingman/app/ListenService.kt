package ai.wingman.app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Base64
import androidx.core.content.ContextCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

/**
 * Always-on listening, in the foreground with a permanent notification, plus whisper playback.
 *
 * Once started it keeps listening until the owner pauses it, reconnecting by itself if the
 * server drops. Microphone audio goes up as mono PCM16 at 16 kHz, 100 ms at a time. A whisper
 * comes back as a short clip and plays on whatever output the phone is routed to, lowering
 * other audio while it plays. Holding the talk button borrows the same microphone: those
 * seconds go to the agent instead of into the conversation.
 */
class ListenService : Service() {
    private var socket: WebSocket? = null
    @Volatile private var capturing = false
    @Volatile private var talk: ByteArrayOutputStream? = null
    private var track: AudioTrack? = null
    private var focus: AudioFocusRequest? = null
    private val main = Handler(Looper.getMainLooper())
    private var mode = MODE_IDLE
    private var enrolName = "Me"

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Server.start(this)  // Android may start the service on its own, before any screen has
        when (intent?.action) {
            ACTION_START -> { Server.setPref(this, "paused", "no"); Wake.listening(this); begin(MODE_LISTEN) }
            ACTION_ENROLL -> { enrolName = intent.getStringExtra(EXTRA_TEXT) ?: "Me"; begin(MODE_ENROLL) }
            ACTION_ASK -> intent.getStringExtra(EXTRA_TEXT)?.let { send("ask", "text" to it) }
            ACTION_TALK_START -> talkStart()
            ACTION_TALK_STOP -> talkStop()
            ACTION_STOP -> { Server.setPref(this, "paused", "yes"); finish() }
        }
        return START_STICKY
    }

    private fun allowed() = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
        PackageManager.PERMISSION_GRANTED

    private fun foreground(text: String) {
        val notification = notification(text)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(1, notification)
        }
    }

    private fun begin(newMode: Int) {
        if (!allowed()) {
            Hub.onMain { Hub.error = "Wingman needs the microphone permission." }
            stopSelf(); return
        }
        if (socket != null && mode == newMode) return
        socket?.cancel(); socket = null
        mode = newMode
        foreground(if (mode == MODE_ENROLL) "Learning your voice" else "Listening. Tap to open, or pause.")
        connect()
    }

    private fun connect() {
        Hub.onMain { if (!Hub.listening) Hub.status = "Connecting"; Hub.error = null }
        val request = Request.Builder().url(Server.socketUrl(this)).build()
        socket = Server.http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (mode == MODE_ENROLL) {
                    send("enroll_start", "name" to enrolName)
                    main.postDelayed({ send("enroll_stop") }, ENROLL_MS)
                } else {
                    send("start")
                }
                startCapture()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = runCatching { JSONObject(text) }.getOrNull() ?: return
                when (event.optString("type")) {
                    "audio" -> when {
                        // A check-in is never said out of the phone's speaker: earbuds, or a notification.
                        event.optString("kind") == "checkin" && noEarbuds() -> remindOnScreen("Wingman", event.optString("text"))
                        !silentWithoutEarbuds() -> play(event.optString("pcm"), event.optInt("sampleRate", RATE))
                    }
                    "whisper" -> {
                        Hub.handle(event)
                        if (event.optString("outcome") == "spoken" && event.optString("kind") != "checkin" && silentWithoutEarbuds())
                            remindOnScreen("Wingman", event.optString("text"))
                    }
                    "stop_audio" -> stopPlaying()
                    "reminder" -> { Hub.handle(event); remindOnScreen("Reminder", event.optString("text")) }
                    "research" -> { Hub.handle(event); remindOnScreen("Research ready", event.optString("topic")) }
                    "enrolled" -> {
                        Hub.handle(event)
                        // After the voice sample, carry straight on into always-on listening.
                        main.post {
                            webSocket.close(1000, null); socket = null
                            if (event.optBoolean("ok") && Server.pref(this@ListenService, "paused") != "yes") {
                                begin(MODE_LISTEN)
                            } else shutdown()
                        }
                    }
                    "ended" -> { Hub.handle(event); main.post { shutdown() } }
                    // Another of the owner's devices took over listening; step aside quietly.
                    "superseded" -> main.post { mode = MODE_IDLE; shutdown(); Hub.handle(event) }
                    else -> Hub.handle(event)
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { dropped(webSocket) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { dropped(webSocket) }
        })
    }

    /** The connection went away. Always-on means trying again, unless the owner paused. */
    private fun dropped(which: WebSocket) = main.post {
        if (socket !== which) return@post
        socket = null
        Hub.listening = false; Hub.hearing = false; Hub.enrolling = false
        if (mode == MODE_LISTEN && Server.pref(this, "paused") != "yes") {
            Hub.status = "Reconnecting"
            Hub.error = "Cannot reach the Wingman server at ${Server.address(this)}. Retrying."
            // The server may have moved: ask the front door where it is, then try again.
            Thread {
                Server.locate(this)
                main.postDelayed({ if (socket == null && mode == MODE_LISTEN) connect() }, 2500)
            }.start()
        } else {
            Hub.status = "Paused"
            shutdown()
        }
    }

    /** Pause: tell the server, stop the microphone, and wait for the recap before closing. */
    private fun finish() {
        if (socket == null) { shutdown(); return }
        stopCapture(); stopPlaying()
        Hub.onMain { Hub.status = "Writing recap" }
        send("stop")
        main.postDelayed({ shutdown() }, 20_000)
    }

    private fun shutdown() {
        mode = MODE_IDLE
        stopCapture(); stopPlaying()
        socket?.close(1000, null); socket = null
        main.removeCallbacksAndMessages(null)
        Hub.onMain { Hub.listening = false; Hub.hearing = false; if (!Hub.status.startsWith("Listening on")) Hub.status = "Paused" }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun send(type: String, vararg fields: Pair<String, String>) {
        val message = JSONObject().put("type", type)
        fields.forEach { (key, value) -> message.put(key, value) }
        socket?.send(message.toString())
    }

    // --- Microphone ---------------------------------------------------------------------

    @Suppress("MissingPermission") // checked in begin() and talkStart()
    private fun openRecorder(): AudioRecord? {
        val minimum = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, CHUNK_BYTES * 4),
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) { record.release(); return null }
        record.startRecording()
        return record
    }

    private fun startCapture() {
        if (capturing) return
        var record = openRecorder()
        if (record == null) {
            Hub.onMain { Hub.error = "Could not open the microphone." }
            return
        }
        capturing = true
        thread(name = "wingman-mic") {
            val buffer = ByteArray(CHUNK_BYTES)
            var deadChunks = 0
            while (capturing) {
                val current = record ?: break
                var filled = 0
                while (capturing && filled < buffer.size) {
                    val read = current.read(buffer, filled, buffer.size - filled)
                    if (read <= 0) break
                    filled += read
                }
                if (filled != buffer.size) continue
                // Loudness of this tenth of a second, for the waveform on screen.
                var peak = 0
                var index = 0
                while (index < filled) {
                    val sample = (buffer[index + 1].toInt() shl 8) or (buffer[index].toInt() and 0xFF)
                    if (sample > peak) peak = sample else if (-sample > peak) peak = -sample
                    index += 2
                }
                Hub.level = (peak / 9000f).coerceIn(0f, 1f)
                // Eight seconds of exact zeros means the stream has died, not that the room is
                // quiet: reopen the microphone rather than listen to nothing.
                deadChunks = if (peak == 0) deadChunks + 1 else 0
                if (deadChunks >= 80) {
                    deadChunks = 0
                    runCatching { current.stop() }; current.release()
                    record = openRecorder()
                    continue
                }
                val toAgent = talk
                if (toAgent != null) toAgent.write(buffer, 0, filled)
                else socket?.send(buffer.toByteString(0, filled))
            }
            record?.let { runCatching { it.stop() }; it.release() }
        }
    }

    private fun stopCapture() { capturing = false }

    // --- Talking to the agent -----------------------------------------------------------

    private fun talkStart() {
        if (!allowed()) { Hub.onMain { Hub.error = "Wingman needs the microphone permission." }; return }
        stopPlaying()
        talk = ByteArrayOutputStream()
        if (!capturing) { foreground("Listening to your question"); startCapture() }
        Hub.onMain { Hub.talking = true }
    }

    private fun talkStop() {
        val clip = talk?.toByteArray() ?: return
        talk = null
        if (mode == MODE_IDLE) stopCapture()
        Hub.onMain { Hub.talking = false; Hub.thinking = true }
        thread(name = "wingman-ask") {
            val answer = runCatching {
                val request = Request.Builder().url("${Server.base(this)}/api/chat/voice")
                    .post(clip.toRequestBody("application/octet-stream".toMediaType())).build()
                Server.http.newCall(request).execute().use { response ->
                    if (response.isSuccessful) JSONObject(response.body?.string() ?: "{}") else null
                }
            }.getOrNull()
            Hub.onMain {
                Hub.thinking = false
                if (answer == null) Hub.chat += ChatMessage("wingman", "I could not hear that, or the server did not answer.")
                else {
                    val heard = answer.optString("heard")
                    if (heard.isNotEmpty()) Hub.chat += ChatMessage("you", heard)
                    Hub.chat += ChatMessage.from(answer)
                }
            }
            answer?.optString("audio")?.takeIf { it.isNotEmpty() && it != "null" }?.let {
                main.post { play(it, answer.optInt("sampleRate", RATE)) }
            }
            if (mode == MODE_IDLE) main.postDelayed({ if (mode == MODE_IDLE && track == null) shutdown() }, 30_000)
        }
    }

    // --- Whispers and spoken answers ----------------------------------------------------

    private fun play(encoded: String, rate: Int) {
        val pcm = Base64.decode(encoded, Base64.DEFAULT)
        if (pcm.isEmpty()) return
        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ASSISTANT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        val manager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        // Lower whatever else is playing for the moment the whisper takes.
        focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(attributes).build().also { manager.requestAudioFocus(it) }
        stopTrack()
        val player = AudioTrack.Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(
                AudioFormat.Builder().setSampleRate(rate)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build()
            )
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(pcm.size)
            .build()
        player.write(pcm, 0, pcm.size)
        track = player
        Hub.onMain { Hub.whispering = true }
        player.play()
        main.postDelayed({ if (track === player) stopPlaying() }, pcm.size * 1000L / (rate * 2) + 150)
    }

    private fun stopTrack() {
        track?.let { runCatching { it.stop() }; it.release() }
        track = null
    }

    private fun stopPlaying() {
        stopTrack()
        focus?.let { (getSystemService(Context.AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(it) }
        focus = null
        Hub.onMain { Hub.whispering = false }
    }

    // --- Notification -------------------------------------------------------------------

    private fun notification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Listening", NotificationManager.IMPORTANCE_LOW)
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val pause = PendingIntent.getService(
            this, 1, Intent(this, ListenService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Wingman is with you").setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true).setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Pause", pause).build())
            .build()
    }

    /** With "Only speak in earbuds" on and nothing in the ears, a whisper is shown instead of said. */
    private fun silentWithoutEarbuds(): Boolean = Server.pref(this, "earbudsOnly") == "1" && noEarbuds()

    private fun noEarbuds(): Boolean {
        val manager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val private = setOf(
            android.media.AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, android.media.AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
            android.media.AudioDeviceInfo.TYPE_BLE_HEADSET, android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET,
            android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES, android.media.AudioDeviceInfo.TYPE_USB_HEADSET,
        )
        return manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS).none { it.type in private }
    }

    /** A reminder is spoken, and also shown, in case the earbuds are out. */
    private fun remindOnScreen(title: String, text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("reminders", "Reminders", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify((System.currentTimeMillis() % 100000).toInt() + 10, Notification.Builder(this, "reminders")
            .setContentTitle(title).setContentText(text.replaceFirstChar { it.uppercase() })
            .setSmallIcon(android.R.drawable.ic_popup_reminder).setAutoCancel(true).setContentIntent(open).build())
    }

    override fun onDestroy() {
        stopCapture(); stopTrack()
        socket?.cancel(); socket = null
        // Stopped without the owner pausing it: Android ended it. Say so, rather than fall silent.
        if (Server.pref(this, "paused") != "yes" && Server.pref(this, "onboarded") == "yes")
            Wake.stopped(this, "Android stopped it in the background.")
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "ai.wingman.app.START"
        const val ACTION_STOP = "ai.wingman.app.STOP"
        const val ACTION_ENROLL = "ai.wingman.app.ENROLL"
        const val ACTION_ASK = "ai.wingman.app.ASK"
        const val ACTION_TALK_START = "ai.wingman.app.TALK_START"
        const val ACTION_TALK_STOP = "ai.wingman.app.TALK_STOP"
        const val EXTRA_TEXT = "text"
        private const val CHANNEL = "listening"
        private const val RATE = 16000
        private const val CHUNK_BYTES = RATE * 2 / 10
        private const val MODE_IDLE = -1
        private const val MODE_LISTEN = 0
        private const val MODE_ENROLL = 1
        const val ENROLL_MS = 10_000L

        fun run(context: Context, action: String, text: String? = null) {
            val intent = Intent(context, ListenService::class.java).setAction(action)
            if (text != null) intent.putExtra(EXTRA_TEXT, text)
            if (action in listOf(ACTION_START, ACTION_ENROLL, ACTION_TALK_START)) context.startForegroundService(intent)
            else context.startService(intent)
        }
    }
}

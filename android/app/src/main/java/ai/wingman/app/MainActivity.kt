package ai.wingman.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import com.google.android.gms.auth.api.identity.Identity
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.outlined.Checklist
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Notes
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        takeShared(intent)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(statusBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT))
        super.onCreate(savedInstanceState)
        Server.start(this)  // this install's account, before anything talks to the server
        takeShared(intent)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Accent, background = Paper, surface = Color.White, onSurface = Ink)) {
                Surface(color = Paper, modifier = Modifier.fillMaxSize()) { Root() }
            }
        }
    }
}

/** Text shared from another app, such as Claude's answer about what it remembers. */
private fun ComponentActivity.takeShared(intent: Intent?) {
    val text = when (intent?.action) {
        Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)
        Intent.ACTION_PROCESS_TEXT -> intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)?.toString()
        else -> null
    }
    if (!text.isNullOrBlank()) Hub.shared = Phone.sourceOf(referrer?.host) to text
}

private fun hasMic(context: Context) =
    ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

@Composable
private fun Root() {
    val context = LocalContext.current
    var onboarded by remember { mutableStateOf(Server.pref(context, "onboarded") == "yes") }
    // Status bar icons: light over the dark onboarding, dark over the paper app.
    val view = LocalView.current
    SideEffect {
        (context as? ComponentActivity)?.window?.let { WindowCompat.getInsetsController(it, view).isAppearanceLightStatusBars = onboarded }
    }
    if (!onboarded) Onboarding { Server.setPref(context, "onboarded", "yes"); onboarded = true }
    else App { Server.setPref(context, "onboarded", "no"); onboarded = false }
}

private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
private fun clock(ms: Long): String = SimpleDateFormat("h:mm a", Locale.getDefault()).format(Date(ms)).lowercase()
private fun day(ms: Long): String = SimpleDateFormat("EEE d MMM", Locale.getDefault()).format(Date(ms))
private fun owes(p: JSONObject) = if (p.optString("by") == "you") "You owe ${p.optString("person")} ${p.optString("what")}"
    else "${p.optString("person")} owes you ${p.optString("what")}"

@Composable
private fun <T> rememberLoaded(path: String, every: Long = 0, parse: (String) -> T): Pair<T?, () -> Unit> {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var value by remember(path) { mutableStateOf<T?>(null) }
    suspend fun pull() { Server.call(context, "GET", path)?.let { body -> runCatching { parse(body) }.getOrNull()?.let { value = it } } }
    LaunchedEffect(path, Hub.refresh) { pull(); if (every > 0) while (true) { delay(every); pull() } }
    return value to { scope.launch { pull() }; Unit }
}

// --- Onboarding --------------------------------------------------------------------------------

@Composable
private fun Onboarding(done: () -> Unit) {
    val context = LocalContext.current
    var step by remember { mutableStateOf(0) }
    var name by remember { mutableStateOf(Server.pref(context, "name") ?: "") }
    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted[Manifest.permission.RECORD_AUDIO] == true) { Hub.error = null; step = 3 }
        else Hub.error = "Wingman cannot work without the microphone. Allow it to continue."
    }
    BackHandler(enabled = (step in 1..3 || step == 5) && !Hub.enrolling) { step -= 1 }

    Column(Modifier.fillMaxSize().night().statusBarsPadding().navigationBarsPadding().imePadding().padding(horizontal = 26.dp)) {
        Row(Modifier.padding(top = 18.dp).fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Label("Wingman", Color.White)
            Spacer(Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                repeat(7) { Box(Modifier.width(if (it == step) 22.dp else 6.dp).height(6.dp).clip(CircleShape).background(Color.White.copy(alpha = if (it <= step) 1f else 0.25f))) }
            }
        }
        AnimatedContent(step, modifier = Modifier.weight(1f), label = "step",
            transitionSpec = { (slideInHorizontally { it / 3 } + fadeIn()) togetherWith (slideOutHorizontally { -it / 3 } + fadeOut()) }) { current ->
            Column(Modifier.fillMaxSize()) {
                when (current) {
                    0 -> {
                        Spacer(Modifier.weight(0.7f))
                        Wave(0.5f, true, Color.White, Modifier.fillMaxWidth().height(86.dp))
                        Spacer(Modifier.weight(0.5f))
                        Display("Your second\nbrain.", 46.sp, Color.White)
                        Display("Always\nlistening.", 46.sp, Color(0xFF9DB1FF), italic = true)
                        Spacer(Modifier.height(16.dp))
                        Body("A personal assistant that hears your day and remembers it for you. It gives you the name you forgot, keeps the promises you made, and answers when you ask. Only you hear it.", 16.sp, NightText)
                        Spacer(Modifier.weight(1f))
                        Label("What should it call you?", NightText)
                        BasicTextField(name, { name = it }, singleLine = true, cursorBrush = SolidColor(Color.White),
                            textStyle = TextStyle(color = Color.White, fontSize = 30.sp, fontFamily = Serif),
                            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Done),
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp),
                            decorationBox = { inner -> Box { if (name.isEmpty()) Display("Your first name", 30.sp, Color(0x66FFFFFF)); inner() } })
                        Rule(Color(0x40FFFFFF))
                        Spacer(Modifier.height(22.dp))
                        Next("Continue", name.isNotBlank()) { Server.setPref(context, "name", name.trim()); step = 1 }
                    }
                    1 -> {
                        Spacer(Modifier.height(34.dp))
                        Display("It hears your day.", 38.sp, Color.White)
                        Display("And handles the rest.", 38.sp, Color(0xFF9DB1FF), italic = true)
                        Spacer(Modifier.height(14.dp))
                        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                            Moment("When you blank", "“What's his name, the guy from design…”", "Rahul.", "whispered in your ear, two seconds later")
                            Moment("When you have something to add", "“I just joined a gym, no idea what routine to follow.”", "Mention your push-pull-legs plan.", "it knows you, so it knows what is worth saying")
                            Moment("When you promise", "“I'll send you the deck by Friday.”", "On your to-do list.", "added silently, with a recap of the whole conversation")
                            Moment("When you ask", "“Wingman, move my three o'clock to four thirty.”", "Moved.", "calendar, reminders, notes, Slack, and research in the background")
                            Moment("When you're lost", "“He called the launch plan a Hail Mary.”", "A long shot.", "the phrase, the jargon or the Hindi you missed, explained")
                        }
                        Spacer(Modifier.height(12.dp))
                        Next("Continue") { step = 2 }
                    }
                    2 -> {
                        Spacer(Modifier.weight(0.6f))
                        Display("Always on.", 46.sp, Color.White)
                        Display("In the open.", 46.sp, Color(0xFF9DB1FF), italic = true)
                        Spacer(Modifier.height(22.dp))
                        listOf(
                            "01" to "Allow the microphone once. It keeps listening on its own, so there is nothing to remember to switch on.",
                            "02" to "A notification stays visible the whole time, with Pause one tap away.",
                            "03" to "It keeps words, never audio. Delete a conversation, a person, or everything.",
                        ).forEach { (number, line) ->
                            Row(Modifier.padding(vertical = 10.dp)) {
                                Label(number, Color(0xFF9DB1FF), Modifier.padding(top = 3.dp).width(34.dp))
                                Body(line, 16.sp, Color.White)
                            }
                        }
                        Hub.error?.let { Body(it, 14.sp, Color(0xFFFFB4A8), modifier = Modifier.padding(top = 10.dp)) }
                        Spacer(Modifier.weight(1f))
                        Next("Allow microphone") {
                            if (hasMic(context)) step = 3 else permissions.launch(buildList {
                                add(Manifest.permission.RECORD_AUDIO)
                                if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
                            }.toTypedArray())
                        }
                    }
                    3 -> VoiceStep(name) { step = 4 }
                    4 -> ConnectStep { step = 5 }
                    5 -> MemoryStep { step = 6 }
                    else -> {
                        Spacer(Modifier.weight(0.6f))
                        Box(Modifier.size(64.dp).clip(CircleShape).background(Color.White), contentAlignment = Alignment.Center) {
                            Icon(Icons.Filled.Check, null, tint = Night, modifier = Modifier.size(30.dp))
                        }
                        Spacer(Modifier.height(26.dp))
                        Display("You're set,\n$name.", 46.sp, Color.White)
                        Spacer(Modifier.height(16.dp))
                        Body("Wingman knows your voice, has started on what your accounts say about you, and is already listening. Put your earbuds in and carry on with your day.", 16.sp, NightText)
                        Spacer(Modifier.weight(1f))
                        Next("Open Wingman") { done() }
                    }
                }
                Spacer(Modifier.height(22.dp))
            }
        }
    }
}

/** Runs the action each time the app comes back to the front, once it can read the clipboard. */
@Composable
private fun OnReturn(action: suspend () -> Unit) {
    val owner = androidx.compose.ui.platform.LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    val current by androidx.compose.runtime.rememberUpdatedState(action)
    androidx.compose.runtime.DisposableEffect(owner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            // The clipboard can only be read once the window has focus, a moment after resuming.
            if (event == androidx.lifecycle.Lifecycle.Event.ON_RESUME) scope.launch { delay(700); current() }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
}

private fun clipboard(context: Context): String {
    val clip = (context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).primaryClip
    return clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString().orEmpty()
}

/** Connect accounts during onboarding, so Wingman knows its owner from the first minute. */
@Composable
private fun ColumnScope.ConnectStep(next: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (both, reload) = rememberLoaded("/api/integrations", every = 3000) { JSONObject(it) }
    var signing by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf("") }
    var phoneOn by remember { mutableStateOf(Phone.allowed(context, Manifest.permission.READ_CALENDAR) || Phone.allowed(context, Manifest.permission.READ_CONTACTS)) }
    fun handOver(code: String?) {
        if (code.isNullOrEmpty()) { signing = false; problem = "Google did not return a code. Try again."; return }
        scope.launch {
            val body = Server.call(context, "POST", "/api/google/code", JSONObject().put("code", code))
            signing = false
            problem = if (body == null) "Google sign-in could not be finished. Try again." else ""
            reload()
        }
    }
    val consent = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        runCatching { Identity.getAuthorizationClient(context).getAuthorizationResultFromIntent(result.data) }
            .onSuccess { handOver(it.serverAuthCode) }
            .onFailure { signing = false; problem = "Sign-in was cancelled." }
    }
    fun signIn() {
        signing = true; problem = ""
        Identity.getAuthorizationClient(context).authorize(Phone.googleRequest())
            .addOnSuccessListener { result ->
                val pending = result.pendingIntent
                if (result.hasResolution() && pending != null) consent.launch(IntentSenderRequest.Builder(pending.intentSender).build())
                else handOver(result.serverAuthCode)
            }
            .addOnFailureListener { signing = false; problem = "Google sign-in failed: ${it.message}" }
    }
    val asking = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        if (granted.values.any { it }) { phoneOn = true; scope.launch { Phone.sync(context); reload() } }
    }
    val google = both?.optJSONObject("google")
    val slack = both?.optJSONObject("slack")
    val notion = both?.optJSONObject("notion")
    val googleOn = google?.optBoolean("connected") == true
    val slackOn = slack?.optBoolean("connected") == true
    val notionOn = notion?.optBoolean("connected") == true
    Spacer(Modifier.height(34.dp))
    Display("Bring your", 40.sp, Color.White)
    Display("world in.", 40.sp, Color(0xFF9DB1FF), italic = true)
    Spacer(Modifier.height(10.dp))
    Body("The more Wingman can see, the better it knows you from the first minute. Each account is read now for what it says about you, and kept in step after.", 15.sp, NightText)
    Spacer(Modifier.height(12.dp))
    Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
        Source("Google", "Calendar, documents and contacts", if (googleOn) google?.optString("account").orEmpty().ifEmpty { "Connected" } else null,
            if (signing) "Signing in…" else "Connect", !signing) { signIn() }
        Source("Slack", "What you are asked for, and what you said you would do", if (slackOn) slack?.optString("workspace").orEmpty().ifEmpty { "Connected" } else null, "Connect") {
            context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(Server.page(context, "/oauth/slack/start")))) }
        Source("Notion", "Your notes and pages", if (notionOn) notion?.optString("workspace").orEmpty().ifEmpty { "Connected" } else null, "Connect") {
            context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(Server.page(context, "/oauth/notion/start")))) }
        Source("This phone", "Its calendar and contacts", if (phoneOn) "Allowed" else null, "Allow") {
            asking.launch(arrayOf(Manifest.permission.READ_CALENDAR, Manifest.permission.READ_CONTACTS)) }
    }
    if (problem.isNotEmpty()) Body(problem, 14.sp, Color(0xFFFFB4A8), modifier = Modifier.padding(vertical = 8.dp))
    Spacer(Modifier.height(12.dp))
    Next(if (googleOn || slackOn || notionOn || phoneOn) "Continue" else "Skip for now") { next() }
}

@Composable
private fun Source(name: String, detail: String, connected: String?, action: String, enabled: Boolean = true, onClick: () -> Unit) {
    Row(Modifier.padding(vertical = 6.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Color(0x14FFFFFF))
        .border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(22.dp)).padding(horizontal = 18.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Display(name, 24.sp, Color.White)
            Body(detail, 13.sp, NightText, modifier = Modifier.padding(top = 2.dp))
            if (connected != null) Label("Connected · $connected", Color(0xFF8DE0B0), Modifier.padding(top = 6.dp))
        }
        Spacer(Modifier.width(10.dp))
        if (connected == null) Action(action, solid = true, onDark = true, enabled = enabled, onClick = onClick)
        else Icon(Icons.Filled.Check, null, tint = Color(0xFF8DE0B0), modifier = Modifier.size(24.dp))
    }
}

/** Wingman reads what was just connected and shows the picture of its owner forming. */
@Composable
private fun ColumnScope.MemoryStep(next: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (state, _) = rememberLoaded("/api/profile", every = 2500) { JSONObject(it) }
    var imported by remember { mutableStateOf("") }
    var link by remember { mutableStateOf("") }
    var copied by remember { mutableStateOf(false) }
    var asked by remember { mutableStateOf("Claude") }
    var reading by remember { mutableStateOf(false) }
    var waiting by remember { mutableStateOf(false) }  // an assistant was asked; its answer is expected on the clipboard
    var taken by remember { mutableStateOf("") }  // the last text brought in, so it is not read twice
    LaunchedEffect(Unit) { Server.call(context, "GET", "/api/connector")?.let { link = JSONObject(it).optString("url") } }
    fun paste(quiet: Boolean) {
        val text = clipboard(context)
        if (reading || text == taken) { if (!quiet && text == taken && text.isNotEmpty()) imported = "That answer is already in. Copy a new one to add more."; return }
        if (text.trim().length < 80 || text == link || text == Phone.QUESTION || text == Phone.HAND_OVER) {
            if (!quiet) imported = "Nothing to paste yet. Copy the assistant's answer, then tap again."
            return
        }
        taken = text; waiting = false; reading = true
        imported = "Reading what $asked knows about you…"
        scope.launch {
            val body = Server.call(context, "POST", "/api/import", JSONObject().put("source", asked).put("text", text))
            reading = false
            imported = body?.let { JSONObject(it).let { r -> "Added ${r.optInt("facts")} new facts from $asked. Your profile is being updated." } } ?: "Could not read that. Try again."
            if (body == null) taken = ""
        }
    }
    // Coming back from Claude or ChatGPT with the answer copied: it is brought in without a tap.
    OnReturn { if (waiting) paste(true) }
    fun copy() {
        (context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager)
            .setPrimaryClip(android.content.ClipData.newPlainText("Wingman connector", link)); copied = true
    }
    LaunchedEffect(Unit) { Server.call(context, "POST", "/api/profile/build") }
    LaunchedEffect(Hub.shared) {
        val (from, text) = Hub.shared ?: return@LaunchedEffect
        Hub.shared = null
        imported = "Reading what $from knows about you…"
        scope.launch {
            val body = Server.call(context, "POST", "/api/import", JSONObject().put("source", from).put("text", text))
            imported = body?.let { JSONObject(it).let { r -> "Added ${r.optInt("facts")} facts from $from" } } ?: "Could not read what was shared. Try again."
        }
    }
    val building = state?.optBoolean("building") == true
    val profile = state?.optJSONObject("profile")
    val facts = state?.optJSONObject("facts")
    val total = facts?.keys()?.asSequence()?.sumOf { facts.optInt(it) } ?: 0
    Spacer(Modifier.height(34.dp))
    Display("Getting to", 40.sp, Color.White)
    Display("know you.", 40.sp, Color(0xFF9DB1FF), italic = true)
    Spacer(Modifier.height(14.dp))
    Wave(if (building) 0.6f else 0.12f, building, Color.White, Modifier.fillMaxWidth().height(46.dp))
    Label(when {
        building -> "Reading " + state?.optString("reading").orEmpty().ifEmpty { "your accounts" } + "…"
        total > 0 -> "$total things known about you so far"
        else -> "Nothing to read yet. It will learn as you talk."
    }, Color(0xFF9DB1FF), Modifier.padding(top = 10.dp))
    Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
        Column(Modifier.padding(top = 14.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Color(0x14FFFFFF))
            .border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(22.dp)).padding(18.dp)) {
        Label("Claude and ChatGPT already know you", Color.White, Modifier.padding(top = 0.dp))
        Body("Add Wingman to them once and they send what they know straight here, now and as they learn more.", 13.sp, NightText, modifier = Modifier.padding(top = 4.dp, bottom = 4.dp))
        listOf(
            "01" to "Copy Wingman's connector address.",
            "02" to "Tap Add to Claude or Add to ChatGPT. Their website opens in your browser: choose Add custom connector, name it Wingman, paste.",
            "03" to "Tap Send. The facts arrive here by themselves.",
        ).forEach { (number, line) ->
            Row(Modifier.padding(vertical = 5.dp)) {
                Label(number, Color(0xFF9DB1FF), Modifier.padding(top = 2.dp).width(30.dp))
                Body(line, 14.sp, Color.White)
            }
        }
        Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Action(if (copied) "Copied" else "Copy address", solid = true, onDark = true, enabled = link.isNotEmpty()) { copy() }
            Action("Send address to my computer", onDark = true, enabled = link.isNotEmpty()) {
                runCatching { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_SUBJECT, "Wingman connector address").putExtra(Intent.EXTRA_TEXT, link), "Send the address")) } }
            Action("Add to Claude", onDark = true, enabled = link.isNotEmpty()) { copy(); Phone.browse(context, "https://claude.ai/settings/connectors?modal=add-custom-connector") }
            Action("Add to ChatGPT", onDark = true, enabled = link.isNotEmpty()) { copy(); Phone.browse(context, "https://chatgpt.com/#settings/Connectors") }
        }
        Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Action("Send from Claude", solid = true, onDark = true) { if (!Phone.ask(context, Phone.CLAUDE, Phone.HAND_OVER)) imported = "Could not open Claude" }
            Action("Send from ChatGPT", onDark = true) { if (!Phone.ask(context, Phone.CHATGPT, Phone.HAND_OVER)) imported = "Could not open ChatGPT" }
        }
        Body("No connector? Ask it what it remembers about you and copy the answer. When you come back, Wingman picks it up.", 12.sp, NightText, modifier = Modifier.padding(top = 12.dp))
        Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Action("Ask Claude", onDark = true) { asked = "Claude"; waiting = true; if (!Phone.ask(context, Phone.CLAUDE)) imported = "Could not open Claude" }
            Action("Ask ChatGPT", onDark = true) { asked = "ChatGPT"; waiting = true; if (!Phone.ask(context, Phone.CHATGPT)) imported = "Could not open ChatGPT" }
            Action(if (reading) "Reading…" else "Paste its answer", solid = true, onDark = true, enabled = !reading) { paste(false) }
        }
        // Right under the buttons, so a tap always shows what happened.
        if (imported.isNotEmpty()) Body(imported, 14.sp, if (imported.startsWith("Added")) Color(0xFF8DE0B0) else if (imported.startsWith("Reading")) Color.White else Color(0xFFFFD08A),
            FontWeight.Medium, Modifier.padding(top = 10.dp))
        }
        if (facts != null && total > 0) Row(Modifier.padding(top = 12.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            facts.keys().asSequence().toList().forEach { source ->
                Box(Modifier.clip(RoundedCornerShape(50)).background(Color(0x1FFFFFFF)).padding(horizontal = 12.dp, vertical = 6.dp)) { Label("$source · ${facts.optInt(source)}", Color.White) }
            }
        }
        if (profile != null) {
            Display(profile.optString("summary"), 21.sp, Color.White, modifier = Modifier.padding(top = 16.dp))
            val sections = profile.optJSONArray("sections") ?: JSONArray()
            for (index in 0 until minOf(sections.length(), 4)) {
                val section = sections.optJSONObject(index) ?: continue
                Label(section.optString("title"), Color(0xFF9DB1FF), Modifier.padding(top = 14.dp, bottom = 2.dp))
                val points = section.optJSONArray("points") ?: JSONArray()
                for (point in 0 until minOf(points.length(), 2)) Body(points.optString(point), 14.sp, NightText, modifier = Modifier.padding(vertical = 3.dp))
            }
        }
    }
    Spacer(Modifier.height(12.dp))
    Next(if (building) "Continue while it reads" else "Continue") { next() }
}

@Composable
private fun WhisperBanner(modifier: Modifier = Modifier) {
    val flash = Hub.flash
    LaunchedEffect(flash) { if (flash != null) { delay(8000); if (Hub.flash === flash) Hub.flash = null } }
    androidx.compose.animation.AnimatedVisibility(
        visible = flash != null, modifier = modifier,
        enter = androidx.compose.animation.slideInVertically { -it } + fadeIn(),
        exit = androidx.compose.animation.slideOutVertically { -it } + fadeOut(),
    ) {
        val (kind, text) = flash?.let { it.first to it.second } ?: ("" to "")
        Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp).fillMaxWidth().clip(RoundedCornerShape(26.dp)).night()
            .clickable { Hub.flash = null }.padding(horizontal = 20.dp, vertical = 18.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Wave(0.7f, true, Color(0xFF9DB1FF), Modifier.width(34.dp).height(16.dp), bars = 7)
                Spacer(Modifier.width(10.dp))
                Label(when (kind) {
                    "name", "fact" -> "Whispered in your ear"
                    "nudge" -> "Nudge in your ear"
                    "explain" -> "Explained in your ear"
                    "brief" -> "Who this is"
                    "promise" -> "Reminder in your ear"
                    else -> "Wingman"
                }, Color(0xFF9DB1FF))
            }
            Display(text, 24.sp, Color.White, italic = true, modifier = Modifier.padding(top = 10.dp))
        }
    }
}

@Composable
private fun Next(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().height(60.dp).clip(RoundedCornerShape(30.dp)).background(if (enabled) Color.White else Color(0x33FFFFFF))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 24.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Body(text, 17.sp, if (enabled) Night else Color(0x88FFFFFF), FontWeight.SemiBold, Modifier.weight(1f))
        Icon(Icons.AutoMirrored.Filled.ArrowForward, null, tint = if (enabled) Night else Color(0x88FFFFFF), modifier = Modifier.size(22.dp))
    }
}

@Composable
private fun Moment(label: String, said: String, whisper: String, after: String) {
    Column(Modifier.padding(vertical = 6.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Color(0x14FFFFFF))
        .border(1.dp, Color(0x1FFFFFFF), RoundedCornerShape(22.dp)).padding(horizontal = 18.dp, vertical = 14.dp)) {
        Label(label, Color(0xFF9DB1FF))
        Body(said, 14.sp, NightText, modifier = Modifier.padding(top = 6.dp))
        Display(whisper, 24.sp, Color.White, italic = true, modifier = Modifier.padding(top = 6.dp))
        Body(after, 13.sp, NightText)
    }
}

/** The owner reads a passage for ten seconds while the waveform follows their voice. */
@Composable
private fun ColumnScope.VoiceStep(name: String, next: () -> Unit) {
    val context = LocalContext.current
    var started by remember { mutableStateOf(false) }
    var left by remember { mutableStateOf(10) }
    val saved = started && !Hub.enrolling && Hub.enrolMessage.startsWith("Voice sample saved")
    val failed = started && !Hub.enrolling && Hub.enrolMessage.isNotEmpty() && !saved
    LaunchedEffect(started, Hub.enrolling) { if (started && Hub.enrolling) { left = 10; while (left > 0) { delay(1000); left -= 1 } } }
    LaunchedEffect(saved) { if (saved) { delay(700); next() } }

    Spacer(Modifier.height(34.dp))
    Display(if (Hub.enrolling) "Keep reading…" else "Now, your voice.", 40.sp, Color.White)
    Body("Wingman must know which voice is yours, so it only steps in for you. Read this aloud, the way you normally talk.", 15.sp, NightText,
        modifier = Modifier.padding(top = 10.dp))
    Spacer(Modifier.height(20.dp))
    Display("“Hi, I'm $name. This is how I normally sound when I'm talking to people. I'm reading this so Wingman can tell my voice apart from everyone else's in a conversation, even in a noisy room.”",
        24.sp, Color.White, italic = true)
    Spacer(Modifier.weight(1f))
    Wave(Hub.level, Hub.enrolling, if (Hub.enrolling) Color.White else Color(0x66FFFFFF), Modifier.fillMaxWidth().height(72.dp))
    Spacer(Modifier.height(10.dp))
    Label(when {
        saved -> "Got it"
        Hub.enrolling -> "Listening · $left s left"
        failed -> "Try again"
        Hub.status == "Connecting" && started -> "Connecting"
        else -> "10 seconds"
    }, Color(0xFF9DB1FF))
    if (failed) Body(Hub.enrolMessage, 14.sp, Color(0xFFFFB4A8), modifier = Modifier.padding(top = 8.dp))
    Hub.error?.let { Body(it, 14.sp, Color(0xFFFFB4A8), modifier = Modifier.padding(top = 8.dp)) }
    Spacer(Modifier.height(14.dp))
    Next(if (Hub.enrolling) "Recording" else if (failed) "Record again" else "Start, then read aloud", enabled = !Hub.enrolling && !saved) {
        started = true; Hub.enrolMessage = ""; Hub.error = null
        ListenService.run(context, ListenService.ACTION_ENROLL, name.ifBlank { "Me" })
    }
}

// --- Shell -------------------------------------------------------------------------------------

private enum class Screen { Home, Recap, Talk, Promises, People, Live, Settings, Connections, Memory, Person }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(redoOnboarding: () -> Unit) {
    val context = LocalContext.current
    var screen by remember { mutableStateOf(Screen.Home) }
    var ask by remember { mutableStateOf<String?>(null) }
    var person by remember { mutableStateOf("") } // the person whose page is open
    var draft by remember { mutableStateOf<Pair<String, String>?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        // Always on: listening resumes whenever the app opens, unless the owner paused it.
        if (Server.pref(context, "paused") != "yes" && hasMic(context) && !Hub.listening) ListenService.run(context, ListenService.ACTION_START)
    }
    LaunchedEffect(Unit) { Relay.start(context) }
    LaunchedEffect(Unit) { withContext(Dispatchers.IO) { Server.locate(context) }; Server.claim(context); while (true) { Phone.sync(context); Hub.refresh++; delay(10 * 60_000L) } }
    LaunchedEffect(Hub.shared) { if (Hub.shared != null) screen = Screen.Memory }
    BackHandler(enabled = screen != Screen.Home) { screen = when (screen) { Screen.Connections, Screen.Memory -> Screen.Settings; Screen.Person -> Screen.People; else -> Screen.Home } }

    val drafting: (JSONObject) -> Unit = { promise ->
        draft = promise.optString("person") to ""
        scope.launch {
            val body = Server.call(context, "POST", "/api/promises/${promise.optString("_id")}/draft")
            draft = promise.optString("person") to (body?.let { JSONObject(it).optString("message") } ?: "Could not reach the server.")
        }
    }
    val tabbed = screen in listOf(Screen.Home, Screen.Recap, Screen.Promises, Screen.People)

    Box(Modifier.fillMaxSize().background(Paper)) {
        Box(Modifier.fillMaxSize().statusBarsPadding().padding(bottom = if (tabbed) 104.dp else 0.dp)) {
            when (screen) {
                Screen.Home -> HomeScreen({ screen = it }, drafting, { id -> person = id; screen = Screen.Person }) { question -> ask = question; screen = Screen.Talk }
                Screen.Recap -> RecapScreen()
                Screen.Talk -> TalkScreen(ask, { ask = null }) { screen = Screen.Home }
                Screen.Promises -> PromisesScreen(drafting)
                Screen.People -> PeopleScreen { id -> person = id; screen = Screen.Person }
                Screen.Person -> PersonScreen(person, drafting, { name -> ask = "What else should I know about $name before we talk?"; screen = Screen.Talk }) { screen = Screen.People }
                Screen.Live -> LiveScreen { screen = Screen.Home }
                Screen.Settings -> SettingsScreen(redoOnboarding, { screen = it }) { screen = Screen.Home }
                Screen.Connections -> ConnectionsScreen({ screen = it }) { screen = Screen.Settings }
                Screen.Memory -> MemoryScreen { screen = Screen.Settings }
            }
        }
        if (tabbed) Row(
            Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(start = 22.dp, end = 22.dp, bottom = 14.dp).fillMaxWidth()
                .shadow(22.dp, RoundedCornerShape(36.dp), spotColor = Color(0x66070B1C)).clip(RoundedCornerShape(36.dp)).background(Night)
                .height(72.dp).padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Tab(Icons.Outlined.Home, "Home", screen == Screen.Home) { screen = Screen.Home }
            Tab(Icons.Outlined.Notes, "Recaps", screen == Screen.Recap) { screen = Screen.Recap }
            Box(Modifier.size(54.dp).clip(CircleShape).background(Accent).clickable { screen = Screen.Talk }, contentAlignment = Alignment.Center) {
                Wave(0.7f, true, Color.White, Modifier.width(26.dp).height(22.dp), bars = 5)
            }
            Tab(Icons.Outlined.Checklist, "Promises", screen == Screen.Promises) { screen = Screen.Promises }
            Tab(Icons.Outlined.Groups, "People", screen == Screen.People) { screen = Screen.People }
        }
        // Whatever Wingman has just whispered is also shown for a few seconds, on every screen:
        // the earbud is private, so this is the only way anyone else sees it happen.
        WhisperBanner(Modifier.align(Alignment.TopCenter).statusBarsPadding())
    }

    draft?.let { (person, message) ->
        ModalBottomSheet(onDismissRequest = { draft = null }, containerColor = Paper) {
            Column(Modifier.padding(start = 24.dp, end = 24.dp, bottom = 30.dp)) {
                Label("Message for $person")
                Spacer(Modifier.height(10.dp))
                if (message.isEmpty()) Display("Writing it…", 26.sp, Muted, italic = true)
                else {
                    Display(message, 24.sp)
                    Spacer(Modifier.height(20.dp))
                    var sent by remember(message) { mutableStateOf("") }
                    Action("Send on Slack", solid = true, modifier = Modifier.fillMaxWidth()) {
                        sent = "Sending…"
                        scope.launch {
                            val body = Server.call(context, "POST", "/api/slack/send", JSONObject().put("person", person).put("text", message))
                            sent = body?.let { "Sent to ${JSONObject(it).optString("sent")} on Slack" } ?: "Slack could not send it. Is Slack connected, and is $person in your workspace?"
                        }
                    }
                    if (sent.isNotEmpty()) Label(sent, if (sent.startsWith("Sent")) Good else Muted, Modifier.padding(top = 10.dp))
                    Spacer(Modifier.height(10.dp))
                    Action("Send another way", modifier = Modifier.fillMaxWidth()) {
                        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, message), "Send to $person"))
                    }
                }
            }
        }
    }
}

@Composable
private fun Tab(icon: ImageVector, label: String, selected: Boolean, onClick: () -> Unit) {
    Column(Modifier.width(60.dp).height(56.dp).clip(RoundedCornerShape(20.dp)).clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Icon(icon, label, tint = if (selected) Color.White else Color(0xFF7C86AD), modifier = Modifier.size(23.dp))
        Spacer(Modifier.height(5.dp))
        Box(Modifier.size(4.dp).clip(CircleShape).background(if (selected) Accent else Color.Transparent))
    }
}

@Composable
private fun Header(title: String, kicker: String, back: (() -> Unit)? = null, trailing: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, top = 18.dp), verticalAlignment = Alignment.Top) {
        if (back != null) {
            Box(Modifier.padding(top = 4.dp).size(44.dp).clip(CircleShape).border(1.dp, Hair, CircleShape).clickable(onClick = back), contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Ink, modifier = Modifier.size(20.dp))
            }
            Spacer(Modifier.width(14.dp))
        }
        Column(Modifier.weight(1f)) {
            Label(kicker)
            Display(title, if (back != null) 30.sp else 40.sp, modifier = Modifier.padding(top = 4.dp))
        }
        trailing()
    }
}

@Composable
private fun Section(label: String, count: Int? = null, action: String? = null, onAction: () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(top = 30.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Label(label, Ink)
        if (count != null) Label("  $count", Muted)
        Spacer(Modifier.weight(1f))
        if (action != null) Label(action, Accent, Modifier.clip(RoundedCornerShape(10.dp)).clickable(onClick = onAction).padding(vertical = 10.dp, horizontal = 4.dp))
    }
    Rule(Ink)
}

// --- Home --------------------------------------------------------------------------------------

@Composable
private fun PromiseRow(promise: JSONObject, actions: Boolean, drafting: (JSONObject) -> Unit, changed: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val mine = promise.optString("by") == "you"
    val due = promise.optString("due").removePrefix("by ").removePrefix("By ")
    Column(Modifier.padding(vertical = 16.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Display(promise.optString("what").replaceFirstChar { it.uppercase() }, 26.sp, maxLines = 2)
                Body((if (mine) "for " else "from ") + promise.optString("person") + " · said " + day(promise.optLong("createdAt")), 13.sp, Muted, modifier = Modifier.padding(top = 2.dp))
            }
            if (due.isNotEmpty()) Label(due, Due, Modifier.padding(start = 10.dp, top = 8.dp).clip(RoundedCornerShape(8.dp)).background(DueSoft).padding(horizontal = 8.dp, vertical = 5.dp))
        }
        if (actions) Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (mine) Action("Draft the message", solid = true) { drafting(promise) }
            Action(if (mine) "Done" else "Received") {
                scope.launch { Server.call(context, "POST", "/api/promises/${promise.optString("_id")}", JSONObject().put("status", "done")); changed() }
            }
        }
    }
}

@Composable
private fun TodoRow(title: String, label: String, labelColor: Color, onDraft: (() -> Unit)? = null, onDone: () -> Unit) {
    Row(Modifier.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onDone), contentAlignment = Alignment.Center) {
            Box(Modifier.size(24.dp).clip(CircleShape).border(1.5.dp, Ink, CircleShape))
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Display(title.replaceFirstChar { it.uppercase() }, 24.sp, maxLines = 2)
            Label(label, labelColor, Modifier.padding(top = 4.dp))
        }
        if (onDraft != null) { Spacer(Modifier.width(8.dp)); Action("Draft", onClick = onDraft) }
    }
}

@Composable
private fun HomeScreen(go: (Screen) -> Unit, drafting: (JSONObject) -> Unit, openPerson: (String) -> Unit, brief: (String) -> Unit) {
    val context = LocalContext.current
    val (home, reload) = rememberLoaded("/api/home", every = 4000) { JSONObject(it) }
    val name = Server.pref(context, "name") ?: home?.optString("ownerName").orEmpty()
    val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    val greeting = when { hour < 5 -> "Up late"; hour < 12 -> "Good morning"; hour < 18 -> "Good afternoon"; else -> "Good evening" }
    val now = home?.optJSONObject("now")
    val owe = home?.optJSONArray("owe")?.objects().orEmpty()
    val owed = home?.optJSONArray("owed")?.objects().orEmpty()
    val caught = home?.optJSONArray("caught")?.objects().orEmpty()
    val tasks = home?.optJSONArray("tasks")?.objects().orEmpty()
    val studies = home?.optJSONArray("research")?.objects().orEmpty()
    val met = home?.optJSONArray("met")?.objects().orEmpty()
    var exempt by remember { mutableStateOf(Wake.exempt(context)) }
    OnReturn { exempt = Wake.exempt(context) }
    val finished = home?.optJSONArray("finished")?.objects().orEmpty()
    var showDone by remember { mutableStateOf(false) }
    val suggested = home?.optJSONArray("suggested")?.objects().orEmpty()
    val scope = rememberCoroutineScope()
    val people = now?.optJSONArray("people")?.objects()?.map { it.optString("name") }.orEmpty()
    val between = now?.optJSONArray("between")?.objects().orEmpty()

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item {
            Header(if (name.isNotBlank()) "$greeting,\n$name." else "$greeting.", SimpleDateFormat("EEEE d MMMM", Locale.getDefault()).format(Date())) {
                Box(Modifier.size(44.dp).clip(CircleShape).border(1.dp, Hair, CircleShape).clickable { go(Screen.Settings) }, contentAlignment = Alignment.Center) {
                    Icon(Icons.Outlined.Settings, "Settings", tint = Ink, modifier = Modifier.size(20.dp))
                }
            }
        }
        if (Hub.error != null) item { Body(Hub.error!!, 13.sp, Bad, modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 14.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(BadSoft).padding(12.dp)) }
        if (home != null && !home.optBoolean("ownerEnrolled")) item {
            Body("Wingman does not know your voice yet, so it cannot tell you from anyone else. Tap to record it.", 13.sp, Due,
                modifier = Modifier.padding(start = 24.dp, end = 24.dp, top = 14.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(DueSoft).clickable { go(Screen.Settings) }.padding(12.dp))
        }
        item {
            // Right now: what it hears, who you are with, and what stands between you.
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp).fillMaxWidth().clip(RoundedCornerShape(30.dp)).night().clickable { go(Screen.Live) }.padding(22.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(7.dp).clip(CircleShape).background(if (Hub.listening) Color(0xFF5CF2A5) else Color(0xFFFFC14D)))
                    Label(when {
                        !Hub.listening -> "  ${Hub.status}"
                        Hub.whispering -> "  Whispering"
                        people.isNotEmpty() -> "  With ${people.joinToString(", ")}"
                        Hub.hearing -> "  Hearing speech"
                        else -> "  Listening"
                    }, Color.White, Modifier.weight(1f))
                    Box(Modifier.size(42.dp).clip(CircleShape).background(Color(0x26FFFFFF)).clickable {
                        ListenService.run(context, if (Hub.listening) ListenService.ACTION_STOP else ListenService.ACTION_START)
                    }, contentAlignment = Alignment.Center) {
                        Icon(if (Hub.listening) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (Hub.listening) "Pause listening" else "Resume listening", tint = Color.White, modifier = Modifier.size(20.dp))
                    }
                }
                Wave(Hub.level, Hub.listening, Color.White, Modifier.padding(top = 18.dp, bottom = 16.dp).fillMaxWidth().height(54.dp))
                Display(
                    when {
                        !Hub.listening && Hub.status.startsWith("Listening on") -> "Your other device is listening. Tap play to listen here instead."
                        !Hub.listening -> "Paused. Tap play and it picks up where it left off."
                        between.isNotEmpty() -> between.take(2).joinToString(" ") { owes(it) + "." }
                        (now?.optInt("lines") ?: 0) > 0 -> "Following along. It speaks only if you get stuck."
                        Hub.hearing -> "Someone is speaking. Following along."
                        else -> "Quiet for now."
                    }, 27.sp, Color.White)
                val last = now?.optString("lastLine").orEmpty()
                if (Hub.listening && last.isNotEmpty()) Body("“$last”", 14.sp, NightText, modifier = Modifier.padding(top = 10.dp), maxLines = 2)
            }
        }
        if (!exempt) item {
            Row(Modifier.padding(horizontal = 24.dp, vertical = 10.dp).fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(DueSoft).padding(16.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Body("Android may stop Wingman in the background. Allow it to keep listening.", 14.sp, Ink, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(10.dp))
                Action("Allow", solid = true) { Wake.askExemption(context) }
            }
        }
        val upcoming = home?.optJSONArray("next")?.objects().orEmpty()
        if (upcoming.isNotEmpty()) item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Coming up")
            upcoming.take(2).forEachIndexed { index, event ->
                if (index > 0) Rule()
                Column(Modifier.padding(vertical = 14.dp)) {
                    Label(event.optString("start").substringAfter("T").take(5), Accent)
                    Display(event.optString("title"), 24.sp, modifier = Modifier.padding(top = 3.dp), maxLines = 2)
                    val with = event.optJSONArray("people")?.let { a -> (0 until a.length()).map { i -> a.optString(i) } }.orEmpty()
                    if (with.isNotEmpty()) Body("with " + with.joinToString(", "), 13.sp, Muted)
                }
            }
        } }
        if (suggested.isNotEmpty()) item {
            // What Wingman thinks you should do after a conversation, waiting for a yes or no.
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 20.dp).fillMaxWidth().clip(RoundedCornerShape(28.dp)).background(AccentSoft).padding(22.dp)) {
                Label(if (suggested.size == 1) "Wingman suggests a to-do" else "Wingman suggests ${suggested.size} to-dos", Accent)
                suggested.forEach { item ->
                    Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Display(item.optString("text").replaceFirstChar { it.uppercase() }, 23.sp, modifier = Modifier.weight(1f), maxLines = 3)
                        Label("Skip", Muted, Modifier.clip(RoundedCornerShape(10.dp)).clickable {
                            scope.launch { Server.call(context, "POST", "/api/tasks/${item.optString("_id")}", JSONObject().put("status", "skip")); reload() } }.padding(12.dp))
                    }
                }
                Row(Modifier.padding(top = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action(if (suggested.size == 1) "Add it" else "Add all", solid = true) {
                        scope.launch { Server.call(context, "POST", "/api/suggestions", JSONObject().put("accept", true)); reload() } }
                    Action("No thanks") { scope.launch { Server.call(context, "POST", "/api/suggestions", JSONObject().put("accept", false)); reload() } }
                }
            }
        }
        if (met.isNotEmpty()) item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Recent people", action = "Everyone") { go(Screen.People) }
            met.forEachIndexed { index, who ->
                if (index > 0) Rule()
                Row(Modifier.fillMaxWidth().clickable { openPerson(who.optString("_id")) }.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Display(who.optString("name"), 22.sp)
                        Body(listOfNotNull(who.optString("about").ifEmpty { null }, day(who.optLong("at")) + " " + clock(who.optLong("at")),
                            who.optString("where").ifEmpty { null }).joinToString(" · "), 13.sp, Muted, maxLines = 2)
                    }
                    Icon(Icons.AutoMirrored.Filled.ArrowForward, null, tint = Ink, modifier = Modifier.size(18.dp))
                }
            }
        } }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("To do", (tasks.size + owe.size).takeIf { it > 0 }, if (owe.size > 3) "All promises" else null) { go(Screen.Promises) }
            if (tasks.isEmpty() && owe.isEmpty()) Body("Nothing to do. Say “remind me to…” or “add it to my list”, or promise someone something, and it lands here.", 15.sp, Muted, modifier = Modifier.padding(vertical = 16.dp))
            var first = true
            tasks.take(6).forEach { task ->
                if (!first) Rule(); first = false
                val due = task.optLong("due")
                TodoRow(task.optString("text"),
                    when {
                        due > 0 -> (if (task.optBoolean("fired")) "Reminded " else "Reminder · ") + (if (day(due) == day(System.currentTimeMillis())) "today " else day(due) + " ") + clock(due)
                        task.optString("kind") == "reminder" -> "Reminder · no time yet"
                        task.optBoolean("auto") -> "Added by Wingman from your conversation"
                        else -> "Note"
                    } + if (due > 0 && task.optBoolean("auto")) " · added by Wingman" else "",
                    if (due > 0 && !task.optBoolean("fired")) Accent else if (task.optBoolean("auto")) Good else Muted) {
                    scope.launch { Server.call(context, "POST", "/api/tasks/${task.optString("_id")}", JSONObject().put("status", "done")); reload() }
                }
            }
            owe.take(4).forEach { promise ->
                if (!first) Rule(); first = false
                val due = promise.optString("due").removePrefix("by ").removePrefix("By ")
                TodoRow(promise.optString("what"), "Promised to ${promise.optString("person")}" + if (due.isNotEmpty()) " · $due" else "", Due, onDraft = { drafting(promise) }) {
                    scope.launch { Server.call(context, "POST", "/api/promises/${promise.optString("_id")}", JSONObject().put("status", "done")); reload() }
                }
            }
        } }
        if (finished.isNotEmpty()) item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Done", finished.size, if (showDone) "Hide" else "Show") { showDone = !showDone }
            if (showDone) finished.forEachIndexed { index, task ->
                if (index > 0) Rule()
                Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Body(task.optString("text"), 15.sp, Muted, maxLines = 2)
                        val at = task.optLong("doneAt")
                        Label(listOfNotNull(
                            if (at > 0) "Done " + day(at) + " " + clock(at) else "Done",
                            if (task.optString("doneHow") == "said") "you told Wingman" else "ticked here",
                            if (task.optBoolean("auto")) "added by Wingman" else null).joinToString(" · "), Good, Modifier.padding(top = 3.dp))
                    }
                    Label("Undo", Accent, Modifier.clip(RoundedCornerShape(10.dp)).clickable {
                        scope.launch { Server.call(context, "POST", "/api/tasks/${task.optString("_id")}", JSONObject().put("status", "open")); reload() } }.padding(10.dp))
                }
            }
        } }
        if (studies.isNotEmpty()) item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Research", studies.size)
            studies.take(4).forEachIndexed { index, study ->
                if (index > 0) Rule()
                val ready = study.optString("status") == "ready"
                Column(Modifier.fillMaxWidth().clickable(enabled = ready) { brief("Tell me about your research on ${study.optString("topic")}, in short.") }.padding(vertical = 14.dp)) {
                    Label(when (study.optString("status")) { "ready" -> "Ready · tap to hear it"; "failed" -> "Could not finish"; else -> "Working on it" },
                        if (ready) Good else if (study.optString("status") == "failed") Bad else Accent)
                    Display(study.optString("topic").replaceFirstChar { it.uppercase() }, 24.sp, modifier = Modifier.padding(top = 4.dp), maxLines = 2)
                    if (ready) Body(study.optString("short"), 14.sp, Muted, modifier = Modifier.padding(top = 4.dp), maxLines = 3)
                }
            }
        } }
        if (owed.isNotEmpty()) item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Owed to you", owed.size)
            owed.take(3).forEachIndexed { index, promise -> if (index > 0) Rule(); PromiseRow(promise, false, drafting, reload) }
        } }
    }
}

// --- Live --------------------------------------------------------------------------------------

@Composable
private fun LiveScreen(back: () -> Unit) {
    val listState = rememberLazyListState()
    LaunchedEffect(Hub.entries.size, Hub.interim) {
        val count = Hub.entries.size + if (Hub.interim.isNotEmpty()) 1 else 0
        if (count > 0) listState.animateScrollToItem(count - 1)
    }
    Column(Modifier.fillMaxSize()) {
        Header("What it hears", if (Hub.listening) (if (Hub.hearing) "Hearing speech" else "Listening") else Hub.status, back)
        Wave(Hub.level, Hub.listening, Accent, Modifier.padding(horizontal = 24.dp, vertical = 14.dp).fillMaxWidth().height(40.dp))
        Rule()
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, contentPadding = PaddingValues(horizontal = 24.dp, vertical = 12.dp)) {
            if (Hub.entries.isEmpty() && Hub.interim.isEmpty()) item { Body("Listening. What Wingman whispers, the promises it hears and its reminders appear here.", 15.sp, Muted) }
            items(Hub.entries) { entry -> EntryRow(entry) }
            if (Hub.interim.isNotEmpty()) item { Body(Hub.interim, 16.sp, Muted, modifier = Modifier.padding(vertical = 6.dp)) }
        }
    }
}

@Composable
private fun EntryRow(entry: Entry) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    when (entry) {
        is Entry.Line -> Column(Modifier.padding(vertical = 8.dp)) {
            Label(entry.label, when (entry.who) { "you" -> Accent; "other" -> Good; else -> Muted })
            Body(entry.text, 17.sp, Ink, modifier = Modifier.padding(top = 3.dp))
        }
        is Entry.Whisper -> {
            val spoken = entry.outcome == "spoken" || entry.outcome == "cut"
            if (spoken || entry.outcome == "card") {
                var grade by remember(entry.id) { mutableStateOf<String?>(null) }
                Column(Modifier.padding(vertical = 10.dp).fillMaxWidth().clip(RoundedCornerShape(24.dp))
                    .then(if (spoken) Modifier.night() else Modifier.background(AccentSoft)).padding(20.dp)) {
                    val ink = if (spoken) Color.White else Ink
                    Label((if (spoken) "Whispered" else "Shown, not spoken") + " · " + entry.kind + (entry.latency?.let { " · %.1f s".format(it) } ?: ""), if (spoken) NightText else Muted)
                    Display(entry.text, 34.sp, ink, italic = true, modifier = Modifier.padding(top = 6.dp))
                    if (entry.id != null) Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("up" to "Useful", "down" to "Not wanted").forEach { (value, label) ->
                            Action(label, solid = grade == value, onDark = spoken) {
                                grade = if (grade == value) null else value
                                scope.launch { Server.call(context, "POST", "/api/whispers/${entry.id}/grade", JSONObject().put("grade", grade ?: JSONObject.NULL)) }
                            }
                        }
                    }
                }
            } else Label(when (entry.outcome) { "declined" -> "Stayed silent · nothing reliable to say"; "stale" -> "Stayed silent · the moment passed"; else -> "Held back" },
                Muted, Modifier.padding(vertical = 6.dp))
        }
        is Entry.Promise -> Column(Modifier.padding(vertical = 10.dp).fillMaxWidth().clip(RoundedCornerShape(24.dp)).background(DueSoft).padding(20.dp)) {
            Label("Promise noted · no sound", Due)
            Display((if (entry.by == "you") "You owe ${entry.person} ${entry.what}" else "${entry.person} owes you ${entry.what}") + if (entry.due.isNotEmpty()) ", ${entry.due}." else ".",
                24.sp, modifier = Modifier.padding(top = 6.dp))
        }
        is Entry.Note -> Column(Modifier.padding(vertical = 10.dp)) {
            Rule(Ink); Label("Recap", Ink, Modifier.padding(top = 10.dp))
            Display(entry.title, 26.sp, modifier = Modifier.padding(top = 4.dp))
            if (entry.body.isNotEmpty()) Body(entry.body, 15.sp, Muted, modifier = Modifier.padding(top = 4.dp, bottom = 10.dp))
            Rule()
        }
    }
}

// --- Talk --------------------------------------------------------------------------------------

@Composable
private fun TalkScreen(ask: String?, asked: () -> Unit, back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    fun send(question: String) {
        if (question.isBlank() || Hub.thinking) return
        Hub.chat += ChatMessage("you", question.trim()); Hub.thinking = true; text = ""
        scope.launch {
            val body = Server.call(context, "POST", "/api/chat", JSONObject().put("text", question.trim()))
            Hub.thinking = false
            Hub.chat += if (body != null) ChatMessage.from(JSONObject(body)) else ChatMessage("wingman", "I could not reach the server.")
        }
    }
    LaunchedEffect(Unit) {
        if (Hub.chat.isEmpty()) Server.call(context, "GET", "/api/chats")?.let { body ->
            runCatching { JSONArray(body).objects().forEach { Hub.chat += ChatMessage(it.optString("role"), it.optString("text"),
                sources = it.optJSONArray("sources")?.let { a -> (0 until a.length()).map { i -> a.optString(i) } } ?: emptyList()) } }
        }
        if (ask != null) { send(ask); asked() }
    }
    LaunchedEffect(Hub.chat.size, Hub.thinking) { if (Hub.chat.isNotEmpty()) listState.animateScrollToItem(Hub.chat.size - 1 + if (Hub.thinking) 1 else 0) }

    Column(Modifier.fillMaxSize().imePadding()) {
        Header("Talk it through", "Wingman · knows your conversations", back)
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = listState, contentPadding = PaddingValues(horizontal = 24.dp, vertical = 16.dp)) {
            if (Hub.chat.isEmpty()) item {
                Display("Ask what you promised. Plan tomorrow's meeting. Get briefed on someone before you walk in.", 28.sp, Muted, italic = true, modifier = Modifier.padding(top = 20.dp))
            }
            items(Hub.chat) { message ->
                if (message.role == "you") Column(Modifier.padding(top = 18.dp)) {
                    Label("You", Accent); Body(message.text, 16.sp, Muted, modifier = Modifier.padding(top = 3.dp))
                } else Column(Modifier.padding(top = 10.dp)) {
                    Display(message.text, 26.sp)
                    message.steps.forEachIndexed { index, step ->
                        Row(Modifier.padding(top = 12.dp)) {
                            Label("0${index + 1}", Accent, Modifier.width(34.dp).padding(top = 4.dp)); Body(step, 16.sp, Ink)
                        }
                    }
                    if (message.sources.isNotEmpty()) Label("From " + message.sources.joinToString(" · "), Muted, Modifier.padding(top = 12.dp))
                    Spacer(Modifier.height(14.dp)); Rule()
                }
            }
            if (Hub.thinking) item { Display("Thinking…", 22.sp, Muted, italic = true, modifier = Modifier.padding(top = 12.dp)) }
        }
        if (Hub.chat.size < 2) Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("What do I owe people this week?", "What did I talk about today?", "Who did I meet today?").forEach { Action(it) { send(it) } }
        }
        Row(Modifier.navigationBarsPadding().padding(start = 20.dp, end = 20.dp, bottom = 16.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f).height(56.dp).clip(RoundedCornerShape(28.dp)).background(Color.White).border(1.dp, Hair, RoundedCornerShape(28.dp)).padding(horizontal = 20.dp),
                contentAlignment = Alignment.CenterStart) {
                if (Hub.talking) Wave(Hub.level, true, Accent, Modifier.fillMaxWidth().height(30.dp))
                else {
                    if (text.isEmpty()) Body("Ask or plan anything", 16.sp, Muted)
                    BasicTextField(text, { text = it }, singleLine = true, cursorBrush = SolidColor(Accent), textStyle = TextStyle(color = Ink, fontSize = 16.sp, fontFamily = Sans),
                        modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send), keyboardActions = KeyboardActions(onSend = { send(text) }))
                }
            }
            Spacer(Modifier.width(10.dp))
            if (text.isNotBlank()) Box(Modifier.size(56.dp).clip(CircleShape).background(Ink).clickable { send(text) }, contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.ArrowForward, "Send", tint = Color.White, modifier = Modifier.size(22.dp))
            } else Box(Modifier.size(if (Hub.talking) 68.dp else 56.dp).clip(CircleShape).background(Accent).pointerInput(Unit) {
                detectTapGestures(onPress = {
                    if (!hasMic(context)) { Hub.error = "Wingman needs the microphone permission."; return@detectTapGestures }
                    ListenService.run(context, ListenService.ACTION_TALK_START)
                    tryAwaitRelease()
                    ListenService.run(context, ListenService.ACTION_TALK_STOP)
                })
            }, contentAlignment = Alignment.Center) { Icon(Icons.Filled.Mic, "Hold to talk", tint = Color.White, modifier = Modifier.size(24.dp)) }
        }
    }
}

// --- Recap, Promises, People -------------------------------------------------------------------

@Composable
private fun RecapScreen() {
    val (list, _) = rememberLoaded("/api/conversations") { JSONArray(it).objects() }
    var picked by remember { mutableStateOf<String?>(null) }
    val open = picked
    if (open != null) { RecapDetail(open) { picked = null }; return }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 28.dp)) {
        item { Header("Recaps", "Every conversation, written up") }
        if (list == null) return@LazyColumn
        if (list.isEmpty()) { item { Body("Nothing yet. When a conversation ends, Wingman writes down what it was about, what was promised and what you need to do.", 15.sp, Muted, modifier = Modifier.padding(24.dp)) }; return@LazyColumn }
        var shownDay = ""
        list.forEach { c ->
            val on = day(c.optLong("startedAt"))
            if (on != shownDay) { shownDay = on; item { Column(Modifier.padding(horizontal = 24.dp)) { Section(on.replaceFirstChar { it.uppercase() }) } } }
            item {
                Column(Modifier.fillMaxWidth().clickable { picked = c.optString("_id") }.padding(horizontal = 24.dp, vertical = 16.dp)) {
                    val people = c.optJSONArray("people")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty()
                    Label(listOfNotNull(clock(c.optLong("startedAt")), "${c.optInt("minutes")} min",
                        people.takeIf { it.isNotEmpty() }?.let { "with " + it.take(3).joinToString(", ") }).joinToString(" · "))
                    Display(c.optString("title"), 26.sp, modifier = Modifier.padding(top = 5.dp), maxLines = 2)
                    if (c.optString("summary").isNotEmpty()) Body(c.optString("summary"), 15.sp, Muted, modifier = Modifier.padding(top = 6.dp), maxLines = 3)
                    val came = listOfNotNull(
                        c.optInt("todos").takeIf { it > 0 }?.let { "$it to do" },
                        c.optInt("promises").takeIf { it > 0 }?.let { if (it == 1) "1 promise" else "$it promises" },
                        c.optInt("whispers").takeIf { it > 0 }?.let { if (it == 1) "1 whisper" else "$it whispers" })
                    if (came.isNotEmpty()) Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        came.forEach { Box(Modifier.clip(RoundedCornerShape(50)).background(AccentSoft).padding(horizontal = 12.dp, vertical = 6.dp)) { Label(it, Accent) } }
                    }
                }
                Column(Modifier.padding(horizontal = 24.dp)) { Rule() }
            }
        }
    }
}

@Composable
private fun RecapDetail(id: String, back: () -> Unit) {
    BackHandler { back() }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (data, reload) = rememberLoaded("/api/recap/$id") { if (it == "null") JSONObject() else JSONObject(it) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 28.dp)) {
        if (data == null || !data.has("conversation")) { item { Header("Recap", "", back) }; return@LazyColumn }
        val conversation = data.getJSONObject("conversation")
        val people = data.getJSONArray("people").objects().map { it.optString("name") }
        val spoken = data.getJSONArray("whispers").objects().filter { it.optString("outcome") in listOf("spoken", "cut") && it.optString("kind") !in listOf("ask", "checkin") }
        val promises = data.getJSONArray("promises").objects()
        val todos = data.optJSONArray("todos")?.objects().orEmpty()
        val points = conversation.optJSONArray("points")?.let { a -> (0 until a.length()).map { a.optString(it) } }.orEmpty()
        item { Header(conversation.optString("title").ifEmpty { "Conversation" },
            day(conversation.optLong("startedAt")) + " · " + clock(conversation.optLong("startedAt")) + if (people.isNotEmpty()) " · with " + people.joinToString(", ") else "", back) }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            val summary = conversation.optString("summary")
            if (summary.isNotEmpty()) Display(summary, 21.sp, modifier = Modifier.padding(top = 20.dp))
            if (points.isNotEmpty()) {
                Section("Worth keeping")
                points.forEach { point ->
                    Row(Modifier.padding(vertical = 8.dp)) {
                        Box(Modifier.padding(top = 8.dp, end = 12.dp).size(6.dp).clip(CircleShape).background(Accent))
                        Body(point, 16.sp, Ink, modifier = Modifier.weight(1f))
                    }
                }
            }
            if (todos.isNotEmpty()) {
                Section("For you to do", todos.size)
                todos.forEachIndexed { index, task ->
                    if (index > 0) Rule()
                    val done = task.optString("status") == "done"
                    Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Body(task.optString("text"), 16.sp, if (done) Muted else Ink, FontWeight.Medium, Modifier.weight(1f))
                        Label(if (done) "Done" else "Mark done", if (done) Good else Accent, Modifier.clip(RoundedCornerShape(10.dp)).clickable(enabled = !done) {
                            scope.launch { Server.call(context, "POST", "/api/tasks/${task.optString("_id")}", JSONObject().put("status", "done")); reload() } }.padding(8.dp))
                    }
                }
            }
            if (promises.isNotEmpty()) {
                Section("Promises", promises.size)
                promises.forEachIndexed { index, p ->
                    if (index > 0) Rule()
                    Row(Modifier.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Body(owes(p), 16.sp, Ink, FontWeight.Medium, Modifier.weight(1f))
                        val due = p.optString("due"); if (due.isNotEmpty()) Label(due, Due)
                    }
                }
            }
            if (spoken.isNotEmpty()) {
                Section("What Wingman whispered", spoken.size)
                spoken.forEachIndexed { index, w ->
                    if (index > 0) Rule()
                    Column(Modifier.padding(vertical = 14.dp)) {
                        Display("“${w.optString("text").trimEnd('.')}”", 22.sp, Accent, italic = true)
                        Label(w.optString("why"), Muted, Modifier.padding(top = 4.dp))
                    }
                }
            }
        } }
    }
}

@Composable
private fun PromisesScreen(drafting: (JSONObject) -> Unit) {
    val (all, reload) = rememberLoaded("/api/promises") { JSONArray(it).objects() }
    val open = all.orEmpty().filter { it.optString("status") == "open" }
    val owe = open.filter { it.optString("by") == "you" }
    val owed = open.filter { it.optString("by") != "you" }
    val kept = all.orEmpty().filter { it.optString("status") == "done" }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item { Header("Promises", "Said out loud, kept on record") }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("You owe", owe.size)
            if (owe.isEmpty()) Body("Nothing owed right now.", 15.sp, Muted, modifier = Modifier.padding(vertical = 16.dp))
            owe.forEachIndexed { index, p -> if (index > 0) Rule(); PromiseRow(p, true, drafting, reload) }
            Section("Owed to you", owed.size)
            if (owed.isEmpty()) Body("Nobody owes you anything yet.", 15.sp, Muted, modifier = Modifier.padding(vertical = 16.dp))
            owed.forEachIndexed { index, p -> if (index > 0) Rule(); PromiseRow(p, true, drafting, reload) }
            if (kept.isNotEmpty()) {
                Section("Kept", kept.size)
                kept.take(12).forEachIndexed { index, p -> if (index > 0) Rule(); Body(owes(p), 15.sp, Muted, modifier = Modifier.padding(vertical = 12.dp)) }
            }
        } }
    }
}

@Composable
private fun PeopleScreen(open: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (people, reload) = rememberLoaded("/api/people") { body -> JSONArray(body).objects().filter { !it.optBoolean("isOwner") } }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item { Header("People", "Everyone it has heard named") }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Everyone", people?.size)
            if (people.isNullOrEmpty()) Body("Nobody yet. People appear once they are named in a conversation.", 15.sp, Muted, modifier = Modifier.padding(vertical = 16.dp))
        } }
        items(people.orEmpty()) { person ->
            Column(Modifier.clickable { open(person.optString("_id")) }.padding(horizontal = 24.dp)) {
                Row(Modifier.padding(vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Display(person.optString("name"), 28.sp)
                        Body(listOfNotNull(person.optString("about").ifEmpty { null }, "last heard " + day(person.optLong("lastMet"))).joinToString(" · "), 13.sp, Muted, maxLines = 2)
                        if (person.optBoolean("hasVoice")) Label("Voice known", Good, Modifier.padding(top = 5.dp))
                    }
                    Icon(Icons.AutoMirrored.Filled.ArrowForward, null, tint = Ink, modifier = Modifier.size(20.dp))
                }
                Rule()
            }
        }
    }
}

// --- One person --------------------------------------------------------------------------------

@Composable
private fun PersonScreen(id: String, drafting: (JSONObject) -> Unit, ask: (String) -> Unit, back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (profile, reload) = rememberLoaded("/api/people/$id") { JSONObject(it) }
    val who = profile?.optJSONObject("person")
    val name = who?.optString("name").orEmpty()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 36.dp)) {
        item { Header(name.ifEmpty { "…" }, who?.optString("about").orEmpty().ifEmpty { "Person" }, back) }
        if (profile == null) { item { Display("Putting together what Wingman knows…", 24.sp, Muted, italic = true, modifier = Modifier.padding(24.dp)) }; return@LazyColumn }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Before you talk")
            Display(profile.optString("brief"), 26.sp, modifier = Modifier.padding(vertical = 16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Action("Ask Wingman more", solid = true) { ask(name) }
                if (who?.optBoolean("hasVoice") == true) Label("Voice known", Good, Modifier.padding(top = 16.dp, start = 6.dp))
            }
            val owe = profile.optJSONArray("owe")?.objects().orEmpty()
            val owed = profile.optJSONArray("owed")?.objects().orEmpty()
            Section("You owe $name", owe.size)
            if (owe.isEmpty()) Body("Nothing.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            owe.forEachIndexed { index, promise -> if (index > 0) Rule(); PromiseRow(promise, true, drafting, reload) }
            Section("$name owes you", owed.size)
            if (owed.isEmpty()) Body("Nothing.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            owed.forEachIndexed { index, promise -> if (index > 0) Rule(); PromiseRow(promise, true, drafting, reload) }
            val talks = profile.optJSONArray("conversations")?.objects().orEmpty()
            Section("When you spoke", talks.size)
            if (talks.isEmpty()) Body("No conversation with $name on record yet.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            talks.forEachIndexed { index, talk ->
                if (index > 0) Rule()
                Column(Modifier.padding(vertical = 14.dp)) {
                    Label(day(talk.optLong("startedAt")) + " · " + clock(talk.optLong("startedAt")))
                    Display(talk.optString("title"), 24.sp, modifier = Modifier.padding(top = 3.dp), maxLines = 2)
                    if (talk.optString("summary").isNotEmpty()) Body(talk.optString("summary"), 14.sp, Muted, modifier = Modifier.padding(top = 4.dp))
                }
            }
            Label("Forget $name", Bad, Modifier.padding(top = 34.dp).clip(RoundedCornerShape(10.dp)).clickable {
                scope.launch { Server.call(context, "DELETE", "/api/people/$id"); back() } }.padding(vertical = 10.dp))
        } }
    }
}

// --- Settings ----------------------------------------------------------------------------------

@Composable
private fun SettingsScreen(redoOnboarding: () -> Unit, go: (Screen) -> Unit, back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf(Server.address(context)) }
    var demo by remember { mutableStateOf(false) }
    var quiet by remember { mutableStateOf(false) }
    var checkins by remember { mutableStateOf(true) }
    var exempt by remember { mutableStateOf(Wake.exempt(context)) }
    OnReturn { exempt = Wake.exempt(context) }
    var earbudsOnly by remember { mutableStateOf(Server.pref(context, "earbudsOnly") == "1") }
    var reachable by remember { mutableStateOf<Boolean?>(null) }
    var wiped by remember { mutableStateOf("") }
    var advanced by remember { mutableStateOf(false) }
    var source by remember { mutableStateOf("ChatGPT") }
    var pasted by remember { mutableStateOf("") }
    var importing by remember { mutableStateOf(false) }
    var imported by remember { mutableStateOf("") }
    var google by remember { mutableStateOf<JSONObject?>(null) }
    suspend fun load() {
        Server.call(context, "GET", "/api/integrations")?.let { google = JSONObject(it).optJSONObject("google") }
        val body = Server.call(context, "GET", "/api/state")
        reachable = body != null
        body?.let {
            val state = JSONObject(it); val settings = state.getJSONObject("settings")
            demo = settings.optBoolean("demo"); checkins = settings.optBoolean("checkins", true); quiet = settings.optString("eagerness") == "quiet"
            Hub.ownerEnrolled = state.optBoolean("ownerEnrolled")
        }
    }
    LaunchedEffect(Unit) { load() }
    LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(bottom = 36.dp)) {
        item { Header("Settings", "Wingman", back) }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("Your voice")
            Body(if (Hub.ownerEnrolled) "Wingman knows your voice. Run the setup again to re-record it." else "No voice on file. Without it Wingman cannot tell you from anyone else.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            Action("Run setup again", solid = true) { ListenService.run(context, ListenService.ACTION_STOP); redoOnboarding() }

            Section("Connect and remember")
            NavRow("Connections", if (google?.optBoolean("connected") == true) "Google connected" else "Calendar, contacts and mail") { go(Screen.Connections) }
            Rule()
            NavRow("Memory", "What Wingman knows about you, and bringing in more") { go(Screen.Memory) }

            Section("How readily it speaks")
            Toggle("Quiet", "Needs more confidence, and two minutes between whispers instead of one.", quiet) {
                quiet = it; scope.launch { Server.call(context, "POST", "/api/settings", JSONObject().put("eagerness", if (it) "quiet" else "normal")) } }

            if (!exempt) {
                Row(Modifier.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Body("Keep listening all day", 16.sp, Ink, FontWeight.Medium)
                        Body("Android may stop Wingman to save battery. Allow it to keep running in the background.", 13.sp, Muted, modifier = Modifier.padding(top = 2.dp))
                    }
                    Spacer(Modifier.width(10.dp))
                    Action("Allow", solid = true) { Wake.askExemption(context) }
                }
                Rule()
            }
            Toggle("Check-ins", "In a quiet moment Wingman may ask you one question: in your earbuds if they are in, otherwise as a notification.", checkins) {
                checkins = it; scope.launch { Server.call(context, "POST", "/api/settings", JSONObject().put("checkins", it)) } }
            Toggle("Only speak in earbuds", "With no earbuds or headphones connected, a whisper arrives as a notification instead of aloud.", earbudsOnly) {
                earbudsOnly = it; Server.setPref(context, "earbudsOnly", if (it) "1" else "0") }

            Section("Your data")
            Body("Wingman keeps words, never audio. Voiceprints are kept for you and for people once they are named.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Action("Delete everything") { scope.launch {
                    wiped = if (Server.call(context, "POST", "/api/wipe") != null) "Deleted" else "Server not reachable"
                    Hub.entries.clear(); Hub.chat.clear(); Hub.refresh++; load() } }
                Label("   $wiped", Muted)
            }

            Label(if (advanced) "Hide advanced" else "Advanced", Muted, Modifier.padding(top = 34.dp).clip(RoundedCornerShape(10.dp)).clickable { advanced = !advanced }.padding(vertical = 10.dp))
            if (advanced) {
                Toggle("Demo setting", "Eight seconds between whispers and conversations close after twenty quiet seconds.", demo) {
                    demo = it; scope.launch { Server.call(context, "POST", "/api/settings", JSONObject().put("demo", it)) } }

                Section("Server")
                BasicTextField(address, { address = it }, singleLine = true, cursorBrush = SolidColor(Accent), textStyle = TextStyle(color = Ink, fontSize = 22.sp, fontFamily = Mono),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp))
                Rule()
                Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Action("Save and test") { Server.setAddress(context, address); address = Server.address(context); scope.launch { load() } }
                    Label(when (reachable) { true -> "   Connected"; false -> "   Not reachable"; null -> "" }, if (reachable == false) Bad else Good)
                }

            }
        } }
    }
}

@Composable
private fun NavRow(title: String, detail: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Display(title, 26.sp); Body(detail, 13.sp, Muted) }
        Icon(Icons.AutoMirrored.Filled.ArrowForward, null, tint = Ink, modifier = Modifier.size(20.dp))
    }
}

// --- Connections -------------------------------------------------------------------------------

@Composable
private fun ConnectionsScreen(go: (Screen) -> Unit, back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (both, reload) = rememberLoaded("/api/integrations", every = 3000) { JSONObject(it) }
    val state = both?.optJSONObject("google")
    val phone = both?.optJSONObject("phone")
    val asking = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) scope.launch { Phone.sync(context); reload(); Hub.refresh++ }
    }
    var signing by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf("") }
    // The one-time code from Google goes to the server, which keeps the connection.
    fun handOver(code: String?) {
        if (code.isNullOrEmpty()) { signing = false; problem = "Google did not return a code. Try again."; return }
        scope.launch {
            val body = Server.call(context, "POST", "/api/google/code", JSONObject().put("code", code))
            signing = false
            problem = if (body == null) "The server could not finish the sign-in. Check that your address is a test user on the Google project." else ""
            reload(); Hub.refresh++
        }
    }
    val consent = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        runCatching { Identity.getAuthorizationClient(context).getAuthorizationResultFromIntent(result.data) }
            .onSuccess { handOver(it.serverAuthCode) }
            .onFailure { signing = false; problem = "Sign-in was cancelled." }
    }
    fun signIn() {
        signing = true; problem = ""
        Identity.getAuthorizationClient(context).authorize(Phone.googleRequest())
            .addOnSuccessListener { result ->
                val pending = result.pendingIntent
                if (result.hasResolution() && pending != null) consent.launch(IntentSenderRequest.Builder(pending.intentSender).build())
                else handOver(result.serverAuthCode)
            }
            .addOnFailureListener { signing = false; problem = "Google sign-in failed: ${it.message}" }
    }
    val (events, _) = rememberLoaded("/api/calendar", every = 20000) { JSONArray(it).objects() }
    val connected = state?.optBoolean("connected") == true
    val canBook = state?.optBoolean("canBook") == true
    val canDocs = state?.optBoolean("docs") == true
    val configured = state?.optBoolean("configured") == true
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 36.dp)) {
        item { Header("Connections", "What Wingman can draw on", back) }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            Section("On this phone")
            listOf(
                Triple("Calendar", Manifest.permission.READ_CALENDAR, "events" to "A brief before each meeting, and a warning when you double-book."),
                Triple("Contacts", Manifest.permission.READ_CONTACTS, "contacts" to "Full names and where people work, so a name can be supplied even if nobody said it."),
            ).forEachIndexed { index, (name, permission, rest) ->
                if (index > 0) Rule()
                val count = phone?.opt(rest.first) as? Int
                Row(Modifier.padding(vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Display(name, 26.sp)
                        Body(rest.second, 13.sp, Muted)
                        if (Phone.allowed(context, permission)) Label(if (count != null) "On · $count ${rest.first}" else "On · syncing", Good, Modifier.padding(top = 5.dp))
                    }
                    Spacer(Modifier.width(10.dp))
                    if (!Phone.allowed(context, permission)) Action("Allow", solid = true) { asking.launch(permission) }
                }
            }
            Body("Read straight from the phone, which already keeps them in sync with your accounts. No sign-in.", 13.sp, Muted, modifier = Modifier.padding(top = 4.dp))

            Section("Google account")
            Row(Modifier.padding(vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Display(if (connected) state?.optString("account").orEmpty().ifEmpty { "Connected" } else "Not connected", 26.sp, maxLines = 1)
                    Label(if (connected) (if (canBook) "Connected · can add events" else "Connected · read only") else if (configured) "Ready to connect" else "Needs a one-time setup", if (connected) Good else Muted, Modifier.padding(top = 4.dp))
                }
                if (connected) Action("Disconnect") { scope.launch { Server.call(context, "DELETE", "/api/integrations/google"); reload() } }
            }
            if (configured && (!connected || !canBook || !canDocs)) {
                Action(if (signing) "Signing in…" else if (!connected) "Continue with Google" else if (!canBook) "Let it add events to your calendar" else "Let it read your Google Docs", solid = true, enabled = !signing, modifier = Modifier.fillMaxWidth()) { signIn() }
                Body("Wingman reads your calendar and contacts, and adds an event only when you ask it to. It never deletes or sends anything.", 13.sp, Muted, modifier = Modifier.padding(top = 10.dp, bottom = 14.dp))
            }
            if (problem.isNotEmpty()) Body(problem, 13.sp, Bad, modifier = Modifier.padding(bottom = 12.dp))
            Rule()
            listOf(
                "Calendar" to "Sees what is coming up, warns about clashes, and books what you ask for.",
                "Contacts" to "Your full Google address book.",
                "Docs" to (if (canDocs) "Finds and reads your documents when you are reaching for something in them." else "Not allowed yet. Tap the button above to let it read your documents."),
                "Mail" to "Not requested yet. Reading mail needs a security audit from Google first.",
            ).forEach { (name, use) ->
                Row(Modifier.padding(vertical = 14.dp)) {
                    Label(name, if (connected) Accent else Muted, Modifier.width(96.dp).padding(top = 3.dp)); Body(use, 15.sp, Ink)
                }
                Rule()
            }
            if (!connected && !configured) Body("The server has no Google client yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to Wingman's .env file and restart it.", 15.sp, Muted, modifier = Modifier.padding(top = 16.dp))
            if (connected) {
                Section("Coming up", events?.size)
                if (events.isNullOrEmpty()) Body("Nothing on your calendar in the next two days.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
                events.orEmpty().take(8).forEachIndexed { index, event ->
                    if (index > 0) Rule()
                    Column(Modifier.padding(vertical = 14.dp)) {
                        Label(event.optString("start").replace("T", " · ").take(18))
                        Display(event.optString("title"), 24.sp, modifier = Modifier.padding(top = 3.dp), maxLines = 2)
                        val with = event.optJSONArray("people")?.let { a -> (0 until a.length()).map { i -> a.optString(i) } }.orEmpty()
                        if (with.isNotEmpty()) Body("with " + with.joinToString(", "), 13.sp, Muted)
                    }
                }
            }
            Section("Notion")
            val notion = both?.optJSONObject("notion")
            val notionOn = notion?.optBoolean("connected") == true
            val shared = notion?.optInt("pages") ?: 0
            Column(Modifier.padding(vertical = 16.dp)) {
                Display(if (notionOn) notion?.optString("workspace").orEmpty().ifEmpty { "Connected" } else "Not connected", 26.sp, maxLines = 1)
                Label(when {
                    !notionOn -> "Needs setup on the server"
                    shared == 0 -> "Connected · no pages shared yet"
                    else -> "Connected · $shared pages shared"
                }, if (notionOn && shared > 0) Good else if (notionOn) Due else Muted, Modifier.padding(top = 4.dp))
            }
            if (notion?.optBoolean("signIn") == true) Row(Modifier.padding(bottom = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Action(if (notion.optBoolean("own")) "Connect a different Notion" else "Connect Notion", solid = !notion.optBoolean("own")) {
                    // Notion sends the browser back to the Wingman server once you approve.
                    Relay.start(context)
                    context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(Server.page(context, "/oauth/notion/start"))))
                }
                if (notion.optBoolean("own")) Action("Disconnect") { scope.launch { Server.call(context, "DELETE", "/api/integrations/notion"); reload() } }
            }
            Rule()
            Body(if (notionOn && shared == 0) "Wingman can only see pages you share with it. In Notion, open a page, tap the ⋯ menu, choose Connections, and add “Wing Man”. Sharing a top-level page shares everything under it. This screen updates by itself."
                else "Reads the pages you share when you are reaching for a fact or planning, and keeps what you ask it to note on a page called “Wingman notes”. Change what it can see any time from a page's Connections menu in Notion.",
                15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))

            Section("Slack")
            val slack = both?.optJSONObject("slack")
            val slackOn = slack?.optBoolean("connected") == true
            Column(Modifier.padding(vertical = 16.dp)) {
                Display(if (slackOn) slack?.optString("workspace").orEmpty().ifEmpty { "Connected" } else "Not connected", 26.sp, maxLines = 1)
                Label(if (slackOn) "Connected as ${slack?.optString("user")}" else if (slack?.optBoolean("signIn") == true) "Ready to connect" else "Needs setup on the server",
                    if (slackOn) Good else Muted, Modifier.padding(top = 4.dp))
            }
            if (slack?.optBoolean("signIn") == true) Row(Modifier.padding(bottom = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Action(if (slackOn) "Connect a different Slack" else "Connect Slack", solid = !slackOn) {
                    context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(Server.page(context, "/oauth/slack/start"))))
                }
                if (slack.optBoolean("own")) Action("Disconnect") { scope.launch { Server.call(context, "DELETE", "/api/integrations/slack"); reload() } }
            }
            Rule()
            Body("Searches your messages when you are reaching for something, planning or researching. It sends a message only when you tap Send on a draft, never on its own.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))

            Section("Other assistants")
            NavRow("Claude and ChatGPT", "Bring in what they remember about you") { go(Screen.Memory) }
        } }
    }
}

// --- Memory ------------------------------------------------------------------------------------

@Composable
private fun MemoryScreen(back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val (memories, reload) = rememberLoaded("/api/memories") { JSONArray(it).objects() }
    var about by remember { mutableStateOf<JSONObject?>(null) }
    var rebuilding by remember { mutableStateOf(false) }
    var link by remember { mutableStateOf("") }
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { Server.call(context, "GET", "/api/connector")?.let { link = JSONObject(it).optString("url") } }
    LaunchedEffect(Unit) { while (true) { delay(5000); reload() } }  // facts sent over the connector show up as they land
    LaunchedEffect(Unit) { Server.call(context, "GET", "/api/profile")?.let { about = JSONObject(it) } }
    var source by remember { mutableStateOf("Claude") }
    var pasted by remember { mutableStateOf("") }
    var importing by remember { mutableStateOf(false) }
    var imported by remember { mutableStateOf("") }
    var typing by remember { mutableStateOf(false) }
    var waiting by remember { mutableStateOf(false) }
    var taken by remember { mutableStateOf("") }
    var showProfile by remember { mutableStateOf(false) }
    var showConnector by remember { mutableStateOf(false) }
    var showFacts by remember { mutableStateOf(false) }
    LaunchedEffect(Hub.shared) {
        val (from, text) = Hub.shared ?: return@LaunchedEffect
        Hub.shared = null
        source = from.takeIf { it != "Shared" } ?: source
        importing = true; imported = ""
        // Runs in the screen's own scope: clearing Hub.shared above restarts this effect, and
        // the import must not be cancelled along with it.
        scope.launch {
            val body = Server.call(context, "POST", "/api/import", JSONObject().put("source", from).put("text", text))
            importing = false
            imported = body?.let { JSONObject(it).let { r -> "Added ${r.optInt("facts")} facts, ${r.optInt("people")} people from $from" } } ?: "Could not read what was shared. Try again."
            reload()
        }
    }
    fun add(from: String, text: String, quiet: Boolean = false) {
        if (importing || (text == taken && text.isNotEmpty())) { if (!quiet && text == taken) imported = "That answer is already in. Copy a new one to add more."; return }
        if (text.trim().length < 20 || text == link || text == Phone.QUESTION || text == Phone.HAND_OVER) {
            if (!quiet) imported = "Nothing to paste yet. Copy the assistant's answer, then tap again."
            return
        }
        taken = text; waiting = false
        importing = true; imported = "Reading what $from knows about you…"
        scope.launch {
            val body = Server.call(context, "POST", "/api/import", JSONObject().put("source", from).put("text", text))
            importing = false
            imported = body?.let { JSONObject(it).let { r -> "Added ${r.optInt("facts")} new facts and ${r.optInt("people")} people from $from" } } ?: "Could not read that. Try again."
            if (body == null) taken = ""
            if (body != null) {
                pasted = ""; reload()
                delay(9000)  // the profile is rewritten from the new facts; show it once it is
                Server.call(context, "GET", "/api/profile")?.let { about = JSONObject(it) }
            }
        }
    }
    fun copyLink() {
        (context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager)
            .setPrimaryClip(android.content.ClipData.newPlainText("Wingman connector", link)); copied = true
    }
    // Coming back from Claude or ChatGPT with the answer copied: it is brought in without a tap.
    OnReturn { if (waiting && clipboard(context).trim().length >= 80) add(source, clipboard(context), quiet = true) }
    LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(bottom = 36.dp)) {
        item { Header("Memory", "What Wingman knows about you", back) }
        item { Column(Modifier.padding(horizontal = 24.dp)) {
            // --- Who you are -----------------------------------------------------------------
            Section("About you", action = if (rebuilding) "Reading…" else "Refresh") {
                if (!rebuilding) { rebuilding = true; scope.launch {
                    Server.call(context, "POST", "/api/profile/refresh")?.let { about = JSONObject(it) }
                    rebuilding = false; reload() } }
            }
            val profile = about?.optJSONObject("profile")
            if (profile == null) {
                Body("Wingman writes this from your conversations, your accounts and what other assistants know. It appears once there is something to go on.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
            } else {
                Display(profile.optString("summary"), 22.sp, modifier = Modifier.padding(top = 16.dp, bottom = 8.dp))
                val sources = profile.optJSONArray("sources")?.let { a -> (0 until a.length()).joinToString(", ") { a.optString(it) } } ?: ""
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Label("${profile.optInt("facts")} facts · $sources", Muted, Modifier.weight(1f))
                    Label(if (showProfile) "Less" else "More", Accent, Modifier.clip(RoundedCornerShape(10.dp)).clickable { showProfile = !showProfile }.padding(8.dp))
                }
                if (showProfile) {
                    val sections = profile.optJSONArray("sections") ?: JSONArray()
                    for (index in 0 until sections.length()) {
                        val section = sections.optJSONObject(index) ?: continue
                        Label(section.optString("title"), Accent, Modifier.padding(top = 16.dp, bottom = 4.dp))
                        val points = section.optJSONArray("points") ?: JSONArray()
                        for (point in 0 until points.length()) Body(points.optString(point), 15.sp, Ink, modifier = Modifier.padding(vertical = 4.dp))
                    }
                }
            }

            // --- Bring in what another assistant knows: ask, copy, paste ------------------------
            Section("From Claude or ChatGPT")
            Column(Modifier.padding(top = 14.dp).fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(Color.White).border(1.dp, Hair, RoundedCornerShape(22.dp)).padding(18.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Label("01", Accent, Modifier.width(34.dp))
                    Body("Ask it what it remembers about you", 15.sp, Ink, FontWeight.Medium)
                }
                Row(Modifier.padding(start = 34.dp, top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action("Ask Claude", solid = true) { source = "Claude"; waiting = true; if (!Phone.ask(context, Phone.CLAUDE)) imported = "Could not open Claude" }
                    Action("Ask ChatGPT") { source = "ChatGPT"; waiting = true; if (!Phone.ask(context, Phone.CHATGPT)) imported = "Could not open ChatGPT" }
                }
                Row(Modifier.padding(top = 18.dp), verticalAlignment = Alignment.CenterVertically) {
                    Label("02", Accent, Modifier.width(34.dp))
                    Body("Copy its answer", 15.sp, Ink, FontWeight.Medium)
                }
                Row(Modifier.padding(top = 18.dp), verticalAlignment = Alignment.CenterVertically) {
                    Label("03", Accent, Modifier.width(34.dp))
                    Body("Come back. Wingman picks it up by itself", 15.sp, Ink, FontWeight.Medium)
                }
                Row(Modifier.padding(start = 34.dp, top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action(if (importing) "Reading…" else "Paste from $source", solid = true, enabled = !importing) {
                        add(source, clipboard(context))
                    }
                    Action(if (typing) "Close" else "Write it myself") { typing = !typing }
                }
                if (typing) {
                    BasicTextField(pasted, { pasted = it }, cursorBrush = SolidColor(Accent), textStyle = TextStyle(color = Ink, fontSize = 15.sp, fontFamily = Sans),
                        modifier = Modifier.padding(top = 14.dp).fillMaxWidth().height(120.dp).clip(RoundedCornerShape(16.dp)).background(Paper).border(1.dp, Hair, RoundedCornerShape(16.dp)).padding(14.dp),
                        decorationBox = { inner -> Box { if (pasted.isEmpty()) Body("Anything Wingman should know about you", 15.sp, Muted); inner() } })
                    Action("Add to memory", solid = true, enabled = !importing && pasted.trim().length >= 20, modifier = Modifier.padding(top = 10.dp)) { add("Typed", pasted) }
                }
                if (imported.isNotEmpty()) Body(imported, 14.sp, if (imported.startsWith("Added")) Good else if (imported.startsWith("Reading")) Accent else Due, FontWeight.Medium, Modifier.padding(top = 14.dp))
            }
            Body("Sharing the answer to Wingman from the assistant's Share menu works too.", 13.sp, Muted, modifier = Modifier.padding(top = 10.dp))

            // --- The automatic route, for accounts that allow custom connectors ----------------
            Section("Connect directly", action = if (showConnector) "Hide" else "Set up") { showConnector = !showConnector }
            Body("Claude or ChatGPT sends what it knows by itself and keeps adding. Needs an account that can add custom connectors.", 14.sp, Muted, modifier = Modifier.padding(top = 12.dp))
            if (showConnector && link.isNotEmpty()) {
                Body("1. Tap Add. The address is copied and the assistant's website opens in your browser.\n2. Choose Add custom connector, name it Wingman, paste.\n3. Come back and tap Send.", 14.sp, Ink, modifier = Modifier.padding(top = 12.dp))
                Row(Modifier.padding(top = 12.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action("Add to Claude", solid = true) { copyLink(); Phone.browse(context, "https://claude.ai/settings/connectors?modal=add-custom-connector") }
                    Action("Add to ChatGPT") { copyLink(); Phone.browse(context, "https://chatgpt.com/#settings/Connectors") }
                    Action(if (copied) "Copied" else "Copy address") { copyLink() }
                }
                Row(Modifier.padding(top = 8.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action("Send from Claude") { if (!Phone.ask(context, Phone.CLAUDE, Phone.HAND_OVER)) imported = "Could not open Claude" }
                    Action("Send from ChatGPT") { if (!Phone.ask(context, Phone.CHATGPT, Phone.HAND_OVER)) imported = "Could not open ChatGPT" }
                }
            }

            // --- Every fact, on request --------------------------------------------------------
            Section("Everything it knows", memories?.size, if (showFacts) "Hide" else "Show") { showFacts = !showFacts }
            if (memories.isNullOrEmpty()) Body("Nothing yet.", 15.sp, Muted, modifier = Modifier.padding(vertical = 14.dp))
        } }
        if (showFacts) items(memories.orEmpty()) { memory ->
            Column(Modifier.padding(horizontal = 24.dp)) {
                Row(Modifier.padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Body(memory.optString("text"), 15.sp, Ink)
                        Label("From " + memory.optString("source"), Muted, Modifier.padding(top = 4.dp))
                    }
                    Label("Forget", Muted, Modifier.clip(RoundedCornerShape(10.dp)).clickable {
                        scope.launch { Server.call(context, "DELETE", "/api/memories/${memory.optString("_id")}"); reload() } }.padding(12.dp))
                }
                Rule()
            }
        }
    }
}

@Composable
private fun Toggle(title: String, detail: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.padding(vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) { Body(title, 16.sp, Ink, FontWeight.SemiBold); Body(detail, 13.sp, Muted) }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = onChange, colors = SwitchDefaults.colors(checkedTrackColor = Ink))
    }
}

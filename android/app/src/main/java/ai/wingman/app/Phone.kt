package ai.wingman.app

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.provider.CalendarContract
import android.provider.ContactsContract
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * What the phone already knows: its calendar and its contacts.
 *
 * The phone keeps both in sync with the owner's accounts, so Wingman reads them here with one
 * permission each. No sign-in and nothing to configure.
 */
object Phone {
    fun allowed(context: Context, permission: String) =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    /** Events from now to three days out, with who else is invited. */
    private fun events(context: Context): JSONArray {
        val out = JSONArray()
        val now = System.currentTimeMillis()
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().let {
            ContentUris.appendId(it, now - 3_600_000); ContentUris.appendId(it, now + 3 * 86_400_000L); it.build()
        }
        val columns = arrayOf(CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN, CalendarContract.Instances.END, CalendarContract.Instances.EVENT_LOCATION)
        context.contentResolver.query(uri, columns, null, null, "${CalendarContract.Instances.BEGIN} ASC")?.use { rows ->
            while (rows.moveToNext() && out.length() < 80) {
                val people = JSONArray()
                context.contentResolver.query(CalendarContract.Attendees.CONTENT_URI,
                    arrayOf(CalendarContract.Attendees.ATTENDEE_NAME, CalendarContract.Attendees.ATTENDEE_EMAIL),
                    "${CalendarContract.Attendees.EVENT_ID} = ?", arrayOf(rows.getLong(0).toString()), null)?.use { who ->
                    while (who.moveToNext() && people.length() < 8) {
                        val name = who.getString(0).orEmpty().ifBlank { who.getString(1).orEmpty().substringBefore("@") }
                        if (name.isNotBlank()) people.put(name)
                    }
                }
                out.put(JSONObject().put("title", rows.getString(1).orEmpty()).put("start", rows.getLong(2))
                    .put("end", rows.getLong(3)).put("where", rows.getString(4).orEmpty()).put("people", people))
            }
        }
        return out
    }

    /** Everyone in the address book, with where they work when the phone knows. */
    private fun contacts(context: Context): JSONArray {
        val work = HashMap<Long, String>()
        context.contentResolver.query(ContactsContract.Data.CONTENT_URI,
            arrayOf(ContactsContract.Data.CONTACT_ID, ContactsContract.CommonDataKinds.Organization.TITLE,
                ContactsContract.CommonDataKinds.Organization.COMPANY),
            "${ContactsContract.Data.MIMETYPE} = ?", arrayOf(ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE), null)?.use { rows ->
            while (rows.moveToNext()) {
                val about = listOf(rows.getString(1), rows.getString(2)).filter { !it.isNullOrBlank() }.joinToString(", ")
                if (about.isNotBlank()) work[rows.getLong(0)] = about
            }
        }
        val out = JSONArray()
        context.contentResolver.query(ContactsContract.Contacts.CONTENT_URI,
            arrayOf(ContactsContract.Contacts._ID, ContactsContract.Contacts.DISPLAY_NAME_PRIMARY), null, null,
            "${ContactsContract.Contacts.LAST_TIME_CONTACTED} DESC")?.use { rows ->
            while (rows.moveToNext() && out.length() < 1500) {
                val name = rows.getString(1).orEmpty()
                if (name.isBlank() || name.contains("@")) continue
                out.put(JSONObject().put("name", name).put("about", work[rows.getLong(0)].orEmpty()))
            }
        }
        return out
    }

    /** Sends whatever the owner has allowed to the server. Returns what the server now holds. */
    suspend fun sync(context: Context): JSONObject? {
        val body = JSONObject()
        runCatching { if (allowed(context, Manifest.permission.READ_CALENDAR)) body.put("events", events(context)) }
        runCatching { if (allowed(context, Manifest.permission.READ_CONTACTS)) body.put("contacts", contacts(context)) }
        if (body.length() == 0) return null
        return Server.call(context, "POST", "/api/device", body)?.let { runCatching { JSONObject(it) }.getOrNull() }
    }

    const val CLAUDE = "com.anthropic.claude"
    const val CHATGPT = "com.openai.chatgpt"
    const val QUESTION = "List everything you remember about me, as plain sentences: my work, projects, people in my life, preferences, plans and constraints. No headings, no commentary."

    const val HAND_OVER = "Use the Wingman connector to save everything you remember about me: my work, projects, the people in my life, preferences, plans and constraints. Send it all in one go, then tell me how many facts were saved."

    /**
     * Opens the other assistant with the question already typed: its app when installed,
     * otherwise its website in the browser.
     */
    fun ask(context: Context, app: String, question: String = QUESTION): Boolean {
        val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, question).setPackage(app)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (runCatching { context.startActivity(send) }.isSuccess) return true
        val site = if (app == CLAUDE) "https://claude.ai/new?q=" else "https://chatgpt.com/?q="
        val web = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(site + android.net.Uri.encode(question)))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return runCatching { context.startActivity(web) }.isSuccess
    }

    /**
     * Opens a page in the phone's browser, not in the assistant's own app: the Claude and ChatGPT
     * apps cannot add a connector, but their websites can, also on a phone.
     */
    fun browse(context: Context, url: String): Boolean {
        val page = android.net.Uri.parse(url)
        for (browser in listOf("com.android.chrome", "com.sec.android.app.sbrowser", "org.mozilla.firefox", "com.microsoft.emmx", "com.brave.browser")) {
            val intent = Intent(Intent.ACTION_VIEW, page).setPackage(browser).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (runCatching { context.startActivity(intent) }.isSuccess) return true
        }
        return runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, page).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess
    }

    fun sourceOf(packageName: String?) = when (packageName) {
        CLAUDE -> "Claude"; CHATGPT -> "ChatGPT"; else -> "Shared"
    }

    // "Continue with Google": the server-side client the one-time code is issued for. Client
    // IDs are public; the secret lives only on the server.
    const val GOOGLE_WEB_CLIENT = "273398686957-hd73jttgkuiokp9qggtr85qkklt9j7vq.apps.googleusercontent.com"

    fun googleRequest(): com.google.android.gms.auth.api.identity.AuthorizationRequest =
        com.google.android.gms.auth.api.identity.AuthorizationRequest.builder()
            .setRequestedScopes(listOf(
                com.google.android.gms.common.api.Scope("https://www.googleapis.com/auth/calendar.events"),
                com.google.android.gms.common.api.Scope("https://www.googleapis.com/auth/contacts.readonly"),
                com.google.android.gms.common.api.Scope("https://www.googleapis.com/auth/drive.readonly"),
                com.google.android.gms.common.api.Scope("https://www.googleapis.com/auth/userinfo.email"),
            ))
            .requestOfflineAccess(GOOGLE_WEB_CLIENT, true)
            .build()
}

package ai.wingman.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings

/**
 * Keeping always-on honest. Android can stop a listening app: after a restart, an update, or
 * when it decides to save battery. Wingman cannot switch the microphone back on by itself from
 * the background, so it says so plainly, and one tap brings it back.
 */
class Wake : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Server.pref(context, "onboarded") == "yes" && Server.pref(context, "paused") != "yes") stopped(context, "Your phone restarted.")
    }

    companion object {
        private const val CHANNEL = "stopped"
        private const val ID = 77

        /** Tell the owner Wingman is not listening, with a tap to resume. */
        fun stopped(context: Context, why: String) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, "Wingman stopped", NotificationManager.IMPORTANCE_HIGH))
            val open = PendingIntent.getActivity(context, 3, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            manager.notify(ID, Notification.Builder(context, CHANNEL)
                .setContentTitle("Wingman is not listening").setContentText("$why Tap to start it again.")
                .setSmallIcon(android.R.drawable.ic_lock_silent_mode).setAutoCancel(true).setContentIntent(open).build())
        }

        fun listening(context: Context) = context.getSystemService(NotificationManager::class.java).cancel(ID)

        /** Has the owner told Android to leave Wingman running in the background. */
        fun exempt(context: Context): Boolean =
            (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(context.packageName)

        /** Android's own prompt: "Let Wingman always run in the background?" */
        fun askExemption(context: Context) {
            val ask = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (runCatching { context.startActivity(ask) }.isFailure)
                runCatching { context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        }
    }
}

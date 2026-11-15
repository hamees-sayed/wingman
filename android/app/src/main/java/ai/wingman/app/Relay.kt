package ai.wingman.app

import android.content.Context
import okhttp3.Request
import java.net.InetAddress
import java.net.ServerSocket
import kotlin.concurrent.thread

/**
 * Catches a sign-in coming back to the phone and passes it on to the Wingman server.
 *
 * Services such as Notion finish a sign-in by sending the browser to an address registered
 * in advance, here localhost:8787. On a phone that address is the phone itself, so the app
 * listens there, forwards the request to the real server, and shows the browser its answer.
 */
object Relay {
    @Volatile private var running = false

    fun start(context: Context) {
        if (running) return
        running = true
        val app = context.applicationContext
        thread(name = "wingman-relay", isDaemon = true) {
            val socket = try {
                ServerSocket(8787, 4, InetAddress.getByName("127.0.0.1"))
            } catch (error: Exception) {
                running = false // the port is taken, for instance by a USB bridge to the server
                return@thread
            }
            while (true) {
                val client = try { socket.accept() } catch (error: Exception) { break }
                thread(isDaemon = true) {
                    runCatching {
                        client.use { connection ->
                            val request = connection.getInputStream().bufferedReader().readLine() ?: return@use
                            val path = request.split(" ").getOrNull(1) ?: "/"
                            val page = if (path.startsWith("/oauth/")) runCatching {
                                Server.http.newCall(Request.Builder().url("${Server.base(app)}$path").build())
                                    .execute().use { it.body?.string() }
                            }.getOrNull() ?: "<h1>Wingman could not reach its server.</h1>" else "<h1>Wingman</h1>"
                            val bytes = page.toByteArray()
                            connection.getOutputStream().apply {
                                write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n" +
                                    "Content-Length: ${bytes.size}\r\nConnection: close\r\n\r\n").toByteArray())
                                write(bytes); flush()
                            }
                        }
                    }
                }
            }
            running = false
        }
    }
}

import Combine
import Foundation

/// A loosely typed JSON value. The server's answers are read the way the Android app reads them:
/// a missing or wrongly typed field is an empty string, zero, false or an empty list.
struct JSON {
    let raw: Any?

    init(_ raw: Any?) { self.raw = raw }

    static func parse(_ data: Data) -> JSON? {
        guard let value = try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]) else { return nil }
        return JSON(value)
    }

    static func parse(_ text: String) -> JSON? {
        guard let data = text.data(using: .utf8) else { return nil }
        return parse(data)
    }

    subscript(key: String) -> JSON {
        guard let object = raw as? [String: Any] else { return JSON(nil) }
        return JSON(object[key])
    }

    var isNull: Bool { raw == nil || raw is NSNull }
    var isObject: Bool { raw is [String: Any] }

    var string: String {
        if let text = raw as? String { return text }
        if let number = raw as? NSNumber { return number.stringValue }
        return ""
    }

    var double: Double {
        if let number = raw as? NSNumber { return number.doubleValue }
        if let text = raw as? String { return Double(text) ?? 0 }
        return 0
    }

    var int: Int {
        let value = double
        if value.isNaN || value.isInfinite { return 0 }
        return Int(value)
    }

    var bool: Bool {
        if let number = raw as? NSNumber { return number.boolValue }
        if let text = raw as? String { return text == "true" }
        return false
    }

    func bool(or fallback: Bool) -> Bool {
        isNull ? fallback : bool
    }

    func string(or fallback: String) -> String {
        isNull ? fallback : string
    }

    var array: [JSON] {
        guard let list = raw as? [Any] else { return [] }
        return list.map { JSON($0) }
    }

    var strings: [String] {
        array.map { $0.string }
    }
}

/// Plain JSON calls to the Wingman server. Every request carries the app key.
enum Server {
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 120
        configuration.timeoutIntervalForResource = 300
        return URLSession(configuration: configuration)
    }()

    static func request(_ method: String, _ path: String) -> URLRequest? {
        guard let url = URL(string: Config.base + path) else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(Config.key, forHTTPHeaderField: Config.keyHeader)
        return request
    }

    private static func send(_ request: URLRequest) async -> JSON? {
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return nil }
            return JSON.parse(data) ?? JSON(nil)
        } catch {
            return nil
        }
    }

    /// Returns nil when the server could not be reached or refused; otherwise the parsed answer.
    static func call(_ method: String, _ path: String, body: [String: Any]? = nil) async -> JSON? {
        guard var request = request(method, path) else { return nil }
        if method == "POST" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = (try? JSONSerialization.data(withJSONObject: body ?? [:], options: [])) ?? Data("{}".utf8)
        }
        return await send(request)
    }

    /// Hold-to-talk: the clip is mono PCM16 at 16 kHz, and the answer comes back with audio.
    static func voice(_ clip: Data) async -> JSON? {
        guard var request = request("POST", "/api/chat/voice") else { return nil }
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.httpBody = clip
        return await send(request)
    }
}

/// Keeps one GET answer fresh for a screen: loaded when the screen appears, again whenever
/// `Hub.refresh` moves, and optionally every few seconds.
final class Loader: ObservableObject {
    @Published var value: JSON?
    @Published var loaded = false

    func pull(_ path: String) async {
        let answer = await Server.call("GET", path)
        await MainActor.run {
            if let answer = answer { self.value = answer }
            self.loaded = true
        }
    }

    func keepFresh(_ path: String, every seconds: Double) async {
        await pull(path)
        guard seconds > 0 else { return }
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            if Task.isCancelled { return }
            await pull(path)
        }
    }
}

/// Dates the way the Android app writes them.
enum Stamp {
    private static func formatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = format
        return formatter
    }

    private static let clockFormat = formatter("h:mm a")
    private static let dayFormat = formatter("EEE d MMM")
    private static let longFormat = formatter("EEEE d MMMM")

    static func clock(_ ms: Double) -> String {
        clockFormat.string(from: Date(timeIntervalSince1970: ms / 1000)).lowercased()
    }

    static func day(_ ms: Double) -> String {
        dayFormat.string(from: Date(timeIntervalSince1970: ms / 1000))
    }

    static var today: String { longFormat.string(from: Date()) }
    static var nowMs: Double { Date().timeIntervalSince1970 * 1000 }
}

extension String {
    /// The first letter in upper case, the rest untouched.
    var capitalisedFirst: String {
        guard let first = self.first else { return self }
        return String(first).uppercased() + self.dropFirst()
    }

    func removingPrefix(_ prefix: String) -> String {
        hasPrefix(prefix) ? String(dropFirst(prefix.count)) : self
    }
}

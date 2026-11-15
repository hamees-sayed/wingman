import Foundation

/// Where the Wingman server is and the key it expects. Both can be changed in Settings; what is
/// typed there is kept in UserDefaults and wins over the defaults below.
enum Config {
    /// The server's address: a public name (reached over https) or an IP and port (plain http).
    static let defaultHost = "whale-yea-vcr-think.trycloudflare.com"

    /// Sent as `X-Wingman-Key` with every request. Replace this with the server's WINGMAN_KEY
    /// before building, or type the key into Settings on the phone.
    static let placeholderKey = "PUT_WINGMAN_KEY_HERE"
    static let defaultKey = placeholderKey

    static let keyHeader = "X-Wingman-Key"

    private static let hostPref = "wingman.server"
    private static let keyPref = "wingman.appKey"

    static var host: String {
        let saved = UserDefaults.standard.string(forKey: hostPref) ?? ""
        return saved.isEmpty ? defaultHost : saved
    }

    static func setHost(_ value: String) {
        var clean = value.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefix in ["http://", "ws://", "wss://"] where clean.hasPrefix(prefix) {
            clean = String(clean.dropFirst(prefix.count))
        }
        while clean.hasSuffix("/") { clean = String(clean.dropLast()) }
        UserDefaults.standard.set(clean, forKey: hostPref)
    }

    static var key: String {
        let saved = UserDefaults.standard.string(forKey: keyPref) ?? ""
        return saved.isEmpty ? defaultKey : saved
    }

    static func setKey(_ value: String) {
        UserDefaults.standard.set(value.trimmingCharacters(in: .whitespacesAndNewlines), forKey: keyPref)
    }

    static var keyIsPlaceholder: Bool { key == placeholderKey }

    /// The server's web address: https for a public name, plain http for a local address and port.
    static var base: String {
        let address = host
        if address.hasPrefix("http") { return address }
        let hasLetter = address.contains { $0.isLetter }
        if hasLetter && !address.contains(":") { return "https://" + address }
        return "http://" + address
    }

    /// The live socket: the same address with ws in place of http.
    static var socketURL: URL? {
        let web = base
        guard web.hasPrefix("http") else { return nil }
        return URL(string: "ws" + String(web.dropFirst(4)) + "/ws")
    }
}

/// Small string settings kept on the phone, the same ones the Android app keeps.
enum Prefs {
    static func get(_ key: String) -> String? {
        UserDefaults.standard.string(forKey: "wingman." + key)
    }

    static func set(_ key: String, _ value: String) {
        UserDefaults.standard.set(value, forKey: "wingman." + key)
    }
}

import Foundation
import SwiftUI

/// What the Live screen shows, in the order it happened.
struct Entry: Identifiable {
    enum Kind {
        case line(who: String, label: String, text: String)
        case whisper(id: String?, kind: String, text: String, why: String, outcome: String, latency: Double?)
        case promise(by: String, person: String, what: String, due: String)
        case note(title: String, body: String)
    }

    let id = UUID()
    var kind: Kind
}

/// One turn in the chat with the agent.
struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String
    let text: String
    var steps: [String] = []
    var sources: [String] = []

    static func from(_ answer: JSON) -> ChatMessage {
        ChatMessage(role: "wingman", text: answer["reply"].string, steps: answer["steps"].strings, sources: answer["sources"].strings)
    }
}

/// How loud the microphone is, 0 to 1. Kept apart from `Hub` because it changes ten times a
/// second and only the waveforms need to redraw for it.
final class LevelMeter: ObservableObject {
    static let shared = LevelMeter()
    @Published var level: CGFloat = 0
}

/// State shared by the listening engine and the screens. Only ever touched on the main thread.
final class Hub: ObservableObject {
    static let shared = Hub()

    @Published var entries: [Entry] = []
    @Published var interim = ""
    @Published var listening = false
    @Published var whispering = false
    @Published var hearing = false // someone is speaking right now
    @Published var status = "Paused"
    @Published var error: String?
    @Published var ownerEnrolled = true
    @Published var enrolling = false
    @Published var enrolMessage = ""
    @Published var refresh = 0 // bumped when a conversation ends, so lists reload
    @Published var chat: [ChatMessage] = []
    @Published var talking = false // the talk button is held
    @Published var thinking = false // the agent is working on an answer

    private func note(_ title: String, _ body: String) {
        entries.append(Entry(kind: .note(title: title, body: body)))
    }

    /// One event from the live socket. Call on the main thread.
    func handle(_ event: JSON) {
        switch event["type"].string {
        case "started":
            if !event["continued"].bool { entries.removeAll() }
            interim = ""
            error = nil
            listening = true
            status = "Listening"
            ownerEnrolled = event["ownerEnrolled"].bool(or: true)
        case "speech":
            hearing = event["speaking"].bool
        case "interim":
            interim = event["text"].string
        case "line":
            interim = ""
            entries.append(Entry(kind: .line(who: event["who"].string, label: event["label"].string, text: event["text"].string)))
        case "relabel":
            let from = event["from"].string
            let to = event["to"].string
            for index in entries.indices {
                if case .line(_, let label, let text) = entries[index].kind, label == from {
                    entries[index].kind = .line(who: "other", label: to, text: text)
                }
            }
        case "whisper":
            refresh += 1
            let named = event["id"].string
            let id: String? = named.isEmpty ? nil : named
            entries.append(Entry(kind: .whisper(
                id: id, kind: event["kind"].string, text: event["text"].string, why: event["why"].string,
                outcome: event["outcome"].string, latency: event["latency"].isNull ? nil : event["latency"].double)))
        case "promise":
            entries.append(Entry(kind: .promise(
                by: event["by"].string, person: event["person"].string, what: event["what"].string, due: event["due"].string)))
            refresh += 1
        case "person", "task", "suggestions":
            refresh += 1
        case "reminder":
            note("Reminder", event["text"].string)
            refresh += 1
        case "research":
            note(event["ok"].bool(or: true) ? "Research ready" : "Research could not be finished", event["topic"].string)
            refresh += 1
        case "recap":
            // Always-on closed one conversation by itself and is already in the next.
            if !event["conversation"].isNull {
                note(event["title"].string(or: "Recap ready"), event["summary"].string)
            }
            refresh += 1
        case "superseded":
            listening = false
            hearing = false
            whispering = false
            status = "Listening on your other device"
        case "ending":
            status = "Writing recap"
        case "ended":
            listening = false
            whispering = false
            hearing = false
            status = "Paused"
            interim = ""
            if !event["conversation"].isNull {
                note(event["title"].string(or: "Recap ready"), event["summary"].string)
            }
            refresh += 1
        case "enrolling":
            enrolling = true
            enrolMessage = "Recording… keep reading."
        case "enrolled":
            enrolling = false
            if event["ok"].bool {
                ownerEnrolled = true
                enrolMessage = "Voice sample saved."
            } else {
                enrolMessage = event["message"].string
            }
        case "error":
            error = event["message"].string
        case "clear_error":
            error = nil
        default:
            break
        }
    }
}

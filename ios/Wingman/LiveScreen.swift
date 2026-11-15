import SwiftUI

/// What Wingman is hearing and doing in the conversation that is going on now.
struct LiveScreen: View {
    let back: () -> Void

    @ObservedObject private var hub = Hub.shared

    private var kicker: String {
        if hub.listening { return hub.hearing ? "Hearing speech" : "Listening" }
        return hub.status
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Header("What it hears", kicker, back: back)
            LiveWave(active: hub.listening, color: Palette.accent)
                .frame(height: 40)
                .padding(.horizontal, 24)
                .padding(.vertical, 14)
            HairRule()
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        if hub.entries.isEmpty && hub.interim.isEmpty {
                            BodyText("Listening. What Wingman whispers, the promises it hears and its reminders appear here.", 15, Palette.muted)
                        }
                        ForEach(hub.entries) { entry in
                            EntryRow(entry: entry)
                        }
                        if !hub.interim.isEmpty {
                            BodyText(hub.interim, 16, Palette.muted)
                                .padding(.vertical, 6)
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                }
                .onChange(of: hub.entries.count) { _, _ in
                    withAnimation { proxy.scrollTo("end", anchor: .bottom) }
                }
                .onChange(of: hub.interim) { _, _ in
                    proxy.scrollTo("end", anchor: .bottom)
                }
                .onAppear { proxy.scrollTo("end", anchor: .bottom) }
            }
        }
    }
}

private struct EntryRow: View {
    let entry: Entry

    @State private var grade: String?

    var body: some View {
        switch entry.kind {
        case .line(let who, let label, let text):
            VStack(alignment: .leading, spacing: 3) {
                LabelText(label, who == "you" ? Palette.accent : (who == "other" ? Palette.good : Palette.muted))
                BodyText(text, 17)
            }
            .padding(.vertical, 8)
        case .whisper(let id, let kind, let text, _, let outcome, let latency):
            whisper(id: id, kind: kind, text: text, outcome: outcome, latency: latency)
        case .promise(let by, let person, let what, let due):
            VStack(alignment: .leading, spacing: 6) {
                LabelText("Promise noted · no sound", Palette.due)
                DisplayText((by == "you" ? "You owe \(person) \(what)" : "\(person) owes you \(what)") + (due.isEmpty ? "." : ", \(due)."), 24)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 24).fill(Palette.dueSoft))
            .padding(.vertical, 10)
        case .note(let title, let detail):
            VStack(alignment: .leading, spacing: 0) {
                HairRule(color: Palette.ink)
                LabelText("Recap", Palette.ink)
                    .padding(.top, 10)
                DisplayText(title, 26)
                    .padding(.top, 4)
                if !detail.isEmpty {
                    BodyText(detail, 15, Palette.muted)
                        .padding(.top, 4)
                        .padding(.bottom, 10)
                }
                HairRule()
            }
            .padding(.vertical, 10)
        }
    }

    private func silence(_ outcome: String) -> String {
        switch outcome {
        case "declined": return "Stayed silent · nothing reliable to say"
        case "stale": return "Stayed silent · the moment passed"
        default: return "Held back"
        }
    }

    @ViewBuilder
    private func whisper(id: String?, kind: String, text: String, outcome: String, latency: Double?) -> some View {
        let spoken = outcome == "spoken" || outcome == "cut"
        if spoken || outcome == "card" {
            let took = latency.map { String(format: " · %.1f s", $0) } ?? ""
            VStack(alignment: .leading, spacing: 0) {
                LabelText((spoken ? "Whispered" : "Shown, not spoken") + " · " + kind + took, spoken ? Palette.nightText : Palette.muted)
                DisplayText(text, 34, spoken ? Color.white : Palette.ink, italic: true)
                    .padding(.top, 6)
                if let id = id {
                    HStack(spacing: 8) {
                        gradeButton("up", "Useful", id: id, onDark: spoken)
                        gradeButton("down", "Not wanted", id: id, onDark: spoken)
                    }
                    .padding(.top, 12)
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(whisperBackground(spoken))
            .clipShape(RoundedRectangle(cornerRadius: 24))
            .padding(.vertical, 10)
        } else {
            LabelText(silence(outcome), Palette.muted)
                .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private func whisperBackground(_ spoken: Bool) -> some View {
        if spoken {
            NightBackground()
        } else {
            Palette.accentSoft
        }
    }

    private func gradeButton(_ value: String, _ label: String, id: String, onDark: Bool) -> some View {
        ActionButton(label, solid: grade == value, onDark: onDark) {
            let next: String? = grade == value ? nil : value
            grade = next
            var chosen: Any = NSNull()
            if let next = next { chosen = next }
            let body: [String: Any] = ["grade": chosen]
            Task {
                _ = await Server.call("POST", "/api/whispers/\(id)/grade", body: body)
            }
        }
    }
}

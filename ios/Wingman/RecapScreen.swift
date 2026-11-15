import SwiftUI

/// Every finished conversation, newest first, grouped by day.
struct RecapScreen: View {
    @ObservedObject private var hub = Hub.shared
    @StateObject private var loader = Loader()
    @State private var picked: String?

    private struct DayGroup {
        let day: String
        var conversations: [JSON]
    }

    private var groups: [DayGroup] {
        var out: [DayGroup] = []
        for conversation in (loader.value ?? JSON(nil)).array {
            let on = Stamp.day(conversation["startedAt"].double)
            if let last = out.indices.last, out[last].day == on {
                out[last].conversations.append(conversation)
            } else {
                out.append(DayGroup(day: on, conversations: [conversation]))
            }
        }
        return out
    }

    var body: some View {
        if let open = picked {
            RecapDetail(id: open, back: { picked = nil })
        } else {
            list
        }
    }

    private var list: some View {
        let days = groups
        return ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Header("Recaps", "Every conversation, written up")
                if loader.value != nil && days.isEmpty {
                    BodyText("Nothing yet. When a conversation ends, Wingman writes down what it was about, what was promised and what you need to do.", 15, Palette.muted)
                        .padding(24)
                }
                ForEach(days.indices, id: \.self) { index in
                    let group = days[index]
                    SectionHeader(group.day.capitalisedFirst)
                        .padding(.horizontal, 24)
                    ForEach(group.conversations.indices, id: \.self) { row in
                        let conversation = group.conversations[row]
                        RecapRow(conversation: conversation)
                            .contentShape(Rectangle())
                            .onTapGesture { picked = conversation["_id"].string }
                        HairRule()
                            .padding(.horizontal, 24)
                    }
                }
            }
            .padding(.bottom, 28)
        }
        .task(id: hub.refresh) {
            await loader.pull("/api/conversations")
        }
    }
}

private struct RecapRow: View {
    let conversation: JSON

    private var kicker: String {
        var parts = [Stamp.clock(conversation["startedAt"].double), "\(conversation["minutes"].int) min"]
        let people = conversation["people"].strings
        if !people.isEmpty { parts.append("with " + people.prefix(3).joined(separator: ", ")) }
        return parts.joined(separator: " · ")
    }

    private var came: [String] {
        var out: [String] = []
        let todos = conversation["todos"].int
        let promises = conversation["promises"].int
        let whispers = conversation["whispers"].int
        if todos > 0 { out.append("\(todos) to do") }
        if promises > 0 { out.append(promises == 1 ? "1 promise" : "\(promises) promises") }
        if whispers > 0 { out.append(whispers == 1 ? "1 whisper" : "\(whispers) whispers") }
        return out
    }

    var body: some View {
        let summary = conversation["summary"].string
        let chips = came
        return VStack(alignment: .leading, spacing: 0) {
            LabelText(kicker)
            DisplayText(conversation["title"].string, 26, lines: 2)
                .padding(.top, 5)
            if !summary.isEmpty {
                BodyText(summary, 15, Palette.muted, lines: 3)
                    .padding(.top, 6)
            }
            if !chips.isEmpty {
                HStack(spacing: 8) {
                    ForEach(chips, id: \.self) { chip in
                        LabelText(chip, Palette.accent)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Capsule().fill(Palette.accentSoft))
                    }
                }
                .padding(.top, 12)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One conversation written up: the summary, what is worth keeping, to-dos, promises, whispers.
struct RecapDetail: View {
    let id: String
    let back: () -> Void

    @ObservedObject private var hub = Hub.shared
    @StateObject private var loader = Loader()

    private var path: String { "/api/recap/\(id)" }

    private func owes(_ promise: JSON) -> String {
        promise["by"].string == "you"
            ? "You owe \(promise["person"].string) \(promise["what"].string)"
            : "\(promise["person"].string) owes you \(promise["what"].string)"
    }

    private func kicker(_ conversation: JSON, _ people: [String]) -> String {
        let at = conversation["startedAt"].double
        return Stamp.day(at) + " · " + Stamp.clock(at) + (people.isEmpty ? "" : " · with " + people.joined(separator: ", "))
    }

    private func spokenWhispers(_ data: JSON) -> [JSON] {
        data["whispers"].array.filter { whisper in
            let outcome = whisper["outcome"].string
            let kind = whisper["kind"].string
            return (outcome == "spoken" || outcome == "cut") && kind != "ask" && kind != "checkin"
        }
    }

    private func trimmedQuote(_ text: String) -> String {
        var out = text
        while out.hasSuffix(".") { out = String(out.dropLast()) }
        return "“\(out)”"
    }

    var body: some View {
        let data = loader.value ?? JSON(nil)
        let conversation = data["conversation"]
        return ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if !conversation.isObject {
                    Header(loader.loaded ? "Recap" : "…", loader.loaded && loader.value == nil ? "Could not reach the server" : "", back: back)
                } else {
                    let people = data["people"].array.map { $0["name"].string }
                    let title = conversation["title"].string
                    Header(title.isEmpty ? "Conversation" : title, kicker(conversation, people), back: back)
                    VStack(alignment: .leading, spacing: 0) {
                        summary(conversation)
                        todos(data["todos"].array)
                        promises(data["promises"].array)
                        whispers(spokenWhispers(data))
                    }
                    .padding(.horizontal, 24)
                }
            }
            .padding(.bottom, 28)
        }
        .task(id: hub.refresh) {
            await loader.pull(path)
        }
    }

    @ViewBuilder
    private func summary(_ conversation: JSON) -> some View {
        let text = conversation["summary"].string
        let points = conversation["points"].strings
        if !text.isEmpty {
            DisplayText(text, 21)
                .padding(.top, 20)
        }
        if !points.isEmpty {
            SectionHeader("Worth keeping")
            ForEach(points.indices, id: \.self) { index in
                HStack(alignment: .top, spacing: 12) {
                    Circle()
                        .fill(Palette.accent)
                        .frame(width: 6, height: 6)
                        .padding(.top, 8)
                    BodyText(points[index], 16)
                }
                .padding(.vertical, 8)
            }
        }
    }

    @ViewBuilder
    private func todos(_ tasks: [JSON]) -> some View {
        if !tasks.isEmpty {
            SectionHeader("For you to do", count: tasks.count)
            ForEach(tasks.indices, id: \.self) { index in
                let task = tasks[index]
                let done = task["status"].string == "done"
                if index > 0 { HairRule() }
                HStack(alignment: .center, spacing: 0) {
                    BodyText(task["text"].string, 16, done ? Palette.muted : Palette.ink, weight: 500)
                    LabelButton(done ? "Done" : "Mark done", done ? Palette.good : Palette.accent, enabled: !done) {
                        Task {
                            _ = await Server.call("POST", "/api/tasks/\(task["_id"].string)", body: ["status": "done"])
                            await loader.pull(path)
                        }
                    }
                }
                .padding(.vertical, 8)
            }
        }
    }

    @ViewBuilder
    private func promises(_ all: [JSON]) -> some View {
        if !all.isEmpty {
            SectionHeader("Promises", count: all.count)
            ForEach(all.indices, id: \.self) { index in
                let promise = all[index]
                let due = promise["due"].string
                if index > 0 { HairRule() }
                HStack(alignment: .center, spacing: 10) {
                    BodyText(owes(promise), 16, weight: 500)
                    if !due.isEmpty { LabelText(due, Palette.due) }
                }
                .padding(.vertical, 14)
            }
        }
    }

    @ViewBuilder
    private func whispers(_ spoken: [JSON]) -> some View {
        if !spoken.isEmpty {
            SectionHeader("What Wingman whispered", count: spoken.count)
            ForEach(spoken.indices, id: \.self) { index in
                let whisper = spoken[index]
                if index > 0 { HairRule() }
                VStack(alignment: .leading, spacing: 4) {
                    DisplayText(trimmedQuote(whisper["text"].string), 22, Palette.accent, italic: true)
                    LabelText(whisper["why"].string, Palette.muted)
                }
                .padding(.vertical, 14)
            }
        }
    }
}

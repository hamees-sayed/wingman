import SwiftUI

/// Home: what Wingman hears right now, what is coming up, what there is to do, and what it
/// picked up today. Everything comes from one call, `GET /api/home`, repeated every few seconds.
struct HomeScreen: View {
    let go: (Screen) -> Void
    let brief: (String) -> Void

    @ObservedObject private var hub = Hub.shared
    @StateObject private var loader = Loader()
    @State private var showDone = false

    private static let path = "/api/home"

    private var home: JSON { loader.value ?? JSON(nil) }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        if hour < 5 { return "Up late" }
        if hour < 12 { return "Good morning" }
        if hour < 18 { return "Good afternoon" }
        return "Good evening"
    }

    private var name: String {
        Prefs.get("name") ?? home["ownerName"].string
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Header(name.isEmpty ? "\(greeting)." : "\(greeting),\n\(name).", Stamp.today) {
                    Button(action: { go(.settings) }) {
                        Image(systemName: "gearshape")
                            .font(.system(size: 18))
                            .foregroundColor(Palette.ink)
                            .frame(width: 44, height: 44)
                            .overlay(Circle().stroke(Palette.hair, lineWidth: 1))
                            .contentShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Settings")
                }
                if let error = hub.error {
                    Banner(text: error, color: Palette.bad, soft: Palette.badSoft)
                }
                if loader.value != nil && !home["ownerEnrolled"].bool {
                    Banner(text: "Wingman does not know your voice yet, so it cannot tell you from anyone else. Tap to record it.",
                           color: Palette.due, soft: Palette.dueSoft)
                        .onTapGesture { go(.settings) }
                }
                liveCard
                comingUp
                suggestions
                VStack(alignment: .leading, spacing: 0) {
                    todo
                    done
                    research
                    met
                    owed
                }
                .padding(.horizontal, 24)
            }
            .padding(.bottom, 20)
        }
        .task(id: hub.refresh) {
            await loader.keepFresh(HomeScreen.path, every: 4)
        }
    }

    private func reload() {
        Task { await loader.pull(HomeScreen.path) }
    }

    private func post(_ path: String, _ body: [String: Any]) {
        Task {
            _ = await Server.call("POST", path, body: body)
            await loader.pull(HomeScreen.path)
        }
    }

    private func owes(_ promise: JSON) -> String {
        promise["by"].string == "you"
            ? "You owe \(promise["person"].string) \(promise["what"].string)"
            : "\(promise["person"].string) owes you \(promise["what"].string)"
    }

    private func dueText(_ promise: JSON) -> String {
        promise["due"].string.removingPrefix("by ").removingPrefix("By ")
    }

    // MARK: - Right now

    private var liveLabel: String {
        let people = home["now"]["people"].array.map { $0["name"].string }
        if !hub.listening { return hub.status }
        if hub.whispering { return "Whispering" }
        if !people.isEmpty { return "With " + people.joined(separator: ", ") }
        if hub.hearing { return "Hearing speech" }
        return "Listening"
    }

    private var liveLine: String {
        let now = home["now"]
        let between = now["between"].array
        if !hub.listening && hub.status.hasPrefix("Listening on") {
            return "Your other device is listening. Tap play to listen here instead."
        }
        if !hub.listening { return "Paused. Tap play and it picks up where it left off." }
        if !between.isEmpty { return between.prefix(2).map { owes($0) + "." }.joined(separator: " ") }
        if now["lines"].int > 0 { return "Following along. It speaks only if you get stuck." }
        if hub.hearing { return "Someone is speaking. Following along." }
        return "Quiet for now."
    }

    /// Right now: what it hears, who you are with, and what stands between you.
    private var liveCard: some View {
        let last = home["now"]["lastLine"].string
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Circle()
                    .fill(hub.listening ? Color(hex: 0x5CF2A5) : Color(hex: 0xFFC14D))
                    .frame(width: 7, height: 7)
                LabelText(liveLabel, .white)
                Spacer(minLength: 8)
                Button(action: {
                    if hub.listening { ListenEngine.shared.pause() } else { ListenEngine.shared.start() }
                }) {
                    Image(systemName: hub.listening ? "pause.fill" : "play.fill")
                        .font(.system(size: 16))
                        .foregroundColor(.white)
                        .frame(width: 42, height: 42)
                        .background(Circle().fill(Color.white.opacity(0.15)))
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(hub.listening ? "Pause listening" : "Resume listening")
            }
            LiveWave(active: hub.listening, color: .white)
                .frame(height: 54)
                .padding(.top, 18)
                .padding(.bottom, 16)
            DisplayText(liveLine, 27, .white)
            if hub.listening && !last.isEmpty {
                BodyText("“\(last)”", 14, Palette.nightText, lines: 2)
                    .padding(.top, 10)
            }
        }
        .padding(22)
        .background(NightBackground())
        .clipShape(RoundedRectangle(cornerRadius: 30))
        .contentShape(RoundedRectangle(cornerRadius: 30))
        .onTapGesture { go(.live) }
        .padding(.horizontal, 16)
        .padding(.top, 20)
    }

    // MARK: - Coming up

    @ViewBuilder
    private var comingUp: some View {
        let upcoming = Array(home["next"].array.prefix(2))
        if !upcoming.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                SectionHeader("Coming up")
                ForEach(upcoming.indices, id: \.self) { index in
                    let event = upcoming[index]
                    let with = event["people"].strings
                    if index > 0 { HairRule() }
                    VStack(alignment: .leading, spacing: 3) {
                        LabelText(startTime(event["start"].string), Palette.accent)
                        DisplayText(event["title"].string, 24, lines: 2)
                        if !with.isEmpty {
                            BodyText("with " + with.joined(separator: ", "), 13, Palette.muted)
                        }
                    }
                    .padding(.vertical, 14)
                }
            }
            .padding(.horizontal, 24)
        }
    }

    /// The hour and minute out of "2026-01-31T15:30:00+05:30".
    private func startTime(_ start: String) -> String {
        guard let mark = start.firstIndex(of: "T") else { return String(start.prefix(5)) }
        return String(start[start.index(after: mark)...].prefix(5))
    }

    // MARK: - Suggested to-dos

    /// What Wingman thinks you should do after a conversation, waiting for a yes or no.
    @ViewBuilder
    private var suggestions: some View {
        let suggested = home["suggested"].array
        if !suggested.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                LabelText(suggested.count == 1 ? "Wingman suggests a to-do" : "Wingman suggests \(suggested.count) to-dos", Palette.accent)
                ForEach(suggested.indices, id: \.self) { index in
                    let item = suggested[index]
                    HStack(alignment: .center, spacing: 0) {
                        DisplayText(item["text"].string.capitalisedFirst, 23, lines: 3)
                        LabelButton("Skip", Palette.muted) {
                            post("/api/tasks/\(item["_id"].string)", ["status": "skip"])
                        }
                    }
                    .padding(.top, 12)
                }
                HStack(spacing: 8) {
                    ActionButton(suggested.count == 1 ? "Add it" : "Add all", solid: true) {
                        post("/api/suggestions", ["accept": true])
                    }
                    ActionButton("No thanks") {
                        post("/api/suggestions", ["accept": false])
                    }
                }
                .padding(.top, 16)
            }
            .padding(22)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 28).fill(Palette.accentSoft))
            .padding(.horizontal, 16)
            .padding(.top, 20)
        }
    }

    // MARK: - To do

    private func taskLabel(_ task: JSON) -> String {
        let due = task["due"].double
        var label: String
        if due > 0 {
            let on = Stamp.day(due) == Stamp.day(Stamp.nowMs) ? "today " : Stamp.day(due) + " "
            label = (task["fired"].bool ? "Reminded " : "Reminder · ") + on + Stamp.clock(due)
        } else if task["kind"].string == "reminder" {
            label = "Reminder · no time yet"
        } else if task["auto"].bool {
            label = "Added by Wingman from your conversation"
        } else {
            label = "Note"
        }
        if due > 0 && task["auto"].bool { label += " · added by Wingman" }
        return label
    }

    private func taskColor(_ task: JSON) -> Color {
        if task["due"].double > 0 && !task["fired"].bool { return Palette.accent }
        return task["auto"].bool ? Palette.good : Palette.muted
    }

    @ViewBuilder
    private var todo: some View {
        let tasks = Array(home["tasks"].array.prefix(6))
        let owe = Array(home["owe"].array.prefix(4))
        let total = home["tasks"].array.count + home["owe"].array.count
        SectionHeader("To do", count: total > 0 ? total : nil)
        if tasks.isEmpty && owe.isEmpty {
            BodyText("Nothing to do. Say “remind me to…” or “add it to my list”, or promise someone something, and it lands here.", 15, Palette.muted)
                .padding(.vertical, 16)
        }
        ForEach(tasks.indices, id: \.self) { index in
            let task = tasks[index]
            if index > 0 { HairRule() }
            TodoRow(title: task["text"].string, label: taskLabel(task), labelColor: taskColor(task)) {
                post("/api/tasks/\(task["_id"].string)", ["status": "done"])
            }
        }
        ForEach(owe.indices, id: \.self) { index in
            let promise = owe[index]
            let due = dueText(promise)
            if index > 0 || !tasks.isEmpty { HairRule() }
            TodoRow(title: promise["what"].string,
                    label: "Promised to \(promise["person"].string)" + (due.isEmpty ? "" : " · \(due)"),
                    labelColor: Palette.due) {
                post("/api/promises/\(promise["_id"].string)", ["status": "done"])
            }
        }
    }

    // MARK: - Done

    private func doneLabel(_ task: JSON) -> String {
        let at = task["doneAt"].double
        var parts = [at > 0 ? "Done " + Stamp.day(at) + " " + Stamp.clock(at) : "Done"]
        parts.append(task["doneHow"].string == "said" ? "you told Wingman" : "ticked here")
        if task["auto"].bool { parts.append("added by Wingman") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var done: some View {
        let finished = home["finished"].array
        if !finished.isEmpty {
            SectionHeader("Done", count: finished.count, action: showDone ? "Hide" : "Show") {
                showDone.toggle()
            }
            if showDone {
                ForEach(finished.indices, id: \.self) { index in
                    let task = finished[index]
                    if index > 0 { HairRule() }
                    HStack(alignment: .center, spacing: 0) {
                        VStack(alignment: .leading, spacing: 3) {
                            BodyText(task["text"].string, 15, Palette.muted, lines: 2)
                            LabelText(doneLabel(task), Palette.good)
                        }
                        LabelButton("Undo") {
                            post("/api/tasks/\(task["_id"].string)", ["status": "open"])
                        }
                    }
                    .padding(.vertical, 12)
                }
            }
        }
    }

    // MARK: - Research

    private func studyLabel(_ status: String) -> String {
        switch status {
        case "ready": return "Ready · tap to hear it"
        case "failed": return "Could not finish"
        default: return "Working on it"
        }
    }

    @ViewBuilder
    private var research: some View {
        let all = home["research"].array
        let studies = Array(all.prefix(4))
        if !studies.isEmpty {
            SectionHeader("Research", count: all.count)
            ForEach(studies.indices, id: \.self) { index in
                let study = studies[index]
                let status = study["status"].string
                let ready = status == "ready"
                if index > 0 { HairRule() }
                VStack(alignment: .leading, spacing: 4) {
                    LabelText(studyLabel(status), ready ? Palette.good : (status == "failed" ? Palette.bad : Palette.accent))
                    DisplayText(study["topic"].string.capitalisedFirst, 24, lines: 2)
                    if ready {
                        BodyText(study["short"].string, 14, Palette.muted, lines: 3)
                    }
                }
                .padding(.vertical, 14)
                .contentShape(Rectangle())
                .onTapGesture {
                    if ready { brief("Tell me about your research on \(study["topic"].string), in short.") }
                }
            }
        }
    }

    // MARK: - People you met

    private func metDetail(_ who: JSON) -> String {
        var parts: [String] = []
        if !who["about"].string.isEmpty { parts.append(who["about"].string) }
        parts.append(Stamp.day(who["at"].double) + " " + Stamp.clock(who["at"].double))
        if !who["where"].string.isEmpty { parts.append(who["where"].string) }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var met: some View {
        let people = home["met"].array
        if !people.isEmpty {
            SectionHeader("People you met")
            ForEach(people.indices, id: \.self) { index in
                let who = people[index]
                if index > 0 { HairRule() }
                VStack(alignment: .leading, spacing: 2) {
                    DisplayText(who["name"].string, 22)
                    BodyText(metDetail(who), 13, Palette.muted, lines: 2)
                }
                .padding(.vertical, 14)
            }
        }
    }

    // MARK: - Owed to you

    @ViewBuilder
    private var owed: some View {
        let all = home["owed"].array
        let promises = Array(all.prefix(3))
        if !promises.isEmpty {
            SectionHeader("Owed to you", count: all.count)
            ForEach(promises.indices, id: \.self) { index in
                let promise = promises[index]
                let due = dueText(promise)
                if index > 0 { HairRule() }
                HStack(alignment: .top, spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        DisplayText(promise["what"].string.capitalisedFirst, 26, lines: 2)
                        BodyText("from \(promise["person"].string) · said \(Stamp.day(promise["createdAt"].double))", 13, Palette.muted)
                    }
                    if !due.isEmpty {
                        LabelText(due, Palette.due)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 5)
                            .background(RoundedRectangle(cornerRadius: 8).fill(Palette.dueSoft))
                            .padding(.top, 8)
                    }
                }
                .padding(.vertical, 16)
            }
        }
    }
}

/// One thing to do, with a circle to tick it off.
private struct TodoRow: View {
    let title: String
    let label: String
    let labelColor: Color
    let onDone: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Button(action: onDone) {
                Circle()
                    .stroke(Palette.ink, lineWidth: 1.5)
                    .frame(width: 24, height: 24)
                    .frame(width: 44, height: 44)
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Mark done")
            VStack(alignment: .leading, spacing: 4) {
                DisplayText(title.capitalisedFirst, 24, lines: 2)
                LabelText(label, labelColor)
            }
        }
        .padding(.vertical, 14)
    }
}

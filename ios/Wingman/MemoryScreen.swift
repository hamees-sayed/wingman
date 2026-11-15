import SwiftUI

/// What Wingman knows about the owner: the written-up profile, and the single facts behind it.
struct MemoryScreen: View {
    let back: () -> Void

    @ObservedObject private var hub = Hub.shared
    @StateObject private var memories = Loader()
    @State private var about: JSON?
    @State private var rebuilding = false
    @State private var source = "ChatGPT"
    @State private var pasted = ""
    @State private var importing = false
    @State private var imported = ""

    private static let sources = ["ChatGPT", "Claude", "Typed"]

    private var facts: [JSON] { (memories.value ?? JSON(nil)).array }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Header("Memory", "What Wingman knows about you", back: back)
                VStack(alignment: .leading, spacing: 0) {
                    profile
                    paste
                    known
                }
                .padding(.horizontal, 24)
            }
            .padding(.bottom, 36)
        }
        .scrollDismissesKeyboard(.interactively)
        .task(id: hub.refresh) {
            await memories.pull("/api/memories")
        }
        .task {
            await loadProfile()
        }
    }

    @MainActor
    private func loadProfile() async {
        if let answer = await Server.call("GET", "/api/profile"), answer.isObject { about = answer }
    }

    private func refreshProfile() {
        if rebuilding { return }
        rebuilding = true
        Task { @MainActor in
            if let answer = await Server.call("POST", "/api/profile/refresh"), answer.isObject { about = answer }
            rebuilding = false
            await memories.pull("/api/memories")
        }
    }

    private func addToMemory() {
        importing = true
        imported = ""
        let text = pasted
        let from = source
        Task { @MainActor in
            let answer = await Server.call("POST", "/api/import", body: ["source": from, "text": text])
            importing = false
            if let answer = answer, answer.isObject {
                imported = "Added \(answer["facts"].int) facts, \(answer["people"].int) people"
                pasted = ""
                await memories.pull("/api/memories")
            } else {
                imported = "Could not read that"
            }
        }
    }

    private func forget(_ memory: JSON) {
        Task {
            _ = await Server.call("DELETE", "/api/memories/\(memory["_id"].string)")
            await memories.pull("/api/memories")
        }
    }

    // MARK: - About you

    @ViewBuilder
    private var profile: some View {
        let written = (about ?? JSON(nil))["profile"]
        SectionHeader("About you", action: rebuilding ? "Reading…" : "Refresh") { refreshProfile() }
        if !written.isObject {
            BodyText("Wingman writes this from your conversations, what other assistants know, and every account you connect. It appears once there is something to go on.", 15, Palette.muted)
                .padding(.vertical, 14)
        } else {
            let sections = written["sections"].array
            DisplayText(written["summary"].string, 22)
                .padding(.top, 16)
                .padding(.bottom, 6)
            LabelText("\(written["facts"].int) facts · " + written["sources"].strings.joined(separator: ", "), Palette.muted)
                .padding(.bottom, 10)
            ForEach(sections.indices, id: \.self) { index in
                let section = sections[index]
                let points = section["points"].strings
                LabelText(section["title"].string, Palette.accent)
                    .padding(.top, 16)
                    .padding(.bottom, 4)
                ForEach(points.indices, id: \.self) { row in
                    BodyText(points[row], 15)
                        .padding(.vertical, 4)
                }
            }
        }
    }

    // MARK: - Bringing in more

    @ViewBuilder
    private var paste: some View {
        SectionHeader("From another assistant")
        BodyText("Ask Claude or ChatGPT what it remembers about you, copy the answer, and paste it here.", 15, Palette.muted)
            .padding(.vertical, 14)
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(MemoryScreen.sources, id: \.self) { name in
                    ActionButton(name == "Typed" ? "Typed by me" : "From \(name)", solid: source == name) { source = name }
                }
            }
        }
        ZStack(alignment: .topLeading) {
            TextEditor(text: $pasted)
                .font(Typeface.sans(15))
                .foregroundColor(Palette.ink)
                .tint(Palette.accent)
                .scrollContentBackground(.hidden)
                .padding(8)
            if pasted.isEmpty {
                Text("Paste it here")
                    .font(Typeface.sans(15))
                    .foregroundColor(Palette.muted)
                    .padding(.horizontal, 13)
                    .padding(.vertical, 16)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: 140)
        .background(RoundedRectangle(cornerRadius: 18).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Palette.hair, lineWidth: 1))
        .padding(.top, 12)
        HStack(spacing: 12) {
            ActionButton(importing ? "Reading…" : "Add to memory", solid: true,
                         enabled: !importing && pasted.trimmingCharacters(in: .whitespacesAndNewlines).count >= 20) {
                addToMemory()
            }
            LabelText(imported, imported.hasPrefix("Added") ? Palette.good : Palette.muted)
        }
        .padding(.top, 12)
    }

    // MARK: - Known

    @ViewBuilder
    private var known: some View {
        let all = facts
        SectionHeader("Known", count: memories.value == nil ? nil : all.count)
        if all.isEmpty {
            BodyText("Nothing brought in yet. What Wingman hears in your conversations is kept separately, under Recaps.", 15, Palette.muted)
                .padding(.vertical, 16)
        }
        ForEach(all.indices, id: \.self) { index in
            let memory = all[index]
            HStack(alignment: .center, spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    DisplayText(memory["text"].string, 22)
                    LabelText("From " + memory["source"].string, Palette.muted)
                }
                LabelButton("Forget", Palette.muted) { forget(memory) }
            }
            .padding(.vertical, 14)
            HairRule()
        }
    }
}

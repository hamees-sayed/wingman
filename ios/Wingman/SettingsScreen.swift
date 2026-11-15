import SwiftUI

/// Settings: the owner's voice, how readily Wingman speaks, their data, and where the server is.
struct SettingsScreen: View {
    let redoOnboarding: () -> Void
    let go: (Screen) -> Void
    let back: () -> Void

    @ObservedObject private var hub = Hub.shared
    @State private var demo = false
    @State private var quiet = false
    @State private var checkins = true
    @State private var earbudsOnly = Prefs.get("earbudsOnly") == "1"
    @State private var wiped = ""
    @State private var confirmWipe = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Header("Settings", "Wingman", back: back)
                VStack(alignment: .leading, spacing: 0) {
                    voice
                    remember
                    speaking
                    data
                    SectionHeader("Server")
                    ServerFields(onTested: { reachable in
                        if reachable { Task { await load() } }
                    })
                    notPorted
                }
                .padding(.horizontal, 24)
            }
            .padding(.bottom, 36)
        }
        .scrollDismissesKeyboard(.interactively)
        .task { await load() }
        .alert("Delete everything?", isPresented: $confirmWipe) {
            Button("Delete", role: .destructive) { wipe() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every conversation, person, promise and memory Wingman holds is removed from the server. This cannot be undone.")
        }
    }

    @MainActor
    private func load() async {
        guard let state = await Server.call("GET", "/api/state"), state.isObject else { return }
        let settings = state["settings"]
        demo = settings["demo"].bool
        checkins = settings["checkins"].bool(or: true)
        quiet = settings["eagerness"].string == "quiet"
        hub.ownerEnrolled = state["ownerEnrolled"].bool
    }

    private func save(_ body: [String: Any]) {
        Task { _ = await Server.call("POST", "/api/settings", body: body) }
    }

    private func wipe() {
        Task { @MainActor in
            let answer = await Server.call("POST", "/api/wipe")
            wiped = answer != nil ? "Deleted" : "Server not reachable"
            if answer != nil {
                hub.entries.removeAll()
                hub.chat.removeAll()
            }
            hub.refresh += 1
            await load()
        }
    }

    @ViewBuilder
    private var voice: some View {
        SectionHeader("Your voice")
        BodyText(hub.ownerEnrolled
                 ? "Wingman knows your voice. Run the setup again to re-record it."
                 : "No voice on file. Without it Wingman cannot tell you from anyone else.", 15, Palette.muted)
            .padding(.vertical, 14)
        ActionButton("Run setup again", solid: true) {
            ListenEngine.shared.pause()
            redoOnboarding()
        }
    }

    @ViewBuilder
    private var remember: some View {
        SectionHeader("Remember")
        Button(action: { go(.memory) }) {
            HStack(alignment: .center, spacing: 8) {
                VStack(alignment: .leading, spacing: 0) {
                    DisplayText("Memory", 26)
                    BodyText("What Wingman knows about you, and bringing in more", 13, Palette.muted)
                }
                Image(systemName: "arrow.right")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundColor(Palette.ink)
            }
            .padding(.vertical, 16)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var speaking: some View {
        SectionHeader("How readily it speaks")
        ToggleRow(title: "Quiet", detail: "Needs more confidence, and two minutes between whispers instead of one.", isOn: quiet) { on in
            quiet = on
            save(["eagerness": on ? "quiet" : "normal"])
        }
        ToggleRow(title: "Check-ins", detail: "In a quiet moment Wingman may ask you one question: in your earbuds if they are in, otherwise as a notification.", isOn: checkins) { on in
            checkins = on
            save(["checkins": on])
        }
        ToggleRow(title: "Only speak in earbuds", detail: "With no earbuds or headphones connected, a whisper arrives as a notification instead of aloud.", isOn: earbudsOnly) { on in
            earbudsOnly = on
            Prefs.set("earbudsOnly", on ? "1" : "0")
        }
        ToggleRow(title: "Demo setting", detail: "Eight seconds between whispers and conversations close after twenty quiet seconds.", isOn: demo) { on in
            demo = on
            save(["demo": on])
        }
    }

    @ViewBuilder
    private var data: some View {
        SectionHeader("Your data")
        BodyText("Wingman keeps words, never audio. Voiceprints are kept for you and for people once they are named.", 15, Palette.muted)
            .padding(.vertical, 14)
        HStack(spacing: 12) {
            ActionButton("Delete everything") { confirmWipe = true }
            LabelText(wiped, Palette.muted)
        }
    }

    @ViewBuilder
    private var notPorted: some View {
        SectionHeader("Not on iPhone yet")
        BodyText("Promises and People screens, drafting a message for a promise, and connecting Google, Slack and Notion. Use the Android app or the web console for those.", 15, Palette.muted)
            .padding(.vertical, 14)
    }
}

/// The server's address and the app key, with a button that saves both and tries them.
struct ServerFields: View {
    var onTested: (Bool) -> Void = { _ in }

    @State private var address = Config.host
    @State private var key = Config.keyIsPlaceholder ? "" : Config.key
    @State private var reachable: Bool?
    @State private var testing = false

    private var result: String {
        if testing { return "Testing…" }
        if let reachable = reachable { return reachable ? "Connected" : "Not reachable, or the key is wrong" }
        return ""
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            LabelText("Address")
                .padding(.top, 16)
            TextField("", text: $address, prompt: Text(Config.defaultHost).foregroundColor(Palette.muted))
                .font(Typeface.mono(17, weight: 400))
                .foregroundColor(Palette.ink)
                .tint(Palette.accent)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled(true)
                .keyboardType(.URL)
                .padding(.vertical, 12)
            HairRule()
            LabelText("App key")
                .padding(.top, 16)
            TextField("", text: $key, prompt: Text("The server's WINGMAN_KEY").foregroundColor(Palette.muted))
                .font(Typeface.mono(17, weight: 400))
                .foregroundColor(Palette.ink)
                .tint(Palette.accent)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled(true)
                .padding(.vertical, 12)
            HairRule()
            BodyText("A public name is reached over https; an address and port such as 192.168.1.20:8787 over plain http on your own network.", 13, Palette.muted)
                .padding(.top, 10)
            HStack(spacing: 12) {
                ActionButton("Save and test", enabled: !testing) { saveAndTest() }
                LabelText(result, reachable == false ? Palette.bad : Palette.good)
            }
            .padding(.top, 12)
        }
    }

    private func saveAndTest() {
        Config.setHost(address)
        Config.setKey(key)
        address = Config.host
        testing = true
        Task { @MainActor in
            let answer = await Server.call("GET", "/api/state")
            testing = false
            reachable = answer != nil
            onTested(answer != nil)
        }
    }
}

/// The server fields on their own, for when onboarding cannot reach the server.
struct ServerSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        LabelText("Wingman")
                        DisplayText("Server", 30)
                    }
                    LabelButton("Done") { dismiss() }
                }
                ServerFields()
            }
            .padding(24)
        }
        .background(Palette.paper.ignoresSafeArea())
        .preferredColorScheme(.light)
    }
}

import SwiftUI
import UIKit

/// First run: a name, what Wingman does, the microphone, ten seconds of the owner's voice, done.
struct Onboarding: View {
    let done: () -> Void

    @ObservedObject private var hub = Hub.shared
    @State private var step = 0
    @State private var name = Prefs.get("name") ?? ""
    @State private var started = false // the voice recording has been asked for
    @State private var left = 10
    @State private var showServer = false

    private var cleanName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var saved: Bool { started && !hub.enrolling && hub.enrolMessage.hasPrefix("Voice sample saved") }
    private var failed: Bool { started && !hub.enrolling && !hub.enrolMessage.isEmpty && !saved }

    var body: some View {
        ZStack {
            NightBackground().ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                topBar
                GeometryReader { geometry in
                    ScrollView(showsIndicators: false) {
                        VStack(alignment: .leading, spacing: 0) {
                            page
                        }
                        .frame(maxWidth: .infinity, minHeight: geometry.size.height, alignment: .topLeading)
                    }
                }
                .id(step)
                button
                    .padding(.top, 12)
                    .padding(.bottom, 22)
            }
            .padding(.horizontal, 26)
        }
        .task(id: hub.enrolling) {
            guard started && hub.enrolling else { return }
            left = 10
            while left > 0 {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
                left -= 1
            }
        }
        .onChange(of: saved) { _, now in
            guard now else { return }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
                if step == 3 { step = 4 }
            }
        }
        .sheet(isPresented: $showServer) {
            ServerSheet()
        }
    }

    private var topBar: some View {
        HStack(spacing: 5) {
            if step >= 1 && step <= 3 && !hub.enrolling {
                Button(action: { step -= 1 }) {
                    Image(systemName: "arrow.left")
                        .font(.system(size: 15, weight: .medium))
                        .foregroundColor(.white)
                        .frame(width: 44, height: 44, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Back")
            }
            LabelText("Wingman", .white)
            Spacer()
            ForEach(0..<5, id: \.self) { index in
                Capsule()
                    .fill(Color.white.opacity(index <= step ? 1 : 0.25))
                    .frame(width: index == step ? 22 : 6, height: 6)
            }
        }
        .frame(height: 44)
        .padding(.top, 8)
    }

    // MARK: - Pages

    @ViewBuilder
    private var page: some View {
        switch step {
        case 0: welcome
        case 1: moments
        case 2: openness
        case 3: voice
        default: finished
        }
    }

    @ViewBuilder
    private var button: some View {
        switch step {
        case 0:
            NextButton("Continue", enabled: !cleanName.isEmpty) {
                Prefs.set("name", cleanName)
                step = 1
            }
        case 1:
            NextButton("Continue") { step = 2 }
        case 2:
            NextButton("Allow microphone") { allowMicrophone() }
        case 3:
            NextButton(hub.enrolling ? "Recording" : (failed ? "Record again" : "Start, then read aloud"),
                       enabled: !hub.enrolling && !saved) {
                started = true
                hub.enrolMessage = ""
                hub.error = nil
                // Setup ends in listening, even if it was paused before setup was run again.
                Prefs.set("paused", "no")
                ListenEngine.shared.enroll(name: cleanName.isEmpty ? "Me" : cleanName)
            }
        default:
            NextButton("Open Wingman") { done() }
        }
    }

    private var welcome: some View {
        Group {
            Spacer(minLength: 20)
            Wave(level: 0.5, active: true, color: .white)
                .frame(height: 86)
            Spacer(minLength: 20)
            DisplayText("Your second\nbrain.", 46, .white)
            DisplayText("Always\nlistening.", 46, Palette.nightAccent, italic: true)
            BodyText("A personal assistant that hears your day and remembers it for you. It gives you the name you forgot, keeps the promises you made, and answers when you ask. Only you hear it.", 16, Palette.nightText)
                .padding(.top, 16)
            Spacer(minLength: 24)
            LabelText("What should it call you?", Palette.nightText)
            TextField("", text: $name, prompt: Text("Your first name").foregroundColor(Color.white.opacity(0.4)))
                .font(Typeface.serif(30))
                .foregroundColor(.white)
                .tint(.white)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled(true)
                .submitLabel(.done)
                .padding(.vertical, 8)
            HairRule(color: Color.white.opacity(0.25))
                .padding(.bottom, 10)
        }
    }

    private var moments: some View {
        Group {
            DisplayText("It hears your day.", 38, .white)
                .padding(.top, 26)
            DisplayText("And handles the rest.", 38, Palette.nightAccent, italic: true)
                .padding(.bottom, 14)
            Moment(label: "When you blank", said: "“What's his name, the guy from design…”", whisper: "Rahul.", after: "whispered in your ear, two seconds later")
            Moment(label: "When you have something to add", said: "“I just joined a gym, no idea what routine to follow.”", whisper: "Mention your push-pull-legs plan.", after: "it knows you, so it knows what is worth saying")
            Moment(label: "When you promise", said: "“I'll send you the deck by Friday.”", whisper: "On your to-do list.", after: "added silently, with a recap of the whole conversation")
            Moment(label: "When you ask", said: "“Wingman, move my three o'clock to four thirty.”", whisper: "Moved.", after: "calendar, reminders, notes, Slack, and research in the background")
            Moment(label: "When you're lost", said: "“He called the launch plan a Hail Mary.”", whisper: "A long shot.", after: "the phrase, the jargon or the Hindi you missed, explained")
        }
    }

    private var openness: some View {
        Group {
            Spacer(minLength: 30)
            DisplayText("Always on.", 46, .white)
            DisplayText("In the open.", 46, Palette.nightAccent, italic: true)
                .padding(.bottom, 22)
            numbered("01", "Allow the microphone once. It keeps listening on its own, so there is nothing to remember to switch on.")
            numbered("02", "The iPhone's microphone indicator stays visible the whole time, and Pause is one tap away in the app.")
            numbered("03", "It keeps words, never audio. Delete a conversation, a person, or everything.")
            if let error = hub.error {
                BodyText(error, 14, Palette.nightError)
                    .padding(.top, 10)
            }
            Spacer(minLength: 30)
        }
    }

    private func numbered(_ number: String, _ line: String) -> some View {
        HStack(alignment: .top, spacing: 0) {
            LabelText(number, Palette.nightAccent)
                .frame(width: 34, alignment: .leading)
                .padding(.top, 3)
            BodyText(line, 16, .white)
        }
        .padding(.vertical, 10)
    }

    private var voiceStatus: String {
        if saved { return "Got it" }
        if hub.enrolling { return "Listening · \(left) s left" }
        if failed { return "Try again" }
        if hub.status == "Connecting" && started { return "Connecting" }
        return "10 seconds"
    }

    /// The owner reads a passage for ten seconds while the waveform follows their voice.
    private var voice: some View {
        Group {
            DisplayText(hub.enrolling ? "Keep reading…" : "Now, your voice.", 40, .white)
                .padding(.top, 26)
            BodyText("Wingman must know which voice is yours, so it only steps in for you. Read this aloud, the way you normally talk.", 15, Palette.nightText)
                .padding(.top, 10)
                .padding(.bottom, 20)
            DisplayText("“Hi, I'm \(cleanName). This is how I normally sound when I'm talking to people. I'm reading this so Wingman can tell my voice apart from everyone else's in a conversation, even in a noisy room.”", 24, .white, italic: true)
            Spacer(minLength: 20)
            LiveWave(active: hub.enrolling, color: hub.enrolling ? Color.white : Color.white.opacity(0.4))
                .frame(height: 72)
                .padding(.bottom, 10)
            LabelText(voiceStatus, Palette.nightAccent)
            if failed {
                BodyText(hub.enrolMessage, 14, Palette.nightError)
                    .padding(.top, 8)
            }
            if let error = hub.error {
                BodyText(error, 14, Palette.nightError)
                    .padding(.top, 8)
                Button(action: { showServer = true }) {
                    LabelText("Server settings", .white)
                        .padding(.vertical, 12)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var finished: some View {
        Group {
            Spacer(minLength: 30)
            Image(systemName: "checkmark")
                .font(.system(size: 26, weight: .semibold))
                .foregroundColor(Palette.night)
                .frame(width: 64, height: 64)
                .background(Circle().fill(Color.white))
                .padding(.bottom, 26)
            DisplayText("You're set,\n\(cleanName).", 46, .white)
            BodyText(hub.listening || hub.status == "Connecting"
                     ? "Wingman knows your voice and is already listening. Put your earbuds in and carry on with your day. It stays quiet until you need it."
                     : "Wingman knows your voice. Put your earbuds in and carry on with your day. It stays quiet until you need it.",
                     16, Palette.nightText)
                .padding(.top, 16)
            Spacer(minLength: 30)
        }
    }

    private func allowMicrophone() {
        ListenEngine.shared.prepareNotifications()
        if ListenEngine.micAllowed {
            hub.error = nil
            step = 3
            return
        }
        if ListenEngine.micDenied {
            // iOS asks only once; after a refusal the switch is in the Settings app.
            hub.error = "Wingman cannot work without the microphone. Turn it on for Wingman in the Settings app, then come back."
            if let url = URL(string: UIApplication.openSettingsURLString) {
                UIApplication.shared.open(url)
            }
            return
        }
        ListenEngine.askForMic { granted in
            if granted {
                hub.error = nil
                step = 3
            } else {
                hub.error = "Wingman cannot work without the microphone. Allow it to continue."
            }
        }
    }
}

/// The wide white button at the foot of each onboarding page.
private struct NextButton: View {
    let text: String
    var enabled: Bool
    let action: () -> Void

    init(_ text: String, enabled: Bool = true, action: @escaping () -> Void) {
        self.text = text
        self.enabled = enabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack {
                Text(text)
                    .font(Typeface.sans(17, weight: 600))
                Spacer()
                Image(systemName: "arrow.right")
                    .font(.system(size: 18, weight: .medium))
            }
            .foregroundColor(enabled ? Palette.night : Color.white.opacity(0.53))
            .padding(.horizontal, 24)
            .frame(height: 60)
            .background(Capsule().fill(enabled ? Color.white : Color.white.opacity(0.2)))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// One example of Wingman stepping in: what was said, what it whispered, and what that was.
private struct Moment: View {
    let label: String
    let said: String
    let whisper: String
    let after: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            LabelText(label, Palette.nightAccent)
            BodyText(said, 14, Palette.nightText)
            DisplayText(whisper, 24, .white, italic: true)
            BodyText(after, 13, Palette.nightText)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(RoundedRectangle(cornerRadius: 22).fill(Color.white.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.white.opacity(0.12), lineWidth: 1))
        .padding(.vertical, 6)
    }
}

import SwiftUI

/// A conversation with the agent: typed, or spoken by holding the microphone button.
struct TalkScreen: View {
    let ask: String?
    let asked: () -> Void
    let back: () -> Void

    @ObservedObject private var hub = Hub.shared
    @State private var text = ""
    @State private var holding = false

    private static let starters = ["What do I owe people this week?", "What did I talk about today?", "Who did I meet today?"]

    private var typed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Header("Talk it through", "Wingman · knows your conversations", back: back)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        if hub.chat.isEmpty {
                            DisplayText("Ask what you promised. Plan tomorrow's meeting. Get briefed on someone before you walk in.", 28, Palette.muted, italic: true)
                                .padding(.top, 20)
                        }
                        ForEach(hub.chat) { message in
                            MessageRow(message: message)
                        }
                        if hub.thinking {
                            DisplayText("Thinking…", 22, Palette.muted, italic: true)
                                .padding(.top, 12)
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding(.horizontal, 24)
                    .padding(.vertical, 16)
                }
                .onChange(of: hub.chat.count) { _, _ in
                    withAnimation { proxy.scrollTo("end", anchor: .bottom) }
                }
                .onChange(of: hub.thinking) { _, _ in
                    withAnimation { proxy.scrollTo("end", anchor: .bottom) }
                }
                .onAppear { proxy.scrollTo("end", anchor: .bottom) }
            }
            if let error = hub.error, error.hasPrefix("Wingman needs") {
                BodyText(error, 13, Palette.bad)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 6)
            }
            if hub.chat.count < 2 {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(TalkScreen.starters, id: \.self) { starter in
                            ActionButton(starter) { send(starter) }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)
                }
            }
            inputRow
        }
        .task {
            if hub.chat.isEmpty { await loadHistory() }
            if let question = ask {
                asked()
                send(question)
            }
        }
    }

    private var inputRow: some View {
        HStack(alignment: .center, spacing: 10) {
            ZStack(alignment: .leading) {
                if hub.talking {
                    LiveWave(active: true, color: Palette.accent)
                        .frame(height: 30)
                } else {
                    TextField("", text: $text, prompt: Text("Ask or plan anything").foregroundColor(Palette.muted))
                        .font(Typeface.sans(16))
                        .foregroundColor(Palette.ink)
                        .tint(Palette.accent)
                        .submitLabel(.send)
                        .onSubmit { send(text) }
                }
            }
            .padding(.horizontal, 20)
            .frame(height: 56)
            .frame(maxWidth: .infinity)
            .background(Capsule().fill(Color.white))
            .overlay(Capsule().stroke(Palette.hair, lineWidth: 1))

            if !typed.isEmpty {
                Button(action: { send(text) }) {
                    Image(systemName: "arrow.right")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundColor(.white)
                        .frame(width: 56, height: 56)
                        .background(Circle().fill(Palette.ink))
                        .contentShape(Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Send")
            } else {
                Image(systemName: "mic.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.white)
                    .frame(width: hub.talking ? 68 : 56, height: hub.talking ? 68 : 56)
                    .background(Circle().fill(Palette.accent))
                    .contentShape(Circle())
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { _ in
                                if !holding {
                                    holding = true
                                    ListenEngine.shared.talkStart()
                                }
                            }
                            .onEnded { _ in
                                holding = false
                                ListenEngine.shared.talkStop()
                            }
                    )
                    .accessibilityLabel("Hold to talk")
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)
        .padding(.bottom, 16)
    }

    private func send(_ question: String) {
        let clean = question.trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.isEmpty || hub.thinking { return }
        hub.chat.append(ChatMessage(role: "you", text: clean))
        hub.thinking = true
        text = ""
        Task { @MainActor in
            let answer = await Server.call("POST", "/api/chat", body: ["text": clean])
            hub.thinking = false
            if let answer = answer, answer.isObject {
                hub.chat.append(ChatMessage.from(answer))
            } else {
                hub.chat.append(ChatMessage(role: "wingman", text: "I could not reach the server."))
            }
        }
    }

    @MainActor
    private func loadHistory() async {
        guard let past = await Server.call("GET", "/api/chats") else { return }
        if !hub.chat.isEmpty { return }
        for turn in past.array {
            hub.chat.append(ChatMessage(role: turn["role"].string, text: turn["text"].string, sources: turn["sources"].strings))
        }
    }
}

/// One turn: the owner's in small type, Wingman's in its own voice with any steps and sources.
private struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        if message.role == "you" {
            VStack(alignment: .leading, spacing: 3) {
                LabelText("You", Palette.accent)
                BodyText(message.text, 16, Palette.muted)
            }
            .padding(.top, 18)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                DisplayText(message.text, 26)
                ForEach(message.steps.indices, id: \.self) { index in
                    HStack(alignment: .top, spacing: 0) {
                        LabelText("0\(index + 1)", Palette.accent)
                            .frame(width: 34, alignment: .leading)
                            .padding(.top, 4)
                        BodyText(message.steps[index], 16)
                    }
                    .padding(.top, 12)
                }
                if !message.sources.isEmpty {
                    LabelText("From " + message.sources.joined(separator: " · "), Palette.muted)
                        .padding(.top, 12)
                }
                HairRule()
                    .padding(.top, 14)
            }
            .padding(.top, 10)
        }
    }
}

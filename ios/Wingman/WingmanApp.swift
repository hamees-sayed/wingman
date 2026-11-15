import SwiftUI

@main
struct WingmanApp: App {
    var body: some Scene {
        WindowGroup {
            Root()
        }
    }
}

/// Onboarding until it has been finished once, then the app.
struct Root: View {
    @State private var onboarded = Prefs.get("onboarded") == "yes"

    var body: some View {
        Group {
            if onboarded {
                Shell(redoOnboarding: {
                    Prefs.set("onboarded", "no")
                    onboarded = false
                })
                .preferredColorScheme(.light)
            } else {
                Onboarding(done: {
                    Prefs.set("onboarded", "yes")
                    onboarded = true
                })
                .preferredColorScheme(.dark)
            }
        }
    }
}

enum Screen {
    case home, recaps, talk, live, settings, memory
}

/// The app after onboarding: one screen at a time, with a floating bar on the main ones.
struct Shell: View {
    let redoOnboarding: () -> Void

    @ObservedObject private var hub = Hub.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var screen: Screen = .home
    @State private var ask: String?

    private var tabbed: Bool { screen == .home || screen == .recaps }

    var body: some View {
        ZStack(alignment: .bottom) {
            Palette.paper.ignoresSafeArea()
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                .padding(.bottom, tabbed ? 92 : 0)
            if tabbed { tabBar }
        }
        .onAppear {
            ListenEngine.shared.prepareNotifications()
            resume()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                resume()
                hub.refresh += 1
            }
        }
        .task {
            // Lists reload now and then even if nothing was heard.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 600 * 1_000_000_000)
                if Task.isCancelled { return }
                hub.refresh += 1
            }
        }
    }

    /// Always on: listening resumes whenever the app opens, unless the owner paused it or
    /// another of their devices has taken over.
    private func resume() {
        if Prefs.get("paused") != "yes" && ListenEngine.micAllowed && !hub.listening
            && !hub.status.hasPrefix("Listening on") {
            ListenEngine.shared.start()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch screen {
        case .home:
            HomeScreen(go: { screen = $0 }, brief: { question in
                ask = question
                screen = .talk
            })
        case .recaps:
            RecapScreen()
        case .talk:
            TalkScreen(ask: ask, asked: { ask = nil }, back: { screen = .home })
        case .live:
            LiveScreen(back: { screen = .home })
        case .settings:
            SettingsScreen(redoOnboarding: redoOnboarding, go: { screen = $0 }, back: { screen = .home })
        case .memory:
            MemoryScreen(back: { screen = .settings })
        }
    }

    private var tabBar: some View {
        HStack(spacing: 0) {
            tab("house", "Home", screen == .home) { screen = .home }
            Spacer(minLength: 0)
            Button(action: { screen = .talk }) {
                Wave(level: 0.7, active: true, color: .white, bars: 5)
                    .frame(width: 26, height: 22)
                    .frame(width: 54, height: 54)
                    .background(Circle().fill(Palette.accent))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Talk to Wingman")
            Spacer(minLength: 0)
            tab("doc.plaintext", "Recaps", screen == .recaps) { screen = .recaps }
        }
        .padding(.horizontal, 34)
        .frame(height: 72)
        .background(Capsule().fill(Palette.night))
        .shadow(color: Palette.night.opacity(0.35), radius: 16, x: 0, y: 8)
        .padding(.horizontal, 54)
        .padding(.bottom, 8)
    }

    private func tab(_ icon: String, _ label: String, _ selected: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 21))
                    .foregroundColor(selected ? Color.white : Color(hex: 0x7C86AD))
                Circle()
                    .fill(selected ? Palette.accent : Color.clear)
                    .frame(width: 4, height: 4)
            }
            .frame(width: 60, height: 56)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

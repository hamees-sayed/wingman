# Wingman for iPhone

A thin SwiftUI client for the Wingman server (`wingman/server.py`). It streams the microphone to
the server over a WebSocket, plays the whispers that come back, and shows Home, Talk, Recaps,
Settings and Memory. The Android app in `android/` is the reference for behaviour and look.

This source has never been compiled: it was written on a Mac without Xcode and only checked with
`swiftc -parse`. Expect to fix a few compiler errors on the first build.

## Build and run

1. Install Xcode (15 or newer) from the App Store and open it once so it finishes installing.
2. Install XcodeGen:

   ```
   brew install xcodegen
   ```

3. Generate the project (this also writes `Wingman/Info.plist`):

   ```
   cd ios
   xcodegen
   ```

4. Open it:

   ```
   open Wingman.xcodeproj
   ```

5. In Xcode, select the **Wingman** target, then **Signing & Capabilities**, and choose your
   **Team**. If the bundle id `ai.wingman.app` is taken on your account, change it there.
6. Plug in an iPhone running iOS 17 or later, pick it as the run destination, and press **Run**.
   Use a real device: the simulator has no useful microphone or Bluetooth route.

## The server address and key

Both live in `Wingman/Config.swift`:

- `defaultHost` is `whale-yea-vcr-think.trycloudflare.com`. A public name is reached over https; an
  address with a port, such as `192.168.1.20:8787`, over plain http on the local network.
- `defaultKey` is the placeholder `PUT_WINGMAN_KEY_HERE`. Replace it with the server's
  `WINGMAN_KEY` before building, or leave it and type the key on the phone.

On the phone both can be changed in **Settings › Server**, and during onboarding from the
**Server settings** link that appears under a connection error. What is typed is kept in
UserDefaults and wins over `Config.swift`. The key is sent as the `X-Wingman-Key` header on every
request and on the WebSocket.

## What is here

| File | What it does |
| --- | --- |
| `project.yml` | XcodeGen project: bundle id, iOS 17, Info.plist keys, fonts |
| `Wingman/Config.swift` | Server address and app key |
| `Wingman/Server.swift` | JSON calls to `/api/...`, a small JSON reader, date helpers |
| `Wingman/Hub.swift` | Shared state, and what each WebSocket event does to it |
| `Wingman/ListenEngine.swift` | Microphone, WebSocket, reconnecting, whisper playback, notifications, hold-to-talk |
| `Wingman/Design.swift` | Colours, fonts, the waveform, buttons and headers |
| `Wingman/WingmanApp.swift` | App entry, onboarding or app, the floating tab bar |
| `Wingman/Onboarding.swift` | Name, what it does, microphone, voice recording, done |
| `Wingman/HomeScreen.swift` | Live card, Coming up, To do, Done, Research, People you met, Owed to you |
| `Wingman/LiveScreen.swift` | What Wingman is hearing and whispering now |
| `Wingman/TalkScreen.swift` | Chat with the agent, typed or by holding the microphone button |
| `Wingman/RecapScreen.swift` | Recaps list and one recap |
| `Wingman/SettingsScreen.swift` | Toggles, delete everything, server address and key |
| `Wingman/MemoryScreen.swift` | Profile and known facts, paste to add more |
| `Wingman/Fonts/` | Instrument Serif, Geist and Geist Mono, copied from the Android app |

## Not ported yet

- Promises and People screens, and one person's page
- Drafting a message for a promise and sending it on Slack
- Connections: Google, Slack and Notion sign-in, and sharing the phone's calendar and contacts
- Sharing text into Wingman from another app ("Add to Wingman's memory")

## Things to check on the first real run

- Listening continues with the app in the background (the `audio` background mode keeps it alive
  while the microphone is open). iOS will not let an app start recording from the background, so
  after the phone restarts, or if iOS ends the app, open Wingman once.
- A whisper plays through earbuds when they are connected and through the loudspeaker otherwise.
- With Bluetooth earbuds connected, iOS uses their microphone and the hands-free profile, which
  lowers the quality of any music playing. This comes from recording and playing over Bluetooth
  at once.
- A check-in with no earbuds connected arrives as a notification rather than aloud.
- Geist and Geist Mono are variable fonts; check that the semibold weights render. If a font does
  not load, the app falls back to the system serif, sans and monospace.

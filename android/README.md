# Wingman for Android

The reference client: it streams the microphone to the Wingman server over a WebSocket, plays
the whispers that come back, and has every screen (Home, Talk, Recaps, Promises, People,
Memory, Settings, Connections).

## What you need

- Android Studio, or just the Android SDK and JDK 17
- A running Wingman server and its `WINGMAN_KEY` (see the main README, or the hosted one below)
- A phone on Android 8 or later. The emulator works for the screens, but listening needs a real
  microphone.

## Build

```sh
cp android/local.properties.example android/local.properties
```

Fill in `android/local.properties`. It is never committed.

| Setting | What to put |
| --- | --- |
| `sdk.dir` | Your Android SDK, e.g. `/Users/you/Library/Android/sdk` |
| `wingman.key` | The server's `WINGMAN_KEY` |
| `wingman.server` | The server's address without `https://`, e.g. `52-43-194-6.sslip.io`, or `192.168.1.20:8787` on a home network |
| `wingman.googleClient` | Optional: the Google OAuth web client id, for in-app Google sign-in |

Then:

```sh
cd android && ./gradlew assembleDebug
```

The APK lands in `android/app/build/outputs/apk/debug/app-debug.apk`. CI can pass the same
settings as `WINGMAN_KEY`, `WINGMAN_SERVER` and `GOOGLE_WEB_CLIENT` environment variables.

## Install

Pick one:

- **USB:** turn on Developer options and USB debugging on the phone, then
  `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`.
- **From the server:** `scripts/deploy.sh` copies the latest APK to the server, which then
  serves it at `https://<server>/app.apk?k=<WINGMAN_KEY>`. Open that link on the phone and allow
  installs from the browser when Android asks.

## First run

1. Allow the microphone and notifications.
2. Record the short voice sample so Wingman can tell your voice from everyone else's.
3. Turn listening on. Whispers play through earbuds when they are connected.

If the app cannot reach the server, open **Settings › Server**. What you type there overrides
the address and key the app was built with.

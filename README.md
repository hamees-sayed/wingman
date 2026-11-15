# Wingman

A personal assistant that listens to your day and remembers it for you. It stays silent by
default and speaks one useful line in your ear only when you need it: a name you forgot, a
fact you are reaching for, something of your own worth bringing up, or the meaning of
something you missed. Afterwards it has the recap, the promises and the to-dos, and you can
talk to it to get things done.

Built at a hackathon in one day. It works end to end for a handful of people; the
[limits](#known-limits) section says plainly what is not production-ready.

## What it does

**While you talk**

- **Whispers.** When you stall ("what's his name, the guy from design…") or go quiet after a
  question, it says the name or fact, usually within two seconds.
- **Nudges.** When someone asks about, or is stuck on, something you have first-hand
  experience of, it tells you to bring it up. It stays silent through ordinary conversation.
- **Explanations.** An idiom, jargon or a language you do not follow gets a plain meaning.
- **Notes.** People, promises in both directions and things asked of you are taken down
  silently. Conversations you take no part in (a video, other people nearby) are not kept.

**Afterwards**

- A recap per conversation: summary, key points, promises, to-dos, what it whispered.
- To-dos added by themselves, merged when reworded, with a record of what was finished.
- A drafted follow-up message for each promise you made.
- A brief two minutes before a calendar meeting, and a debrief in the evening.

**When you ask ("Wingman, …")**

- An agent with tools: calendar (read, book, move, cancel), to-dos, reminders, Slack (search,
  pull tasks into to-dos, send after you say yes), Gmail, Notion, Google Docs, people, past
  conversations, memory, and web research that runs in the background.
- It starts working while you are still speaking, says what it is doing ("Checking your
  calendar."), and can be interrupted.

**Knowing you**

- A written profile built from your conversations and every account you connect.
- Memory import from Claude and ChatGPT: ask, copy, come back; or add Wingman to them as a
  connector (MCP) so they write to it directly.
- Each install has its own account. Nothing is shared between accounts.

## How it works

```
phone mic ──PCM16 16 kHz──▶ WebSocket ──▶ FastAPI server
                                            │
   Silero VAD ─▶ Pulse streaming STT ─▶ who is speaking (TitaNet voiceprints, local)
                                            │
        stall / question / wake-word detectors (code, not a model)
                                            │
   ┌─────────────── whisper ───────────────┴────────────── agent ───────────────┐
   │ look up memory, people, Slack, Notion,   tool-calling loop over the         │
   │ Docs, calendar at once ─▶ small model     integrations ─▶ reply             │
   │ decides whether to speak                                                     │
   └──────────────▶ rules (confidence, spacing, staleness) ─▶ Lightning TTS ─▶ phone
```

- **Server** (`wingman/`, Python, FastAPI): the whole pipeline. `session.py` is one listening
  session; `brain.py` holds the prompts for whispers, nudges, notes and recaps; `agent.py` and
  `tools.py` are the agent; `google.py`, `slack.py`, `notion.py`, `recall.py` are the
  integrations; `profile.py` and `daily.py` build the profile, briefs and debriefs;
  `users.py` carries which account a request or task is for.
- **Database** (`convex/`): Convex. Conversations, lines, people (with voiceprints),
  promises, to-dos, memories, research, settings. Every function takes the account.
- **Android app** (`android/`, Kotlin, Jetpack Compose): a foreground service that streams
  the microphone and plays whispers, plus the screens.
- **iPhone app** (`ios/`, SwiftUI): a port of the core screens and the listening engine. It
  is built unsigned in CI; it has not been run on a device.
- **Web console** (`web/index.html`): a plain page for development.

Words are kept; audio never is. A few minutes of audio are held in memory only, to tell
speakers apart.

## Run it

### 1. Server

Needs [uv](https://docs.astral.sh/uv/) and Node (for the Convex CLI).

```sh
cp .env.example .env            # fill in at least the Required block
npm install
npx convex dev                  # creates your Convex deployment and prints its URL; put it in .env as CONVEX_URL
```

Download the two voice models (about 40 MB) into `models/`, from the
[sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases):

- `silero_vad.onnx` (under `asr-models`)
- `nemo_en_titanet_small.onnx` (under the speaker recognition models)

```sh
uv sync
uv run uvicorn wingman.server:app --host 0.0.0.0 --port 8787
```

On a laptop at home, set `WINGMAN_TRUST_LAN=1` so a phone on the same Wi-Fi is let in. For
anything reachable from the internet, put it behind HTTPS and set `PUBLIC_URL` to that
address: Slack sign-in and the connector need a real https address.

### 2. Android app

```sh
cp android/local.properties.example android/local.properties   # sdk path, key, server, Google client id
cd android && ./gradlew assembleDebug
```

The APK lands in `android/app/build/outputs/apk/debug/`. The server also serves the last
build at `/app.apk?k=<WINGMAN_KEY>`, which is the easy way to get it onto a phone. The full
guide is in [android/README.md](android/README.md).

The iPhone app is in `ios/`. CI builds it, and you can sideload it without Xcode; see
[ios/README.md](ios/README.md).

### 3. Connections

Each is optional and is set up once, on the server side:

| Service | What to create | Notes |
| --- | --- | --- |
| Google | OAuth web client and Android client in one Cloud project | Enable the Calendar, Drive, Gmail and People APIs. While the project is in testing, each person must be added as a test user. |
| Slack | A Slack app with user-token scopes (see `wingman/slack.py`) | Add `PUBLIC_URL/oauth/slack/callback` as a redirect URL; turn on public distribution for other workspaces. |
| Notion | A public integration | The person chooses which pages to share when they connect. |
| Supermemory | An API key | Search by meaning. Without it Wingman falls back to word search. |

### 4. Hosting

For a fresh Ubuntu 24.04 machine (an EC2 `t3.medium` with ports 22, 80 and 443 open is enough),
`scripts/ec2-setup.sh` installs everything in one go. It sets up a local Convex backend (the
`convex` service on `127.0.0.1:3210`), the `wingman` service, and Caddy, which serves https and
fetches its own certificate. Use an Elastic IP, and the free `sslip.io` name for it as the domain:

```sh
ssh ubuntu@52.43.194.6 'sh -s' -- 52-43-194-6.sslip.io America/Los_Angeles < scripts/ec2-setup.sh
scp .env ubuntu@52.43.194.6:wingman/.env   # with PUBLIC_URL=https://52-43-194-6.sslip.io and CONVEX_URL=http://127.0.0.1:3210
WINGMAN_HOST=ubuntu@52.43.194.6 WINGMAN_SSH_KEY=~/.ssh/your-key.pem scripts/deploy.sh
```

The second argument sets the machine's time zone. The server reads times like "remind me at
4 pm" off its own clock, so give it the time zone of the people using it. On a machine left at
UTC, a 4 pm reminder from California fires at 8 am. The phone apps then use
`52-43-194-6.sslip.io` as the server address. The Convex data lives on
the machine under `~/.convex`, so back it up before you terminate the instance.

`scripts/deploy.sh` copies the code and the latest APK to a machine and restarts the
service there (`WINGMAN_HOST=user@host`). It expects a systemd unit called `wingman`
running `uv run uvicorn wingman.server:app --host 127.0.0.1 --port 8787` and something
in front for HTTPS (Caddy with a `reverse-proxy` to port 8787 is enough). It never touches
the server's `.env` or saved sign-ins.

Pick a machine with a fast route to OpenAI and Smallest as well as to you. Each turn makes
several calls out, so a machine that is close to the phone but slow outbound is no gain.

## Tests and scripts

```sh
uv run python -m pytest tests -q          # the agent's tool loop, offline
uv run python -m scripts.recall_backfill  # copy an account's facts and conversations into Supermemory
```

`scripts/scenarios.py` replays scripted two-voice conversations through the real pipeline.
**It wipes the first owner's database before it runs.** Do not point it at data you want.

## Accounts

Each app install makes a long random token on first launch and sends it with every request
(`X-Wingman-User`). The server turns it into an account id, stamps it on every database call
and keeps that account's sign-ins and caches in their own folder. Rows from before accounts
existed belong to `"owner"`; the first existing install to update claims them
(`POST /api/account/claim`).

## Known limits

- **The app key is shared.** `WINGMAN_KEY` is compiled into the app. It gets a request to the
  door, not into an account, but it should become a per-person sign-in.
- **No account recovery.** The account lives on the phone; reinstalling starts a new one.
- **The database trusts the server.** Convex functions take the account id as an argument.
  Keep the Convex URL private, or add a server secret to every function.
- **Costs are yours.** Every account runs on the server's OpenAI, Smallest and Supermemory keys.
- **Speech is one at a time.** The text-to-speech service allows one request in flight.
- **Latency.** About 1.2 to 1.8 s from the end of speech to the first spoken line for a lookup,
  measured by replay; a direct answer takes about 2.4 s. Under a second would need a
  speech-to-speech model.
- **Speaker separation** is done locally per sentence and gets short lines wrong.
- **Google verification.** Until the Cloud project is verified, only test users can sign in.
- **iPhone.** Background listening is the least certain part and has not been tried on a device.

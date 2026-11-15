# Wingman: running this copy

Secrets are not included. To run it:

1. Copy `.env.example` to `.env` and fill in the values (OpenAI, Smallest, Google, Notion and Slack
   credentials, and a `WINGMAN_KEY` of your choosing). Copy `.env.local.example` to `.env.local`
   and set `CONVEX_URL` to your own Convex deployment (`npx convex dev` creates one).
2. Put the same `WINGMAN_KEY` in `android/app/src/main/java/ai/wingman/app/Hub.kt` (`APP_KEY`),
   and set `DEFAULT` there to your server's address.
3. The two voice models are not in this zip (64 MB). Place `silero_vad.onnx` and
   `nemo_en_titanet_small.onnx` (sherpa-onnx releases) in `models/`.
4. Server: `uv sync`, then `uv run uvicorn wingman.server:app --host 0.0.0.0 --port 8787`.
5. Android: in `android/`, `./gradlew assembleDebug`.
6. `ios/` is uncompiled SwiftUI source; see `ios/README.md`.

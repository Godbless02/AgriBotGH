# Abena Twi Text-to-Speech Integration

## Scope and architecture

This feature changes response playback only. The frozen TF-IDF retrieval model,
canonical 563-record dataset, entity safeguards, routing states, Gemini
assistance, weather integration, and speech-to-text flow are unchanged.

- English responses continue to use browser `SpeechSynthesis` only.
- Twi responses first call AgriBotGH's `POST /api/tts` endpoint.
- Flask calls Abena AI with the server-owned `abena_twi_lite` voice and speed.
- Audio stays in memory as base64 and is never written to disk.
- The browser plays returned chunks sequentially through `HTMLAudioElement`.
- Any provider, transport, response, or playback failure attempts the existing
  browser speech path once. User cancellation does not trigger fallback.

## Configuration

Copy the relevant names from `.env.example` for local use, or add them directly
to the Render service environment:

```text
ABENA_TTS_ENABLED=true
ABENA_TTS_API_URL=https://abena.mobobi.com/playground/api/v1/tts/synthesize/
ABENA_TTS_TWI_VOICE=abena_twi_lite
ABENA_TTS_SPEED=1.0
ABENA_API_KEY=
```

The safe code default for `ABENA_TTS_ENABLED` is `false`, so a checkout or test
process cannot spend provider quota accidentally. `.env.example` enables the
feature as the intended deployment configuration. The API key is optional,
loaded only by Flask, sent only as a bearer header when present, ignored by the
frontend, and excluded by the repository's `.gitignore` rules.

## API contract

The browser sends JSON only:

```json
{"text": "Twi response text", "language": "twi"}
```

It cannot select the provider, voice, speed, URL, or credentials. Empty,
malformed, non-Twi, and non-JSON requests return HTTP 400. Text above 4,000
characters returns HTTP 413. A successful response returns an ordered `clips`
array containing `audio_base64`, `mime_type`, and optional `duration_seconds`.
Provider failures return HTTP 503 with a stable code and
`fallback_allowed: true`; raw upstream response bodies are not exposed.

Abena accepts no more than 500 characters per synthesis request. AgriBotGH
normalizes whitespace and splits at a target of 480 Unicode characters,
preferring sentence punctuation, then commas, then word boundaries, with a hard
split only when necessary. Each chunk is requested exactly once and no automatic
retry can duplicate quota usage.

## Playback and cancellation

During a Twi request the control reports `Preparing natural Twi audio...`. The
returned clips share the existing Pause/Resume and Stop controls. Starting a
different response, starting speech recognition, changing language/session, or
clearing/resetting the chat aborts pending fetches and stops current media.
Request IDs prevent late fetch, media, or cancellation events from changing a
newer response's controls.

Fallback is visibly labelled so the application does not misrepresent browser
pronunciation as natural Twi speech. If browser synthesis is also missing, the
audio control reports unavailability while the response text stays usable.

## Tests

Normal tests are fully mocked and never call Abena:

```powershell
python -m unittest -v test_abena_tts_service.py
npx playwright test tests/tts.spec.js tests/stt.spec.js
```

The dedicated live smoke test is opt-in only and is not run automatically:

```powershell
$env:RUN_LIVE_ABENA_TTS="1"
python -m unittest -v test_abena_tts_live.py
Remove-Item Env:RUN_LIVE_ABENA_TTS
```

Only run it deliberately when quota use is authorized. It reports pass/fail and
never prints an API key or returned audio data.

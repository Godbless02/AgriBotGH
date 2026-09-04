# Twi/Akan Browser Speech-to-Text Investigation

Investigation date: 30 August 2026

## Decision

AgriBotGH does not enable browser-native Twi speech input in this release.
Neither tested browser exposes an available `tw-GH` or `ak-GH` local recognition
model, and no usable Twi/Akan transcript was produced. Assigning either string
to `recognition.lang` is not proof that the recognition service supports the
language. Twi typing and the existing Twi retrieval and Gemini-assistance path
remain unchanged.

## Vendor evidence

- Microsoft documents only `en-US`, `de-DE`, `it-IT`, `pt-PT`, `es-ES`, and
  `ko-KR` for its current Edge on-device recognizer. It lists neither Akan nor
  Twi: https://learn.microsoft.com/en-us/microsoft-edge/web-platform/speech-recognition-api
- Microsoft documents that the established Edge Web Speech implementation uses
  Azure Cognitive Services: https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/SpeechRecognitionEnabled
- Azure Speech's current transcription locale table contains neither Akan/Twi,
  `ak-GH`, nor `tw-GH`:
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support
- Chrome's official Web Speech demo language table contains neither Akan nor
  Twi: https://github.com/googlearchive/webplatform-samples/blob/master/webspeechdemo/webspeechdemo.html
- Google Cloud Speech-to-Text's maintained locale table also contains neither
  Akan/Twi, `ak-GH`, nor `tw-GH`:
  https://cloud.google.com/speech-to-text/docs/speech-to-text-supported-languages

## Installed-browser probes

The project was served from secure-context localhost. Chrome and Edge were
launched with microphone permission and a browser-provided fake audio device.
The probe checked the real constructor, `SpeechRecognition.available()` with
`processLocally: true`, and a recognition start lifecycle for every candidate.

| Browser | Version | `tw-GH` local | `ak-GH` local | Result |
|---|---:|---|---|---|
| Google Chrome | 152.0.7977.64 | unavailable | unavailable | Locale strings could be assigned, but no transcript was produced. |
| Microsoft Edge | 151.0.4129.93 | unavailable | unavailable | Neither candidate produced a usable Twi/Akan lifecycle or transcript. |

For comparison, Chrome reported `en-GH` and `en-US` as downloadable. Edge's
cloud path completed an `en-US` recognition lifecycle and returned the expected
`no-speech` result for synthetic non-speech input. This confirms that the probe
could distinguish an operating English path from the unsupported Twi/Akan
candidates.

## Agricultural phrase decision

Real Twi phrase accuracy testing was conditional on finding a compatible
recognition locale. That prerequisite failed, so the application did not send
Twi speech through an English recognizer and did not invent transcripts. The
following canonical dataset questions are reserved for a future real-speaker
benchmark once an explicit Twi/Akan ASR model is available:

1. `Ferefere bɛn na ɛyɛ papa ma aburo?`
2. `M'aburow nhaban wɔ tumtum na wɔredidi won. Dɛn na meyɛ?`
3. `Osu tenten ma nsuo hyɛɛ m'afuo mu. Dɛn na meyɛ?`
4. `Ɛdeɛn na menim bere a osu reba?`
5. `Dɛn na menyɛ asase no so ansa na meto aburoɔ?`

These cover fertilizer, maize symptoms/pests, flooding, weather, and land
preparation. A future benchmark must also cover pronunciation and spelling
variation, code-switching, noisy farms, multiple speakers, crop/entity accuracy,
and Ghanaian place names.

## Safest future alternative

Do not add a generic cloud recognizer or translation layer merely to display a
Twi microphone. Build a separate, opt-in prototype around a model that explicitly
supports Asante/Akuapem Twi, then compare it against a consented Ghanaian
agricultural speech test set. Mozilla Common Voice provides a small Twi ASR
dataset, and Ghana-focused research models such as the Southern Ghana DONDO
w2v-BERT family are candidates for evaluation, not automatic production choices:

- https://commonvoice.mozilla.org/en/datasets
- https://huggingface.co/KhayaAI/w2v-bert-ada_ewe_fat_fra_gaa_nzi_twi_en

Adopt a future model only after human review shows acceptable word error rate and
high accuracy for crops, pests, fertilizers, quantities, and locations. The
result must remain an editable Twi transcript and must enter AgriBotGH's existing
Twi retrieval pipeline without translation. Any server-side option also requires
explicit recording consent, retention controls, secure transport, cost and
latency measurement, and a fresh privacy review.

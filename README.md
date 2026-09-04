# AgriBotGH

A bilingual (English–Twi) agricultural chatbot for Ghanaian farmers.

## Project Overview

AgriBotGH is a Flask web application that answers farming questions in English and Twi using a validated topic-aware TF-IDF retrieval model and four-state response router.

## System Architecture

```text
Browser UI (HTML/CSS/JavaScript, localStorage history, Web Speech API)
        |
        v
Flask JSON API
        |
        +--> saved English or Twi retrieval artifact (all 563 records)
                 |
                 +--> word + character TF-IDF similarity (weight 0.38)
                 +--> training-category centroid relevance (weight 0.62)
                 +--> raw-similarity + margin confidence routing
                         A: strong canonical dataset answer
                         B: internal weak retrieval / controlled Gemini retry
                         C: off-topic response
                         D: agricultural knowledge-gap response
```

Flask verifies the canonical dataset, active metadata, configuration,
evaluation, final comparison, freeze manifest, and language artifacts at
startup. It never trains a model while serving requests.

## Files and Purpose

- `app.py` — Flask backend, AI retrieval logic, and API endpoints.
- `app.js` — frontend chat UI, localStorage session history, and language controls.
- `index.html` — chat application markup.
- `style.css` — UI styling and responsive layout.
- `data/agribotgh_dataset_bilingual_563.json` — canonical 563-record bilingual dataset used by the app.
- `models/production/active_model.json` — checksum-protected pointer to the active versioned model bundle.
- `models/quick_questions.json` — display-only canonical prompts with no answer IDs or routing shortcuts.
- `evaluate_retrieval_robustness.py` — reproducible n-gram, normalization, top-k, margin, and negative-control benchmark.
- `debug_retrieval.py` — local-only top-3 diagnostics; it is not exposed by Flask.
- `build_retrieval_artifacts.py` — reproducible production model builder.
- `activate_model.py` — validated model activation and rollback utility.
- `requirements.txt` — Python dependencies.
- `Procfile` — deployment command for Gunicorn.

## Dataset Policy

`data/agribotgh_dataset_bilingual_563.json` is the sole authoritative dataset.
The application, suggestion builder, split generator, training workflow, and
validation workflow must derive their records from this file. Legacy datasets
and fallback dataset schemas are not supported.

TODO 19's final expansion quality gate kept the dataset at 563 records. The
review found that category cleanup, semantic deduplication, expert safety
review, and native Twi review must come before adding more records. The audit
and future release gates are recorded in
`data/evaluation/todo19_dataset_expansion_assessment.json`.

Run `python validate_dataset.py` before any split or training operation. TODO
20's validator checks the exact schema, IDs, Unicode integrity, canonical
category labels, normalized duplicates, question/answer shape, and bilingual
field separation. It writes the complete result and non-blocking human-review
queues to `data/evaluation/dataset_quality_report.json`.

The final `train_model.py` runs that validation itself, recreates and verifies
the deterministic 70/15/15 split, trains the selected topic-aware TF-IDF model,
evaluates both languages against the gold standard, builds the deployment
index from all 563 canonical records, and atomically saves a new
checksum-protected semantic version. It refuses to overwrite an existing
version and does not activate a candidate unless `--activate` is explicit.

Run `python test_model.py` for the final bilingual model behavior matrix. It
tests exact questions, paraphrases, supported and unsupported agriculture,
off-topic handling, malformed input, short and long prompts, normalization,
mixed-language input, and language separation. Results are saved to
`models/final_model_test_results.json`, and any failed contract returns a
non-zero process exit code.

TODO 23's independent bilingual off-topic challenge is stored in
`data/evaluation/off_topic_questions.json`. Run
`python evaluate_off_topic_questions.py` to validate its English/Twi pairing,
confirm it does not duplicate the router-development set, and verify that every
ordinary and agricultural-word hard negative receives State C without an
agricultural answer. Results are written to
`models/off_topic_question_results.json`.

TODO 24's bilingual agricultural robustness set is stored in
`data/evaluation/agriculture_edge_cases.json`. Run
`python evaluate_agriculture_edge_cases.py` to exercise vague, incomplete,
misspelled, colloquial, short, long, paraphrased, and multiple-topic prompts.
The check rejects false State-C classifications and unsupported confident
answers, and writes measured results to
`models/agriculture_edge_case_results.json`.

TODO 25's language-separation evaluator samples every canonical category in
both languages and verifies the API response, saved retrieval artifact, and
candidate question/answer fields never cross languages. Run
`python evaluate_language_separation.py`; results are written to
`models/language_separation_results.json`. Browser history and speech controls
also retain the language of the original request when users switch languages.

Text-to-speech is manual and never starts automatically. Each bot message has
Play/Pause/Resume and Stop controls, starting another message stops the previous
one, and switching languages cancels active speech. English remains entirely
browser-native. Twi first requests the server-side Abena `abena_twi_lite` voice;
if it is disabled or unavailable, browser speech remains as an explicitly
labelled fallback. Retrieval does not depend on speech support.

The browser regression suite covers the complete responsive matrix at widths
1920, 1440, 1366, 1280, 1024, 768, 480, 390, and 375 pixels. It verifies the
desktop collapsible sidebar, mobile history drawer, quick-question panel,
topics, suggestions, input/send controls, TTS controls, language selector,
history, and absence of horizontal overflow.

Typed questions, starter suggestions, topic suggestions, and right-panel quick
questions all use the same frontend `submitQuestion()` path. The theme system
prioritizes a saved manual choice, then the browser colour scheme, then a
night-time fallback when browser theme detection is unavailable.

TODOs 29–30 are measured by `evaluate_response_quality.py`. It audits all 1,126
language-specific canonical answers, composes the agricultural-edge, off-topic,
and language-separation suites, and verifies that every detected high-risk
pesticide, chemical, fertilizer-rate, vaccine, dosage, or animal-treatment
answer carries a separate bilingual safety notice. Canonical answer text remains
unchanged. Automated checks cannot replace qualified agronomic and native-Twi
review; that limitation is recorded in the generated report.

TODO 31's source-traceable architecture comparison is generated by
`create_final_model_comparison.py`. TODO 32 freezes the selected active bundle
with `freeze_model.py`; the freeze manifest hashes the dataset, metadata,
configuration, evaluation, comparison, and both language artifacts. Frozen
versions 1.0.1 and 1.1.1 must never be modified in place—future model changes
require a new semantic version and complete evaluation.

TODO 33's Flask/model parity report is generated by
`evaluate_integration_regression.py`. TODO 34's reproducible local benchmark is
generated by `measure_performance.py` and records cold startup, retrieval and
Flask latency distributions, working-set memory, environment details, and the
declared responsiveness limits used for pass/fail decisions.

TODO 35's deterministic demonstration matrix is built by
`build_presentation_test_set.py`. It contains exactly 20 English questions, 20
Twi questions, 10 paraphrases, 10 off-topic questions, 10 topic selections, and
10 TTS cases. `evaluate_presentation.py` executes the 70 backend cases and the
Playwright presentation test executes the 10 real browser speech-control cases,
completing `models/presentation_test_results.json`.

## Final Measured Results

The complete Chapter Four source data is in
`models/final_project_report_data.json`; a report-ready summary is in
`docs/FINAL_PROJECT_REPORT_DATA.md`.

| Metric | English | Twi |
|---|---:|---:|
| Gold-answerable validation cases | 18 | 18 |
| Top-1 retrieval accuracy | 50.00% | 50.00% |
| Top-3 retrieval accuracy | 66.67% | 61.11% |
| Retrieval precision over all 84 validation cases | 10.71% | 10.71% |
| Ranking coverage | 100.00% | 100.00% |
| Category-match rate | 47.62% | 53.57% |

The v1.1.1 confidence gate requires raw TF-IDF similarity of at least `0.50`
and a raw top-1 margin of at least `0.05`. On 35 reviewed paraphrases it reached
85.71% top-1 and 94.29% top-3 accuracy; 24/35 were confidently answered, all
24 accepted answers were correct, and 120 negative controls produced zero
false accepts. The system sends weaker evidence to State B. Similarity and
margin are not probabilities.

Independent challenges pass 48/48 off-topic cases, 32/32 agricultural edge
cases, 80/80 language-separation cases, and 80/80 presentation cases.

## Python Environment

The application uses Python 3.13.5, recorded in `.python-version` (the format
currently supported by Render). `runtime.txt` is retained only as a legacy
deployment reference. The project
virtual-environment name is `agribot_env`.

### Windows PowerShell

```powershell
py -3.13 -m venv agribot_env
.\agribot_env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, allow locally created scripts for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Alternatively, run the environment without activation:

```powershell
.\agribot_env\Scripts\python.exe -m pip install -r requirements.txt
.\agribot_env\Scripts\python.exe app.py
```

### Windows CMD

```cmd
py -3.13 -m venv agribot_env
agribot_env\Scripts\activate.bat
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

### Recreate From Scratch

Delete the local `agribot_env` directory, then run the PowerShell or CMD commands
above. `requirements.txt` is the sole authoritative Python dependency file.

### Configuration

The application reads these variables from the process environment:

- `FLASK_DEBUG` — set `true` only for local debugging.
- `PORT` — listening port; defaults to `5000`.
- `GEMINI_API_KEY` — optional server-side key for low-confidence retrieval
  assistance. Leave unset to disable the feature safely.
- `GEMINI_MODEL` — optional model override; defaults to
  `gemini-3.5-flash-lite`.
- `ABENA_TTS_ENABLED` — set `true` to enable server-side natural Twi audio.
- `ABENA_TTS_API_URL`, `ABENA_TTS_TWI_VOICE`, and `ABENA_TTS_SPEED` —
  server-owned provider settings documented in `.env.example`.
- `ABENA_API_KEY` — optional server-side bearer credential; never expose it to
  frontend JavaScript.
For local development, the server loads the project-root `.env` file when it
exists. Values already supplied by the operating system or deployment platform
are never overwritten. On Render, configure secrets in the service environment;
the ignored local `.env` file is not required or deployed.
Ordinary unit-test runs do not load the project `.env`, preventing accidental
live API usage. The explicitly opted-in live test loads it when
`RUN_GEMINI_LIVE_TESTS=true` or `RUN_LIVE_ABENA_TTS=1` is set for the relevant
explicit live test.

Gemini is not an answering engine in this application. It is called at most
once, and only after the local router produces an uncertain agricultural State
B result. It may rewrite that query for a second pass through the same frozen
local retriever. The second pass is used only when it becomes a strong State A
match without lowering the raw TF-IDF score; the displayed answer still comes
verbatim from `data/agribotgh_dataset_bilingual_563.json`. Strong matches,
off-topic requests, and live-weather requests bypass Gemini. Missing keys,
timeouts, rate limits, malformed output, or unsafe entity changes fail safely.
If a question remains weak and is clearly agricultural, the user receives the
State D knowledge-gap response rather than a generated answer.

### Retrieval States and Knowledge Gaps

- **State A** is a strong supported match and returns the canonical answer from
  the 563-record bilingual dataset.
- **State B** is an internal weak-retrieval stage. Where allowed, Gemini may
  interpret the wording once in the same language before the unchanged local
  retriever runs again.
- **State C** is a clearly off-topic request and keeps the existing
  agricultural-scope response.
- **State D** is a farming question for which no sufficiently reliable dataset
  answer could be retrieved after the permitted assistance step.

State D does not trigger unrestricted Gemini agricultural answer generation.
Its wording deliberately does not claim that knowledge is certainly absent: a
State D result can mean either a true dataset knowledge gap or wording that the
retriever cannot confidently connect to existing knowledge. The displayed
available topics are built once from the nonblank, deduplicated `category`
values in the already-loaded canonical dataset, so they remain synchronized
with that dataset. Selecting one of these semantic buttons places the topic in
the editable chat input; it does not invent or auto-submit an answer.

### Hybrid Text-to-Speech

Bot response cards include Listen, Pause/Resume, and Stop controls. Playback is
user initiated and limited to one response at a time. English uses browser
`SpeechSynthesis`. Twi posts cleaned text to `/api/tts`; Flask keeps provider
configuration private, chunks Unicode text in memory, and returns ordered Abena
audio clips for browser playback. Each historical response retains its text and
language association.

Voice discovery supports both immediately available and asynchronously loaded
browser voices. English selects an available `en-*` voice without depending on
a vendor-specific name. If Abena is disabled, fails, or returns unusable audio,
Twi falls back once to a `tw-*`, Akan `ak-*`, or final browser voice with an
accuracy warning. Intentional cancellation never starts fallback. If both
engines are unavailable, the response stays readable. Full configuration,
contract, and test details are in `docs/ABENA_TWI_TTS_INTEGRATION.md`.

### Browser Speech-to-Text

In English mode, browsers that expose `window.SpeechRecognition` or
`window.webkitSpeechRecognition` provide a user-initiated microphone control.
One short question is recognized with the `en-GH` locale and placed in the
existing editable chat input. Recognition never auto-submits: the user reviews
or corrects crop, product, pest, and location names before pressing Send. Send
then uses the unchanged Flask, weather, TF-IDF, and optional Gemini-assisted
chat pipeline used for typed questions.

Recognition stops when the user submits, clears chat, changes language or
session, resets the application, or starts response playback. Starting voice
input first cancels response playback so AgriBot does not listen to itself.
Permission, unavailable-device, no-speech, network, and unsupported-browser
failures leave typed input available. No microphone audio is uploaded to Flask,
stored by the application, or logged, and there is no speech-to-text backend or
credential.

Browser-native Twi/Akan recognition is not claimed. Direct release testing found
that Chrome 152 reports both `tw-GH` and `ak-GH` unavailable for local
recognition; Edge 151 also reports both unavailable and neither browser produced
a usable Twi/Akan transcript. The microphone is therefore disabled in Twi mode
with a clear explanation; curated Twi text input and the existing Twi
Gemini-assisted retrieval path remain fully supported. Full evidence and the
safe future evaluation path are recorded in
`docs/TWI_STT_INVESTIGATION.md`. Web Speech recognition support varies by
browser and normally requires HTTPS in production (or localhost during
development).

## Notes

- The backend exclusively uses `data/agribotgh_dataset_bilingual_563.json`.
- Flask loads the immutable bundle selected by `models/production/active_model.json`; it does not retrain at startup.
- Artifact checksums and the canonical dataset checksum are verified during startup.
- The canonical dataset must be present locally; startup fails clearly if it is missing or invalid.
- There is no database, server-side authentication, email/SMTP, or Paystack
  integration in the current application. User names and chat history are kept
  in browser `localStorage` only.
- English and Twi sessions are stored separately per browser user. Refreshing
  restores the history list; **Clear Chat** starts a new blank session without
  deleting earlier history. The current UI does not provide permanent history
  deletion.
- The active Python runtime dependencies are Flask, scikit-learn, NumPy,
  joblib, Gunicorn, Requests, and the optional server-side Google Gen AI SDK;
  their versions are pinned in
  `requirements.txt`.

## Evaluation and Reproduction

Run the core evidence generators from the activated virtual environment:

```powershell
python validate_dataset.py
python evaluate_retrieval.py
python evaluate_off_topic_questions.py
python evaluate_agriculture_edge_cases.py
python evaluate_language_separation.py
python evaluate_response_quality.py
python create_final_model_comparison.py
python evaluate_integration_regression.py
python measure_performance.py
python evaluate_presentation.py
python generate_final_project_report.py
python evaluate_gemini_assistance.py
python -m unittest discover -v
npm test
```

`evaluate_gemini_assistance.py` is a live, opt-in six-case English/Twi
evaluation. Without `GEMINI_API_KEY` it writes an honest skipped report and
makes no network call. The optional one-request live unit test additionally
requires `RUN_GEMINI_LIVE_TESTS=true`. All ordinary tests use mocks.

## Deployment

For Render, create a Python 3 web service with build command
`pip install -r requirements.txt`, start command `gunicorn app:app`, and health
check path `/api/health`. `.python-version` pins Python 3.13.5. Render supplies
`PORT`. Keep `FLASK_DEBUG` disabled. To enable retrieval assistance, add
`GEMINI_API_KEY` as a secret environment variable and optionally set
`GEMINI_MODEL`; never place the key in frontend code or commit it.
To enable natural Twi playback, set `ABENA_TTS_ENABLED=true` and the Abena
settings shown in `.env.example`; add `ABENA_API_KEY` only if the provider
requires it. Render injects these values at runtime and does not need `.env`.
The app has no database migration, SMTP, Paystack, or authentication service
requirements. Static frontend files are served by Flask from the project
directory.

## Limitations

- Only 36 of the 168 bilingual validation questions were judged answerable from
  the training split; ranking metrics must be interpreted on that basis.
- Conservative automatic answering improves reliability at the cost of low
  fuzzy-answer coverage. Exact canonical questions and linked suggestions
  remain deterministic.
- The tested local dense embedding model did not outperform topic-aware TF-IDF;
  a pretrained multilingual transfer could not be integrity-verified under the
  available host/network limits.
- Twi quality has automated Unicode, separation, and behavior checks, but still
  needs review by native Twi speakers.
- Agricultural answers and the high-risk keyword policy still need periodic
  review by qualified extension, veterinary, and crop-protection professionals.
- Natural Twi playback depends on Abena availability and quota. Browser
  fallback quality still depends on installed voices, and the UI discloses
  potentially inaccurate fallback pronunciation.
- No human-participant usability study results were supplied.

## Future Work

- Conduct native-Twi and agricultural-expert review before expanding beyond 563
  records.
- Collect genuine farmer paraphrases and hard negatives for a larger external
  test set.
- Re-evaluate a checksum-verified multilingual sentence model when reliable
  model transfer and deployment resources are available.
- Add a calibrated confidence model only after collecting enough labelled
  production-style queries.
- Run structured usability testing with farmers and extension officers; report
  participant counts and measured outcomes separately from automated UI tests.

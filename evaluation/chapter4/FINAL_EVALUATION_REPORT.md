# AgriBotGH Final Formal Chapter Four Evaluation Evidence

Generated: 2026-09-01T23:42:05.776149+00:00

## 1. Feature-freeze verification

- Active model: AgriBotGH Retrieval Model v1.3.1 (semantic version 1.3.1)
- Dataset SHA-256: `45dcf61300699d4808c6843efa07c1a9648f2b136b5c1740139f8d67fe57dd14`
- Dataset records: 563
- Focused pre-evaluation tests: 45/45 passed
- Pre-evaluation worktree clean: False (existing development changes were preserved)
- Production behavior changed during this evaluation: No
- Uncontrolled external calls: 0

## 2. Dataset preliminary analysis

The verified schema is `id, category, question_en, answer_en, question_twi, answer_twi`. The corpus contains 563 records, 563 unique IDs from 1 to 563, 0 missing IDs, 0 duplicate IDs, and 40 categories. All four question/answer completeness rates are 100%. This is structural corpus analysis, not independent agronomic or professional Twi validation.

## 3. Benchmark design

The benchmark was constructed and written before execution. Direct cases use one deterministic representative (lowest record ID) from every category. English paraphrases have predetermined record IDs. Twi variations are conservative changes around canonical Twi wording and all require human linguistic review. Unsupported topics were verified absent across every dataset field and singular/plural variants.

## 4. Benchmark size and composition

Total: 150 cases.
- Group A — Direct English: 40 cases, 40/40 exact
- Group B — Direct Twi: 40 cases, 40/40 exact
- Group C — English paraphrase: 20 cases, 18/20 exact
- Group D — Twi variation: 20 cases, 20/20 exact
- Group E — Unsupported agriculture: 15 cases
- Group F — Off-topic: 15 cases

## 5. Objective 1 results

- Direct English exact accuracy: 100.0%
- Direct Twi exact accuracy: 100.0%
- English paraphrase exact accuracy: 90.0%
- Twi variation exact accuracy: 100.0%
- Overall supported exact accuracy: 98.333%

These measurements evaluate retrieval correctness, not the scientific correctness of every stored answer.

## 6. Exact-record retrieval results

Exact correctness requires the final record ID to equal the predetermined expected ID. Related records are not silently counted as exact.

## 7. Mismatches awaiting intent-level review

Count: 2. Every mismatch is exported to `mismatch_review.csv` with status `PENDING HUMAN REVIEW`. No automatic intent-level credit was awarded.

- `C4-C-008`: expected record 524; returned 101; route A→A; status `PENDING HUMAN REVIEW`.
- `C4-C-014`: expected record 237; returned no record; route B→D; status `PENDING HUMAN REVIEW`.

Record 524 versus record 101 remains pending even though the returned answer appears related. The tomato paraphrase reached the correct record as the initial top candidate in State B, but the controlled interpretation was conservatively rejected because the salient-term profiles differed (`plenty` versus `tomato`); it therefore ended safely in State D rather than receiving exact-match credit.

## 8. Objective 2 results

- Knowledge-gap detection: 100.0%
- Off-topic rejection: 93.333%
- Generated Gemini agricultural answers: 0
- Weather controlled evaluation: PASS
- TTS functional evaluation: PASS: 10/10 browser tests
- English STT functional evaluation: PASS: 17/17 browser tests; Twi recognition remains disabled
- Twi STT: disabled because reliable browser-native Akan/Twi recognition was not demonstrated

## 9. Gemini controlled evaluation

The deterministic stub was interpretation-only. State A/C bypass behavior, State B eligibility, language/entity preservation, second-pass acceptance, and safe provider-failure handling are covered. The stub cannot generate a final answer; all final agricultural text remained canonical dataset text.

Controlled calls: 20; accepted interpretations: 3; generated agricultural answers: 0. These figures evaluate deterministic routing integration, not live Gemini interpretation quality.

## 10. Gemini live evaluation

**NOT RUN.** The evaluation did not enable live access automatically. To run the existing opt-in micro-test in PowerShell: `$env:RUN_GEMINI_LIVE_TESTS="true"; .\agribot_env\Scripts\python.exe -m unittest -v test_gemini_live.py`. A benchmark live subset is stored in `service_results.json`; a future live run must remain at or below 20 calls.

## 11. State C results

Group F correct State C rate: 93.333%.

- `C4-F-011`: “How should I apologize to my partner after an argument?” ended in State B (low_confidence).

## 12. State D results

Group E correct State D rate: 100.0%; false State A: 0; false State C: 0; generated answers: 0.

## 13. Weather results

Five valid weather intents, four agricultural non-weather questions and three mocked error classes passed their routing expectations. Live Open-Meteo was not run. Provider failure was evaluated as a weather-service error, not a knowledge gap.

## 14. TTS results

Browser tests cover feature detection, listen/pause/resume/stop, history and State D playback, unsupported-browser fallback and accessible controls. Audible Twi pronunciation quality was not objectively measured.

## 15. STT results

English browser-native STT tests cover user initiation, editable transcripts, final/interim handling, duplicate prevention, TTS interaction, cancellation, provider/permission errors and fallback behavior. Twi native browser STT remains disabled and is not claimed as implemented.

## 16. Objective 3 reliability results

- Supported false-rejection rate: 0.833%
- Strong-State exact precision: 99.16%
- High-confidence incorrect State A count: 1
- Language leakage count: 0
- Full Python suite: PASS: 126 tests run, 125 passed, 1 opt-in live Gemini test skipped
- Full browser suite: PASS: 58 tests discovered, 57 passed, 1 opt-in live Open-Meteo test skipped

## 17. Diagnostic tests

17/18 diagnostics passed. See `diagnostic_results.json` and Table 4.9 CSV.

## 18. Robustness checks

7/9 robustness areas passed. Browser evidence is Chromium-based; Edge was not separately measured.

## 19. Response-time statistics

Initial local retrieval: minimum 14.821 ms, mean 22.405 ms, median 18.807 ms, p95 53.142 ms, maximum 72.517 ms. Controlled final pipeline: minimum 15.075 ms, mean 22.997 ms, median 19.292 ms, p95 45.805 ms, maximum 77.069 ms. No external-provider latency is mixed into these statistics.

## 20. Full regression-suite results

{
  "generated_at_utc": "2026-09-01T23:38:00+00:00",
  "full_python": "PASS: 126 tests run, 125 passed, 1 opt-in live Gemini test skipped",
  "full_browser": "PASS: 58 tests discovered, 57 passed, 1 opt-in live Open-Meteo test skipped",
  "retrieval_gemini_focused": "PASS: 24/24",
  "knowledge_gap_suite": "PASS: 8/8",
  "entity_generalization_suite": "PASS: 8/8",
  "off_topic_challenge_suite": "PASS: 3/3 tests; embedded challenge remains 48/48",
  "weather_suite": "PASS: 11/11",
  "tts_suite": "PASS: 10/10 browser tests",
  "stt_suite": "PASS: 17/17 browser tests; Twi recognition remains disabled",
  "javascript_syntax": "PASS: node --check app.js",
  "python_compilation": "PASS: all project Python files",
  "pip_check": "PASS: no broken requirements",
  "npm_dependency_check": "PASS: @playwright/test 1.62.1 and http-server 14.1.1 resolved",
  "git_diff_check": "PASS",
  "live_gemini": "NOT_RUN",
  "live_open_meteo": "NOT_RUN",
  "suite_overlap_notice": "Counts overlap and must not be summed as system accuracy.",
  "evaluation_tooling_note": "The first full Python attempt reported one static-audit false positive because the required evaluation output filename dataset_profile.json was parsed as an alternate production dataset reference. Only the evaluation script's literal construction was adjusted; the required filename, benchmark, frozen application, and measured retrieval results were unchanged. The final full suite then passed."
}

Suites overlap and their counts must not be added together as a system-accuracy statistic.

## 21. Limitations

- No independent agronomic validation was performed.
- Non-canonical Twi variations require human linguistic review.
- Farmer satisfaction, adoption, crop-loss reduction, yield improvement and field effectiveness were not measured.
- Intent-level correctness for exact-record mismatches remains pending human adjudication.
- Live Gemini and live Open-Meteo evaluations were not run.
- Audible speech quality, field noise and real-device microphone accuracy were not measured.
- Browser automation used Chromium; Edge was not separately evaluated.

## 22. Screenshot checklist

- [ ] Main AgriBotGH interface
- [ ] Correct English agricultural answer
- [ ] Correct Twi agricultural answer
- [ ] Gemini-assisted retrieval, if demonstrable
- [ ] Real Open-Meteo weather result
- [ ] State D response and topic buttons
- [ ] State C off-topic response
- [ ] TTS controls
- [ ] English microphone transcript
- [ ] Twi microphone limitation message
- [ ] Mobile layout
- [ ] Dark mode

Mocked weather must not be presented as a live weather screenshot.

## 23. Generated evaluation files

See `generated_files.json` for the machine-readable inventory. These files provide evidence from which Chapter Four can be drafted; they do not constitute the completed chapter.

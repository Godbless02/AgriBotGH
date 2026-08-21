# AgriBotGH

A bilingual (English–Twi) agricultural chatbot for Ghanaian farmers.

## Project Overview

AgriBotGH is a Flask web application that answers farming questions in English and Twi using a validated topic-aware TF-IDF retrieval model and three-state response router.

## System Architecture

```text
Browser UI (HTML/CSS/JavaScript, localStorage history, Web Speech API)
        |
        v
Flask JSON API
        |
        +--> exact canonical/suggestion identity --> verified bilingual answer
        |
        +--> saved English or Twi retrieval artifact
                 |
                 +--> word + character TF-IDF similarity (weight 0.38)
                 +--> training-category centroid relevance (weight 0.62)
                 +--> domain and confidence routing
                         A: answer
                         B: clarification + canonical suggestions
                         C: agricultural-scope recovery path
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
evaluates both languages against the gold standard, and atomically saves a new
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

Browser text-to-speech is manual and never starts automatically. Each bot
message has Play/Pause/Resume and Stop controls, starting another message stops
the previous one, and switching languages cancels active speech. English voices
are selected for English; Twi prefers a browser-provided Twi/Akan voice. When no
such voice exists, the interface explicitly warns that fallback pronunciation
may be inaccurate. Retrieval does not depend on speech support.

The browser regression suite covers the complete responsive matrix at widths
1920, 1440, 1366, 1280, 1024, 768, 480, 390, and 375 pixels. It verifies the
desktop collapsible sidebar, mobile history drawer, quick-question panel,
topics, suggestions, input/send controls, TTS controls, language selector,
history, and absence of horizontal overflow.

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
version 1.0.1 must never be modified in place—future model changes require a new
semantic version and complete evaluation.

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

The final normalized score-margin threshold is `0.27`. Validation measured
100% response precision with approximately 0.60% automatic-answer coverage;
the system deliberately sends uncertain questions to State B. A similarity
score or margin is not described as a probability.

Independent challenges pass 48/48 off-topic cases, 32/32 agricultural edge
cases, 80/80 language-separation cases, and 80/80 presentation cases.

## Python Environment

The application uses Python 3.13.5, recorded in `runtime.txt`. The project
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
The application does not load `.env` files automatically; set these variables
in the shell or deployment dashboard.

## Notes

- The backend exclusively uses `data/agribotgh_dataset_bilingual_563.json`.
- Flask loads the immutable bundle selected by `models/production/active_model.json`; it does not retrain at startup.
- Artifact checksums and the canonical dataset checksum are verified during startup.
- The canonical dataset must be present locally; startup fails clearly if it is missing or invalid.
- There is no database, server-side authentication, email/SMTP, or Paystack
  integration in the current application. User names and chat history are kept
  in browser `localStorage` only.
- The active Python runtime dependencies are Flask, Flask-Cors, scikit-learn,
  NumPy, joblib, and Gunicorn; their versions are pinned in
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
python -m unittest discover -v
npm test
```

## Deployment

`Procfile` starts Gunicorn for deployment. Configure `PORT` in the hosting
environment and keep `FLASK_DEBUG` disabled. The app has no database migration,
SMTP, Paystack, or authentication service requirements. Static frontend files
are served by Flask from the project directory.

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
- Twi speech quality depends on whether the user's browser/operating system
  provides a Twi or Akan voice. The UI discloses fallback pronunciation.
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

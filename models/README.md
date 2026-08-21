# Model Directory

## Production

Only the bundle selected by `production/active_model.json` is loaded by Flask.
Each immutable semantic-version directory contains:

- `english.joblib` and `twi.joblib` — trained retrieval artifacts.
- `retrieval_config.json` — vectorizer, weights, threshold, and router settings.
- `evaluation_summary.json` — measured validation and router results.
- `model_metadata.json` — dataset/split provenance, software versions, source
  hashes, artifact sizes, checksums, metrics, and known limitations.

Build a new bundle with:

```powershell
.\agribot_env\Scripts\python.exe build_retrieval_artifacts.py
```

The builder refuses to overwrite an existing semantic version. Change the
version deliberately before producing a different model. The active manifest
is written only after every file in the new bundle has been created.

Activate or roll back to a checksum-valid existing bundle with:

```powershell
.\agribot_env\Scripts\python.exe activate_model.py 1.0.0
```

The activation manifest is replaced atomically only after the dataset,
configuration, evaluation summary, and both language artifact checksums pass.
Raw `joblib` bytes can differ between builds, so metadata records both a file
checksum for deployed-byte integrity and a deterministic semantic fingerprint
for learned-model reproducibility.

## Experimental and Baseline Files

JSON reports in the root of `models/` are historical evaluation evidence for
TODOs 6–14. `english_model.joblib`, `twi_model.joblib`, and
`validation_data.json` are baseline experiment artifacts and are not loaded by
Flask. Embedding cache directories are local experimental caches and are
ignored by Git.

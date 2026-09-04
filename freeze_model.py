"""Create TODO 32's immutable final-model freeze declaration."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from retrieval_runtime import RetrievalRuntime, sha256_file


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "models" / "production" / "model_freeze.json"
COMPARISON_PATH = BASE_DIR / "models" / "final_model_comparison.json"
DATASET_PATH = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"


def load(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def create_freeze_manifest():
    runtime = RetrievalRuntime(BASE_DIR, DATASET_PATH)
    active = runtime.manifest
    metadata = runtime.metadata
    comparison = load(COMPARISON_PATH)
    config_path = runtime.version_dir / metadata["configuration_file"]
    evaluation_path = runtime.version_dir / metadata["evaluation_file"]
    artifact_files = {
        language: {
            "file": str((runtime.version_dir / summary["file"]).relative_to(BASE_DIR)).replace("\\", "/"),
            "sha256": summary["sha256"],
        }
        for language, summary in metadata["artifacts"].items()
    }
    immutable = {
        "model_id": metadata["model_id"],
        "semantic_version": metadata["semantic_version"],
        "display_version": metadata["model_version"],
        "architecture": metadata["retrieval_architecture"],
        "dataset": metadata["canonical_dataset"],
        "dataset_sha256": metadata["canonical_dataset_sha256"],
        "metadata_file": active["metadata_file"],
        "metadata_sha256": active["metadata_sha256"],
        "configuration_file": str(config_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "configuration_sha256": sha256_file(config_path),
        "evaluation_file": str(evaluation_path.relative_to(BASE_DIR)).replace("\\", "/"),
        "evaluation_sha256": sha256_file(evaluation_path),
        "comparison_file": str(COMPARISON_PATH.relative_to(BASE_DIR)).replace("\\", "/"),
        "comparison_sha256": sha256_file(COMPARISON_PATH),
        "artifacts": artifact_files,
        "selected_architecture": comparison["selection"]["architecture_id"],
        "answer_confidence_threshold": comparison["selection"]["answer_confidence_threshold"],
    }
    freeze_id = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "freeze_schema_version": 1,
        "todo": 32,
        "status": "frozen",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_id": freeze_id,
        **immutable,
        "change_control": (
            "Do not mutate this version. Any model, dataset, configuration, threshold, or artifact "
            "change requires a new semantic version, full evaluation, and a new freeze manifest."
        ),
    }


def write_once(manifest):
    if OUTPUT_PATH.exists():
        existing = load(OUTPUT_PATH)
        if existing.get("freeze_id") == manifest["freeze_id"]:
            print(f"Already frozen with matching freeze ID: {manifest['freeze_id']}")
            return
        if existing.get("semantic_version") == manifest["semantic_version"]:
            raise RuntimeError(
                "A different freeze exists for this semantic version; create a new model version"
            )
        print(
            f"Superseding freeze for immutable v{existing.get('semantic_version')} "
            f"with evaluated v{manifest['semantic_version']}"
        )
    temporary = OUTPUT_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, OUTPUT_PATH)


def main():
    manifest = create_freeze_manifest()
    write_once(manifest)
    print(
        f"Frozen: {manifest['display_version']} ({manifest['architecture']})\n"
        f"Freeze ID: {manifest['freeze_id']}\nFile: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()

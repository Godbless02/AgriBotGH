"""Safely activate an existing versioned AgriBotGH model bundle."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from retrieval_runtime import sha256_file


BASE_DIR = Path(__file__).resolve().parent
PRODUCTION_DIR = BASE_DIR / "models" / "production"
DATA_FILE = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def activate_version(base_dir, production_dir, dataset_file, version):
    base_dir = Path(base_dir).resolve()
    production_dir = Path(production_dir).resolve()
    dataset_file = Path(dataset_file).resolve()
    version_dir = production_dir / version
    metadata_file = version_dir / "model_metadata.json"
    metadata = load_json(metadata_file)
    if metadata.get("semantic_version") != version:
        raise RuntimeError("Requested version does not match model metadata")
    if metadata.get("canonical_dataset_sha256") != sha256_file(dataset_file):
        raise RuntimeError("Model version does not match the canonical dataset")

    supporting_files = (
        (metadata["configuration_file"], metadata["configuration_sha256"]),
        (metadata["evaluation_file"], metadata["evaluation_sha256"]),
    )
    for filename, expected_hash in supporting_files:
        if sha256_file(version_dir / filename) != expected_hash:
            raise RuntimeError(f"Checksum mismatch for {filename}")
    for language, artifact in metadata["artifacts"].items():
        if sha256_file(version_dir / artifact["file"]) != artifact["sha256"]:
            raise RuntimeError(f"Checksum mismatch for {language} artifact")

    try:
        relative_metadata = metadata_file.relative_to(base_dir)
    except ValueError as error:
        raise RuntimeError("Production directory must be inside the project root") from error
    manifest = {
        "manifest_schema_version": 1,
        "active_semantic_version": version,
        "model_version": metadata["model_version"],
        "metadata_file": str(relative_metadata).replace("\\", "/"),
        "metadata_sha256": sha256_file(metadata_file),
        "activated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_file = production_dir / "active_model.json"
    temporary_file = production_dir / ".active_model.json.tmp"
    temporary_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_file.replace(manifest_file)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="Semantic model version to activate")
    args = parser.parse_args()
    manifest = activate_version(BASE_DIR, PRODUCTION_DIR, DATA_FILE, args.version)
    print(
        f"Activated {manifest['model_version']} "
        f"({manifest['active_semantic_version']})"
    )


if __name__ == "__main__":
    main()

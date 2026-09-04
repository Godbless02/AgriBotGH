"""Static project-quality audit used by the final AgriBotGH checks."""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPORT_FILE = ROOT / "models" / "code_quality_report.json"
CANONICAL_DATASET = "data/agribotgh_dataset_bilingual_563.json"
IGNORED_PARTS = {
    ".git",
    "agribot_env",
    "venv",
    "node_modules",
    "Microsoft",
    "backups",
    "test-results",
    "__pycache__",
}
RUNTIME_SUFFIXES = {".py", ".js", ".html", ".css"}
REQUIRED_FILES = {
    "app.py",
    "app.js",
    "index.html",
    "style.css",
    "requirements.txt",
    "Procfile",
    ".python-version",
    "runtime.txt",
    ".env.example",
    CANONICAL_DATASET,
    "models/production/active_model.json",
    "models/production/model_freeze.json",
}


def project_files(suffixes: set[str] | None = None) -> list[Path]:
    files = []
    for directory, names, filenames in os.walk(ROOT):
        names[:] = [name for name in names if name not in IGNORED_PARTS]
        for filename in filenames:
            path = Path(directory) / filename
            if suffixes is None or path.suffix.lower() in suffixes:
                files.append(path)
    return sorted(files)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def duplicate_python_definitions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = names.get(node.name, 0) + 1
    return sorted(name for name, count in names.items() if count > 1)


def duplicate_javascript_functions(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    names = re.findall(r"(?m)^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text)
    return sorted({name for name in names if names.count(name) > 1})


def audit_code_quality(write_report: bool = True) -> dict:
    syntax_errors = []
    duplicate_definitions = []
    for path in project_files({".py"}):
        try:
            duplicates = duplicate_python_definitions(path)
        except (SyntaxError, UnicodeError) as exc:
            syntax_errors.append({"file": relative(path), "error": str(exc)})
            continue
        if duplicates:
            duplicate_definitions.append({"file": relative(path), "names": duplicates})

    for path in project_files({".js"}):
        duplicates = duplicate_javascript_functions(path)
        if duplicates:
            duplicate_definitions.append({"file": relative(path), "names": duplicates})

    missing_files = sorted(name for name in REQUIRED_FILES if not (ROOT / name).is_file())

    dataset_references = []
    canonical_references = []
    for path in project_files(RUNTIME_SUFFIXES):
        text = path.read_text(encoding="utf-8-sig")
        if CANONICAL_DATASET in text:
            canonical_references.append(relative(path))
        for match in re.finditer(r"[\w./\\-]*dataset[\w./\\-]*\.(?:json|txt)", text, re.I):
            value = match.group(0).replace("\\", "/").lstrip("./")
            if value.endswith("agribotgh_dataset_bilingual_563.json"):
                continue
            if Path(value).name in {"dataset_validation.json", "dataset_quality_report.json"}:
                continue
            dataset_references.append({"file": relative(path), "reference": value})

    secret_findings = []
    secret_patterns = (
        re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{12,}"),
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|password|token)\s*[:=]\s*['\"][^'\"${}<\s]{8,}"
        ),
    )
    for path in project_files(RUNTIME_SUFFIXES):
        text = path.read_text(encoding="utf-8-sig")
        if any(pattern.search(text) for pattern in secret_patterns):
            secret_findings.append(relative(path))

    app_text = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    requirements = {
        line.split("==", 1)[0].lower()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    dependency_checks = {
        "flask_declared": "flask" in requirements,
        "unnecessary_flask_cors_removed": "flask-cors" not in requirements
        and "flask_cors" not in app_text,
        "numpy_declared": "numpy" in requirements,
        "scikit_learn_declared": "scikit-learn" in requirements,
        "joblib_declared": "joblib" in requirements,
        "gunicorn_declared": "gunicorn" in requirements,
        "optional_fastembed_not_in_production": "fastembed" not in requirements,
    }
    configuration_checks = {
        "canonical_dataset_used_by_app": "agribotgh_dataset_bilingual_563.json" in app_text,
        "debug_disabled_by_default": "FLASK_DEBUG=false" in (ROOT / ".env.example").read_text(),
        "production_startup_declared": (ROOT / "Procfile").read_text().strip() == "web: gunicorn app:app",
        "render_python_version_declared": (ROOT / ".python-version").read_text().strip() == "3.13.5",
        "model_freeze_enforced": "load_final_model_freeze" in app_text,
    }

    checks = {
        "python_syntax": not syntax_errors,
        "no_duplicate_top_level_definitions": not duplicate_definitions,
        "required_files_present": not missing_files,
        "no_noncanonical_dataset_references": not dataset_references,
        "canonical_dataset_referenced": bool(canonical_references),
        "no_hardcoded_secret_patterns": not secret_findings,
        "dependencies_complete": all(dependency_checks.values()),
        "configuration_safe": all(configuration_checks.values()),
    }
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "details": {
            "python_files_checked": len(project_files({".py"})),
            "runtime_files_checked": len(project_files(RUNTIME_SUFFIXES)),
            "syntax_errors": syntax_errors,
            "duplicate_definitions": duplicate_definitions,
            "missing_files": missing_files,
            "noncanonical_dataset_references": dataset_references,
            "canonical_dataset_references": canonical_references,
            "hardcoded_secret_findings": secret_findings,
            "dependency_checks": dependency_checks,
            "configuration_checks": configuration_checks,
            "not_in_project_scope": [
                "authentication",
                "database persistence",
                "email/SMTP",
                "Paystack payments",
            ],
        },
    }
    if write_report:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = audit_code_quality()
    print(f"Code-quality audit: {result['status']}")
    print(f"Report: {REPORT_FILE}")
    raise SystemExit(0 if result["status"] == "pass" else 1)

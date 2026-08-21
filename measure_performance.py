"""Measure TODO 34 startup, retrieval, API latency, and process memory."""

from __future__ import annotations

import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "models" / "performance_results.json"
LIMITS = {
    "cold_start_seconds": 20.0,
    "retrieval_p95_ms": 100.0,
    "api_p95_ms": 200.0,
    "working_set_mb": 600.0,
}


def percentile(values, percentile_value):
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile_value)))
    return ordered[position]


def summarize_ms(values):
    return {
        "samples": len(values),
        "minimum_ms": round(min(values), 3),
        "average_ms": round(statistics.fmean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "maximum_ms": round(max(values), 3),
    }


def working_set_mb():
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        get_process_memory.restype = ctypes.c_int
        handle = get_current_process()
        if not get_process_memory(
            handle, ctypes.byref(counters), counters.cb
        ):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.WorkingSetSize / (1024 * 1024)

    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 if sys.platform != "darwin" else 1024 * 1024
    return usage / divisor


def measure_cold_start():
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", "import app; assert app.FINAL_MODEL_FREEZE['status'] == 'frozen'"],
        cwd=BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    elapsed = time.perf_counter() - started
    return elapsed, completed.returncode, completed.stderr[-1000:]


def measure_performance():
    cold_start, start_code, start_error = measure_cold_start()
    sample_records = agribot.CANONICAL_RECORDS[::11][:50]
    retrieval_times = []
    for repeat in range(2):
        for record in sample_records:
            code = "tw" if (record["id"] + repeat) % 2 else "en"
            field = "question_twi" if code == "tw" else "question_en"
            started = time.perf_counter()
            agribot.RETRIEVAL_RUNTIME.retrieve(record[field] + " details", code)
            retrieval_times.append((time.perf_counter() - started) * 1000)

    client = agribot.app.test_client()
    api_questions = [
        ("en", agribot.CANONICAL_RECORDS[0]["question_en"]),
        ("tw", agribot.CANONICAL_RECORDS[0]["question_twi"]),
        ("en", "My maize leaves are changing colour and I am not sure why"),
        ("tw", "Akokɔ mma ayare"),
        ("en", "Who won the football match last night?"),
        ("tw", "Hena na odii bɔɔlbɔ no mu nkonim anadwo no?"),
    ]
    api_times = []
    statuses = []
    for _ in range(10):
        for code, question in api_questions:
            started = time.perf_counter()
            response = client.post("/api/chat", json={"message": question, "language": code})
            api_times.append((time.perf_counter() - started) * 1000)
            statuses.append(response.status_code)

    retrieval = summarize_ms(retrieval_times)
    api = summarize_ms(api_times)
    memory = round(working_set_mb(), 2)
    checks = {
        "cold_start": start_code == 0 and cold_start <= LIMITS["cold_start_seconds"],
        "retrieval_latency": retrieval["p95_ms"] <= LIMITS["retrieval_p95_ms"],
        "api_latency": api["p95_ms"] <= LIMITS["api_p95_ms"],
        "working_set": memory <= LIMITS["working_set_mb"],
        "api_statuses": all(status == 200 for status in statuses),
    }
    return {
        "schema_version": 1,
        "todo": 34,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "model": agribot.RETRIEVAL_RUNTIME.metadata["model_version"],
            "training_records_per_language": 394,
        },
        "cold_start": {
            "seconds": round(cold_start, 3),
            "exit_code": start_code,
            "stderr_tail": start_error,
        },
        "retrieval_latency": retrieval,
        "flask_test_client_latency": api,
        "memory": {"working_set_mb": memory, "measurement": "current process resident working set"},
        "limits": LIMITS,
        "checks": checks,
        "summary": {"passed": all(checks.values()), "checks_passed": sum(checks.values()), "checks_total": len(checks)},
    }


def main():
    report = measure_performance()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Cold start={report['cold_start']['seconds']:.3f}s; "
        f"retrieval p95={report['retrieval_latency']['p95_ms']:.3f}ms; "
        f"API p95={report['flask_test_client_latency']['p95_ms']:.3f}ms; "
        f"memory={report['memory']['working_set_mb']:.2f}MB"
    )
    print(f"Report: {REPORT_PATH}")
    if not report["summary"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

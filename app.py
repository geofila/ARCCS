from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue

from flask import Flask, Response, jsonify, render_template, request
import openai
from werkzeug.utils import secure_filename

from log_compliance_checker import (
    ProcurementLogComplianceChecker,
    build_default_checker,
)


BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / "settings.json"
DOCUMENT_HISTORY_FILE = BASE_DIR / "history.json"
LOG_OUTPUT_DIR = BASE_DIR / "log_compliance_outputs"
LOG_HISTORY_DIR = LOG_OUTPUT_DIR / "history"
DEFAULT_LOG_REGULATIONS_FILE = BASE_DIR / "extracted_regulations_CELEX.json"
DEFAULT_LOGS_FILE = BASE_DIR / "Example Data/Logs/TED_log_2016-2022_IT.csv"

DEFAULT_SETTINGS = {
    "api_key": "your-api-key-here",
    "model": "gpt-5.2",
    "auto_save_reports": True,
    "max_regulations_to_check": 25,
    "quality_threshold": 40,
}

ALLOWED_EXTENSIONS = {"csv", "json"}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key, value in DEFAULT_SETTINGS.items():
                settings.setdefault(key, value)
            return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def load_document_history():
    if DOCUMENT_HISTORY_FILE.exists():
        try:
            return json.loads(DOCUMENT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_document_history(history):
    DOCUMENT_HISTORY_FILE.write_text(
        json.dumps(history, indent=2, default=str),
        encoding="utf-8",
    )


def add_to_document_history(entry):
    history = load_document_history()
    entry["id"] = len(history) + 1
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    history.insert(0, entry)
    history = history[:50]
    save_document_history(history)
    return entry


def get_current_model():
    settings = load_settings()
    return settings.get("model", "gpt-5.2")


current_settings = load_settings()
openai.api_key = current_settings.get("api_key", "your-api-key-here")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


log_queues = {}


def get_log_queue(session_id="default"):
    if session_id not in log_queues:
        log_queues[session_id] = queue.Queue()
    return log_queues[session_id]


def send_log(message, log_type="info", session_id="default"):
    payload = {"type": log_type, "level": log_type, "message": message}
    get_log_queue(session_id).put(payload)
    print(message)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def make_upload_path(prefix, filename):
    safe_name = secure_filename(filename)
    return BASE_DIR / app.config["UPLOAD_FOLDER"] / f"{prefix}_{safe_name}"


def default_log_regulations_path():
    return app_state.get("log_regulations_path") or str(DEFAULT_LOG_REGULATIONS_FILE)


def default_logs_path():
    return app_state.get("logs_file") or str(DEFAULT_LOGS_FILE)


def summarize_regulations(regulations):
    source_sections = set()
    keywords = set()

    for regulation in regulations:
        if regulation.get("source_section"):
            source_sections.add(str(regulation["source_section"]))
        for keyword in regulation.get("keywords") or []:
            keywords.add(str(keyword))

    return {
        "total_regulations": len(regulations),
        "sections": sorted(source_sections)[:12],
        "keywords": sorted(keywords)[:20],
    }


def build_log_checker(regulations_json_path=None, logs_csv_path=None):
    settings = load_settings()
    return build_default_checker(
        regulations_json_path=str(regulations_json_path or default_log_regulations_path()),
        logs_csv_path=str(logs_csv_path or default_logs_path()),
        model=settings.get("model", "gpt-5.2"),
        default_regulation_limit=settings.get("max_regulations_to_check", 25),
        auto_save_reports=settings.get("auto_save_reports", True),
        output_dir=str(LOG_OUTPUT_DIR),
        api_key=settings.get("api_key"),
    )


def _parse_history_timestamp(value):
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return datetime.fromtimestamp(0, tz=timezone.utc)

    for fmt in ("%Y%m%dT%H%M%SZ",):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def map_status_to_frontend(status_value):
    raw_status = str(status_value or "").strip()
    status = raw_status.upper()
    if status in {"COMPLIANT", "PASS"}:
        return "pass"
    if status in {"NON_COMPLIANT", "FAIL"}:
        return "fail"
    if status in {"INSUFFICIENT_INFORMATION", "INFO"}:
        return "info"
    if status in {"WARNING", "HUMAN_REQUIRED"}:
        return "warning"
    return "warning"


def normalize_result_item(result):
    compliance_status = (
        result.get("compliance_status")
        or result.get("status")
        or "UNKNOWN"
    )
    evidence = result.get("evidence")
    if not evidence:
        evidence_from_logs = result.get("evidence_from_logs") or []
        if isinstance(evidence_from_logs, list):
            evidence = "\n".join(str(item) for item in evidence_from_logs if item)
        else:
            evidence = str(evidence_from_logs or "")

    preview_text = (
        result.get("message")
        or result.get("contradiction_details")
        or result.get("missing_information")
        or result.get("explanation")
        or "No details available."
    )

    if len(preview_text) > 220:
        preview_text = preview_text[:217] + "..."

    confidence = result.get("confidence")
    if confidence is None:
        confidence = result.get("confidence_score")

    normalized = {
        "regulation": (
            result.get("regulation")
            or result.get("regulation_name")
            or result.get("regulation_id")
            or "Unknown Regulation"
        ),
        "regulation_id": result.get("regulation_id", "N/A"),
        "status": map_status_to_frontend(compliance_status),
        "compliance_status": compliance_status,
        "message": preview_text,
        "missing_information": result.get("missing_information"),
        "explanation": result.get("explanation") or result.get("reasoning") or "No explanation available.",
        "contradiction_details": result.get("contradiction_details") or "",
        "evidence": evidence or "",
        "confidence": confidence if confidence is not None else 0,
        "confidence_score": confidence if confidence is not None else 0,
        "domain": result.get("domain") or {},
        "relevant_log_fields": result.get("relevant_log_fields") or [],
        "case_id": result.get("case_id"),
        "raw_data": result,
    }

    if not normalized["contradiction_details"] and normalized["compliance_status"] == "NON_COMPLIANT":
        normalized["contradiction_details"] = normalized["explanation"]

    return normalized


def normalize_document_history_item(item):
    summary = item.get("summary") or {}
    results = [normalize_result_item(result) for result in item.get("results") or []]
    timestamp = item.get("timestamp")

    return {
        "id": f"document-{item.get('id')}",
        "entry_type": "document_compliance",
        "entry_label": "Document Compliance",
        "timestamp": timestamp,
        "model": item.get("model") or "gpt-5.2",
        "source_primary_label": "Regulations",
        "source_primary_name": item.get("regulation_file") or "Unknown",
        "source_secondary_label": "Document",
        "source_secondary_name": item.get("proposal_file") or "Unknown",
        "input_label": None,
        "input_value": None,
        "summary": {
            "total": summary.get("total", len(results)),
            "compliant": summary.get("compliant", 0),
            "non_compliant": summary.get("non_compliant", 0),
            "insufficient_info": summary.get("insufficient_info", 0),
            "human_required": summary.get("human_required", 0),
        },
        "overall_status": item.get("overall_status") or "UNKNOWN",
        "results": results,
        "report_output": item,
        "_source_kind": "document",
        "_source_id": item.get("id"),
        "_sort_timestamp": _parse_history_timestamp(timestamp),
    }


def normalize_log_history_item(report_payload, report_path):
    summary = report_payload.get("summary") or {}
    app_meta = report_payload.get("app_meta") or {}
    save_info = report_payload.get("save_info") or {}
    detailed_results = report_payload.get("detailed_results") or []
    timestamp_raw = save_info.get("saved_at_utc") or app_meta.get("timestamp")
    timestamp = _parse_history_timestamp(timestamp_raw).isoformat()

    return {
        "id": f"log-{Path(report_path).name}",
        "entry_type": "log_compliance",
        "entry_label": "Log Compliance",
        "timestamp": timestamp,
        "model": app_meta.get("model") or get_current_model(),
        "source_primary_label": "Regulations",
        "source_primary_name": app_meta.get("regulation_file") or DEFAULT_LOG_REGULATIONS_FILE.name,
        "source_secondary_label": "Logs CSV",
        "source_secondary_name": app_meta.get("logs_file") or DEFAULT_LOGS_FILE.name,
        "input_label": "Project ID",
        "input_value": summary.get("case_id") or app_meta.get("project_input") or "Unknown",
        "summary": {
            "total": summary.get("total_regulations_checked", len(detailed_results)),
            "compliant": summary.get("compliant", 0),
            "non_compliant": summary.get("non_compliant", 0),
            "insufficient_info": summary.get("insufficient_information", 0),
            "human_required": summary.get("human_required", 0),
        },
        "overall_status": summary.get("overall_status") or "UNKNOWN",
        "results": [normalize_result_item(result) for result in detailed_results],
        "report_output": report_payload,
        "log_row_count": summary.get("log_row_count", 0),
        "_source_kind": "log",
        "_source_path": str(report_path),
        "_sort_timestamp": _parse_history_timestamp(timestamp_raw),
    }


def load_log_history_items():
    items = []

    if not LOG_HISTORY_DIR.exists():
        return items

    for report_path in sorted(LOG_HISTORY_DIR.glob("*.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            items.append(normalize_log_history_item(payload, report_path))
        except Exception:
            continue

    return items


def load_combined_history():
    document_items = [normalize_document_history_item(item) for item in load_document_history()]
    log_items = load_log_history_items()
    combined = document_items + log_items
    combined.sort(key=lambda item: item["_sort_timestamp"], reverse=True)
    return combined


def find_history_item(history_id):
    for item in load_combined_history():
        if item["id"] == history_id:
            return item
    return None


def has_valid_api_key():
    settings = load_settings()
    api_key = settings.get("api_key", "")
    return bool(api_key and api_key != "your-api-key-here" and len(api_key) > 20)


def resolve_case_selection(logs_by_case, project_input):
    value = str(project_input or "").strip()
    if not value:
        raise ValueError("Please provide a project ID / case ID.")

    if value in logs_by_case:
        return value

    matches = sorted(case_id for case_id in logs_by_case if case_id.endswith(value))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple case IDs end with '{value}'. Please enter the exact full project ID."
        )

    raise ValueError(f"Project ID '{value}' was not found in the uploaded CSV.")


app_state = {
    "log_regulations_path": None,
    "logs_file": None,
    "project_input": None,
    "selected_case_id": None,
    "log_case_facts": None,
    "log_report": None,
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream-logs")
def stream_logs():
    def generate():
        q = get_log_queue("default")
        while True:
            try:
                message = q.get(timeout=30)
                yield f"data: {json.dumps(message)}\n\n"
            except queue.Empty:
                keepalive = {"type": "keepalive", "level": "keepalive", "message": ""}
                yield f"data: {json.dumps(keepalive)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/load-log-regulations", methods=["POST"])
def load_log_regulations():
    try:
        if not DEFAULT_LOG_REGULATIONS_FILE.exists():
            return jsonify(
                {
                    "success": False,
                    "message": f"Default regulations file not found: {DEFAULT_LOG_REGULATIONS_FILE.name}",
                }
            ), 404

        send_log("=" * 60)
        send_log("Loading default procurement regulations...")
        regulations = ProcurementLogComplianceChecker.load_regulations(DEFAULT_LOG_REGULATIONS_FILE)
        summary = summarize_regulations(regulations)

        app_state["log_regulations_path"] = str(DEFAULT_LOG_REGULATIONS_FILE)

        send_log(f"Loaded {summary['total_regulations']} regulations.", "success")
        send_log(f"Source sections found: {len(summary['sections'])}")

        return jsonify(
            {
                "success": True,
                "message": "Default regulations loaded successfully.",
                "filename": DEFAULT_LOG_REGULATIONS_FILE.name,
                "features": summary,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/upload-log-regulations", methods=["POST"])
def upload_log_regulations():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file provided."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected."}), 400

    if not allowed_file(file.filename) or file.filename.rsplit(".", 1)[1].lower() != "json":
        return jsonify({"success": False, "message": "Please upload a JSON regulations file."}), 400

    filepath = make_upload_path("regulations", file.filename)
    file.save(filepath)

    try:
        send_log("=" * 60)
        send_log(f"Loading uploaded regulations: {filepath.name}")
        regulations = ProcurementLogComplianceChecker.load_regulations(filepath)
        summary = summarize_regulations(regulations)

        app_state["log_regulations_path"] = str(filepath)

        send_log(f"Loaded {summary['total_regulations']} regulations.", "success")
        return jsonify(
            {
                "success": True,
                "message": "Regulations file uploaded successfully.",
                "filename": file.filename,
                "features": summary,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": f"Failed to load regulations JSON: {exc}"}), 400


@app.route("/upload-log-csv", methods=["POST"])
def upload_log_csv():
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file provided."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "No file selected."}), 400

    if not allowed_file(file.filename) or file.filename.rsplit(".", 1)[1].lower() != "csv":
        return jsonify({"success": False, "message": "Please upload a CSV logs file."}), 400

    filepath = make_upload_path("logs", file.filename)
    file.save(filepath)

    app_state["logs_file"] = str(filepath)

    return jsonify(
        {
            "success": True,
            "message": "Logs CSV uploaded successfully.",
            "filename": file.filename,
        }
    )


@app.route("/process-log-input", methods=["POST"])
def process_log_input():
    try:
        filepath = Path(default_logs_path())
        project_input = (request.json or {}).get("project_id", "")

        if not filepath.exists():
            return jsonify({"success": False, "message": "No logs CSV found. Please upload a file first."}), 400

        send_log("=" * 60)
        send_log(f"Scanning logs CSV: {filepath.name}")
        checker = build_log_checker(logs_csv_path=filepath)
        logs_by_case = checker.logs_by_case
        selected_case_id = resolve_case_selection(logs_by_case, project_input)
        case_rows = checker.get_case_rows(case_id=selected_case_id)
        case_facts = checker.build_case_facts(case_rows)

        app_state["project_input"] = project_input
        app_state["selected_case_id"] = selected_case_id
        app_state["log_case_facts"] = case_facts
        app_state["log_report"] = None

        send_log(f"Selected case_id: {selected_case_id}", "success")
        send_log(f"Rows in selected case: {case_facts['row_count']}")
        send_log(f"Events present: {', '.join(case_facts['events_present']) or 'None'}")

        first_date = next((row.get("timestamp") for row in case_rows if row.get("timestamp")), None)
        last_date = next((row.get("timestamp") for row in reversed(case_rows) if row.get("timestamp")), None)

        return jsonify(
            {
                "success": True,
                "message": "Logs input processed successfully.",
                "data": {
                    "selected_case_id": selected_case_id,
                    "project_input": project_input,
                    "total_cases": len(logs_by_case),
                    "row_count": case_facts["row_count"],
                    "events_present": case_facts["events_present"],
                    "event_count": len(case_facts["events_present"]),
                    "first_date": first_date,
                    "last_date": last_date,
                    "logs_file": filepath.name,
                },
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "message": f"Failed to process logs input: {exc}"}), 500


@app.route("/run-log-compliance-check", methods=["POST"])
def run_log_compliance_check():
    try:
        if not has_valid_api_key():
            return jsonify(
                {
                    "success": False,
                    "message": "Please configure a valid OpenAI API key in Settings before running the analysis.",
                }
            ), 400

        selected_case_id = app_state.get("selected_case_id")
        if not selected_case_id:
            return jsonify(
                {
                    "success": False,
                    "message": "Please upload your logs CSV and process a project ID first.",
                }
            ), 400

        checker = build_log_checker()
        case_rows = checker.get_case_rows(case_id=selected_case_id)
        case_facts = checker.build_case_facts(case_rows)

        settings = load_settings()
        regulations = checker.regulations[: checker.default_regulation_limit]
        results = []

        send_log("=" * 60)
        send_log("Starting procurement log compliance analysis...")
        send_log(f"Regulations file: {Path(default_log_regulations_path()).name}")
        send_log(f"Logs file: {Path(default_logs_path()).name}")
        send_log(f"Selected case_id: {selected_case_id}")
        send_log(f"Rows in case: {case_facts['row_count']}")
        send_log(f"Model: {checker.model}")
        send_log(f"Regulations to check: {len(regulations)}")
        send_log("=" * 60)

        for index, regulation in enumerate(regulations, start=1):
            regulation_name = (
                regulation.get("regulation_name")
                or regulation.get("regulation_id")
                or "Unknown regulation"
            )
            send_log(f"[{index}/{len(regulations)}] Checking {regulation_name[:90]}...")
            result = checker.check_single_regulation(regulation, case_facts)
            results.append(result)

            status = result.get("compliance_status", "UNKNOWN")
            if status == "NON_COMPLIANT":
                send_log("   Status: NON_COMPLIANT", "error")
            elif status == "COMPLIANT":
                send_log("   Status: COMPLIANT", "success")
            elif status == "INSUFFICIENT_INFORMATION":
                send_log("   Status: INSUFFICIENT_INFORMATION", "warning")
            else:
                send_log("   Status: HUMAN_REQUIRED", "warning")

        report = checker.generate_report(case_facts=case_facts, results=results)
        report["summary"]["default_regulation_limit"] = checker.default_regulation_limit
        report["summary"]["effective_regulation_limit"] = len(regulations)
        report["app_meta"] = {
            "entry_type": "log_compliance",
            "logs_file": Path(default_logs_path()).name,
            "regulation_file": Path(default_log_regulations_path()).name,
            "model": checker.model,
            "project_input": app_state.get("project_input"),
            "selected_case_id": selected_case_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if settings.get("auto_save_reports", True):
            save_info = checker.save_report(report=report)
            report["save_info"] = save_info
            send_log("Report saved to history.", "success")

        app_state["log_case_facts"] = case_facts
        app_state["log_report"] = report

        frontend_results = [normalize_result_item(result) for result in results]
        total = report["summary"]["total_regulations_checked"]
        passed = report["summary"]["compliant"]
        failed = report["summary"]["non_compliant"]
        insufficient = report["summary"]["insufficient_information"]
        human_required = report["summary"]["human_required"]
        warnings = insufficient + human_required
        compliance_rate = round((passed / total) * 100, 2) if total else 0

        send_log("")
        send_log("Analysis complete.", "success")
        send_log(f"Compliant: {passed}")
        send_log(f"Non-compliant: {failed}")
        send_log(f"Insufficient information: {insufficient}")
        send_log(f"Human required: {human_required}")

        return jsonify(
            {
                "success": True,
                "message": "Log compliance analysis completed successfully.",
                "results": frontend_results,
                "summary": {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "insufficient_info": insufficient,
                    "human_required": human_required,
                    "warnings": warnings,
                    "compliance_rate": compliance_rate,
                },
                "overall_status": report["summary"]["overall_status"],
                "case_facts": case_facts,
                "report_output": report,
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "message": f"Error during log compliance analysis: {exc}"}), 500


@app.route("/export-report", methods=["GET"])
def export_report():
    report = app_state.get("log_report")
    if not report:
        return jsonify({"success": False, "message": "No log analysis report available yet."}), 400

    return jsonify({"success": True, "report": report})


@app.route("/reset", methods=["POST"])
def reset_state():
    global app_state
    app_state = {
        "log_regulations_path": None,
        "logs_file": None,
        "project_input": None,
        "selected_case_id": None,
        "log_case_facts": None,
        "log_report": None,
    }
    return jsonify({"success": True, "message": "State reset successfully."})


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/api/settings", methods=["GET"])
def get_settings():
    settings = load_settings()
    api_key = settings.get("api_key", "")
    settings["api_key_set"] = bool(api_key and api_key != "your-api-key-here" and len(api_key) > 20)
    settings["api_key_preview"] = api_key[:8] + "..." + api_key[-4:] if settings["api_key_set"] else ""
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
def update_settings():
    global current_settings
    try:
        data = request.json or {}
        settings = load_settings()

        if data.get("api_key"):
            settings["api_key"] = data["api_key"]
            openai.api_key = data["api_key"]
        if "model" in data:
            settings["model"] = data["model"]
        if "auto_save_reports" in data:
            settings["auto_save_reports"] = data["auto_save_reports"]
        if "max_regulations_to_check" in data:
            settings["max_regulations_to_check"] = int(data["max_regulations_to_check"])
        if "quality_threshold" in data:
            settings["quality_threshold"] = int(data["quality_threshold"])

        save_settings(settings)
        current_settings = settings

        return jsonify({"success": True, "message": "Settings saved successfully."})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@app.route("/api/settings/check-api-key", methods=["GET"])
def check_api_key():
    valid = has_valid_api_key()
    return jsonify(
        {
            "has_api_key": valid,
            "valid": valid,
            "message": "API key is set" if valid else "Please configure your OpenAI API key in Settings",
        }
    )


@app.route("/api/history", methods=["GET"])
def get_history():
    history = load_combined_history()

    response = []
    for item in history:
        entry = {key: value for key, value in item.items() if not key.startswith("_")}
        response.append(entry)

    return jsonify(response)


@app.route("/api/history/<history_id>", methods=["GET"])
def get_history_item(history_id):
    item = find_history_item(history_id)
    if not item:
        return jsonify({"error": "Not found"}), 404

    return jsonify({key: value for key, value in item.items() if not key.startswith("_")})


@app.route("/api/history/<history_id>", methods=["DELETE"])
def delete_history_item(history_id):
    item = find_history_item(history_id)
    if not item:
        return jsonify({"success": False, "message": "History item not found."}), 404

    if item.get("_source_kind") == "document":
        source_id = item.get("_source_id")
        history = [entry for entry in load_document_history() if entry.get("id") != source_id]
        save_document_history(history)
    elif item.get("_source_kind") == "log":
        source_path = item.get("_source_path")
        if source_path and Path(source_path).exists():
            Path(source_path).unlink()

    return jsonify({"success": True})


@app.route("/api/history/clear", methods=["POST"])
def clear_history():
    save_document_history([])

    if LOG_HISTORY_DIR.exists():
        for file_path in LOG_HISTORY_DIR.glob("*.json"):
            try:
                file_path.unlink()
            except Exception:
                continue

    return jsonify({"success": True, "message": "History cleared."})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

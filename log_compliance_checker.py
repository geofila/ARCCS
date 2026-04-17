"""
LLM-first compliance checker for procurement logs.

This module reads:
- extracted regulations from a JSON file
- procurement logs from a CSV file

It then:
1. isolates one procurement case by exact case_id or by suffix selection,
2. builds a compact logs-only context for that case,
3. sends each extracted regulation, one by one, to an LLM,
4. gets back one of:
   - COMPLIANT
   - NON_COMPLIANT
   - HUMAN_REQUIRED
   - INSUFFICIENT_INFORMATION
5. returns a report with totals and detailed per-regulation results.

This file is standalone and does not require changes to the other project
modules.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import openai as openai_legacy
except Exception:
    openai_legacy = None


VALID_STATUSES = {
    "COMPLIANT",
    "NON_COMPLIANT",
    "HUMAN_REQUIRED",
    "INSUFFICIENT_INFORMATION",
}

EVENT_ORDER = {
    "PUBLICATION": 1,
    "PARTICIPATION": 2,
    "AWARD": 3,
    "CONTRACT-START": 4,
    "CONTRACT-END": 5,
}


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _dedupe_preserve_order(values: List[Any]) -> List[Any]:
    seen = set()
    output = []
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        output.append(value)
    return output


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    if status in VALID_STATUSES:
        return status
    return "HUMAN_REQUIRED"


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _timeline_line(row: Dict[str, Any]) -> str:
    return (
        f"{row.get('timestamp') or 'UNKNOWN_DATE'} | "
        f"{row.get('event') or 'UNKNOWN_EVENT'} | "
        f"amount={row.get('amount') or 'NA'} | "
        f"t_type={row.get('t_type') or 'NA'} | "
        f"electronic={row.get('electronic') or 'NA'} | "
        f"framework_agr={row.get('framework_agr') or 'NA'} | "
        f"country={row.get('country') or 'NA'} | "
        f"nuts={row.get('nuts') or 'NA'} | "
        f"cpv_division={row.get('cpv_division') or 'NA'} | "
        f"cpv={row.get('cpv') or 'NA'} | "
        f"case_len={row.get('case_len') or 'NA'}"
    )


class ProcurementLogLLMComplianceChecker:
    def __init__(
        self,
        regulations_json_path: str,
        logs_csv_path: str,
        model: str = "gpt-5.2",
        default_regulation_limit: int = 20,
        auto_save_reports: bool = True,
        output_dir: str = "log_compliance_outputs",
        api_key: Optional[str] = None,
    ) -> None:
        self.regulations_json_path = Path(regulations_json_path)
        self.logs_csv_path = Path(logs_csv_path)
        self.model = model
        self.default_regulation_limit = default_regulation_limit
        self.auto_save_reports = auto_save_reports
        self.output_dir = Path(output_dir)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        self.regulations = self.load_regulations(self.regulations_json_path)
        self.log_rows = self.load_logs(self.logs_csv_path)
        self.logs_by_case = self.group_logs_by_case(self.log_rows)

    @staticmethod
    def _detect_csv_delimiter(csv_path: Path) -> str:
        first_line = csv_path.read_text(encoding="utf-8-sig").splitlines()[0]
        return ";" if first_line.count(";") >= first_line.count(",") else ","

    @staticmethod
    def load_regulations(regulations_json_path: Path) -> List[Dict[str, Any]]:
        payload = json.loads(regulations_json_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if "regulations" in payload and isinstance(payload["regulations"], list):
                return payload["regulations"]
            if "results" in payload and isinstance(payload["results"], list):
                return payload["results"]
        if isinstance(payload, list):
            return payload
        raise ValueError(f"Unsupported regulations JSON structure in {regulations_json_path}")

    @classmethod
    def load_logs(cls, logs_csv_path: Path) -> List[Dict[str, Any]]:
        delimiter = cls._detect_csv_delimiter(logs_csv_path)
        rows: List[Dict[str, Any]] = []

        with logs_csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            for raw_row in reader:
                row = {
                    str(key).strip(): (str(value).strip() if value is not None else "")
                    for key, value in raw_row.items()
                }
                rows.append(row)

        return rows

    @staticmethod
    def group_logs_by_case(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["case_id"]].append(row)
        return grouped

    def select_case_id(
        self,
        case_id: Optional[str] = None,
        case_id_suffix: Optional[str] = None,
        pick: str = "first",
    ) -> str:
        if case_id:
            if case_id not in self.logs_by_case:
                raise ValueError(f"case_id '{case_id}' was not found in the logs CSV.")
            return case_id

        if not case_id_suffix:
            raise ValueError("You must provide either case_id or case_id_suffix.")

        matches = sorted(
            current_case_id
            for current_case_id in self.logs_by_case
            if current_case_id.endswith(str(case_id_suffix))
        )

        if not matches:
            raise ValueError(f"No case_id found ending with suffix '{case_id_suffix}'.")

        if pick == "last":
            return matches[-1]
        return matches[0]

    def get_case_rows(
        self,
        case_id: Optional[str] = None,
        case_id_suffix: Optional[str] = None,
        pick: str = "first",
    ) -> List[Dict[str, Any]]:
        selected_case_id = self.select_case_id(
            case_id=case_id,
            case_id_suffix=case_id_suffix,
            pick=pick,
        )
        rows = deepcopy(self.logs_by_case[selected_case_id])
        rows.sort(
            key=lambda row: (
                row.get("timestamp") or "",
                EVENT_ORDER.get(row.get("event"), 99),
                row.get("event") or "",
            )
        )
        return rows

    @staticmethod
    def build_case_facts(case_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not case_rows:
            raise ValueError("Cannot build case facts from an empty list of log rows.")

        event_counts = Counter(row.get("event") for row in case_rows)
        amount_values = _dedupe_preserve_order(
            [
                amount
                for amount in (_safe_float(row.get("amount")) for row in case_rows)
                if amount is not None
            ]
        )
        case_len_values = _dedupe_preserve_order(
            [
                case_len
                for case_len in (_safe_int(row.get("case_len")) for row in case_rows)
                if case_len is not None
            ]
        )

        rows_by_event: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in case_rows:
            rows_by_event[row.get("event")].append(row)

        facts = {
            "case_id": case_rows[0]["case_id"],
            "row_count": len(case_rows),
            "timeline": [_timeline_line(row) for row in case_rows],
            "event_counts": dict(event_counts),
            "events_present": sorted(event_counts.keys()),
            "publication_count": event_counts.get("PUBLICATION", 0),
            "participation_count": event_counts.get("PARTICIPATION", 0),
            "award_count": event_counts.get("AWARD", 0),
            "contract_start_count": event_counts.get("CONTRACT-START", 0),
            "contract_end_count": event_counts.get("CONTRACT-END", 0),
            "amount_values": amount_values,
            "case_len_values": case_len_values,
            "first_publication_date": _safe_date(rows_by_event["PUBLICATION"][0]["timestamp"]) if rows_by_event["PUBLICATION"] else None,
            "first_participation_date": _safe_date(rows_by_event["PARTICIPATION"][0]["timestamp"]) if rows_by_event["PARTICIPATION"] else None,
            "first_award_date": _safe_date(rows_by_event["AWARD"][0]["timestamp"]) if rows_by_event["AWARD"] else None,
            "first_contract_start_date": _safe_date(rows_by_event["CONTRACT-START"][0]["timestamp"]) if rows_by_event["CONTRACT-START"] else None,
            "first_contract_end_date": _safe_date(rows_by_event["CONTRACT-END"][0]["timestamp"]) if rows_by_event["CONTRACT-END"] else None,
            "t_type_values": _dedupe_preserve_order([row.get("t_type") for row in case_rows if row.get("t_type")]),
            "electronic_values": _dedupe_preserve_order([row.get("electronic") for row in case_rows if row.get("electronic")]),
            "framework_agr_values": _dedupe_preserve_order([row.get("framework_agr") for row in case_rows if row.get("framework_agr")]),
            "country_values": _dedupe_preserve_order([row.get("country") for row in case_rows if row.get("country")]),
            "nuts_values": _dedupe_preserve_order([row.get("nuts") for row in case_rows if row.get("nuts")]),
            "cpv_division_values": _dedupe_preserve_order([row.get("cpv_division") for row in case_rows if row.get("cpv_division")]),
            "cpv_values": _dedupe_preserve_order([row.get("cpv") for row in case_rows if row.get("cpv")]),
            "raw_rows": case_rows,
        }

        return facts

    def _llm_available(self) -> bool:
        return bool(self.api_key and (OpenAI is not None or openai_legacy is not None))

    def _make_client(self):
        if OpenAI is not None:
            return OpenAI(api_key=self.api_key)
        return None

    def _chat_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self._llm_available():
            raise RuntimeError(
                "LLM evaluation requires an OpenAI client and OPENAI_API_KEY."
            )

        if OpenAI is not None:
            client = self._make_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)

        response = openai_legacy.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            api_key=self.api_key,
        )
        return json.loads(response.choices[0].message.content)

    @staticmethod
    def _build_system_prompt() -> str:
        return (
            "You are a legal-procurement compliance analyst.\n"
            "You evaluate ONE extracted regulation against ONE procurement case log.\n\n"
            "CRITICAL RULES:\n"
            "1. Use ONLY the regulation data and the selected case log provided.\n"
            "2. Do NOT use terms of use, external websites, external legal assumptions, or unstated facts.\n"
            "3. The selected case rows are the full log for that exact case_id.\n"
            "4. Repeated rows with the same case_id belong to the same procurement case.\n"
            "5. If the logs contain enough information to assess the regulation and the logs conflict with it, return NON_COMPLIANT.\n"
            "6. If the logs contain enough information to assess the regulation and no conflict exists, return COMPLIANT.\n"
            "7. If key information required by the regulation is missing from the available logs, return INSUFFICIENT_INFORMATION.\n"
            "8. Use HUMAN_REQUIRED only when the logs are materially relevant but the decision is still genuinely ambiguous or unsafe.\n"
            "9. Be conservative with COMPLIANT: choose it only when the logs are actually sufficient.\n"
            "10. The explanation must be detailed and explicit: say what the regulation requires, what the logs show, and why that leads to the chosen status.\n"
            "11. Return valid JSON only."
        )

    @staticmethod
    def _build_user_prompt(regulation: Dict[str, Any], case_facts: Dict[str, Any]) -> str:
        regulation_payload = {
            "regulation_id": regulation.get("regulation_id"),
            "regulation_name": regulation.get("regulation_name"),
            "regulation_type": regulation.get("regulation_type"),
            "description": regulation.get("description"),
            "requirements": regulation.get("requirements"),
            "restrictions": regulation.get("restrictions"),
            "compliance_requirements": regulation.get("compliance_requirements"),
            "dates": regulation.get("dates"),
            "keywords": regulation.get("keywords"),
            "source_section": regulation.get("source_section"),
        }

        case_summary = {
            "case_id": case_facts["case_id"],
            "row_count": case_facts["row_count"],
            "event_counts": case_facts["event_counts"],
            "events_present": case_facts["events_present"],
            "publication_count": case_facts["publication_count"],
            "participation_count": case_facts["participation_count"],
            "award_count": case_facts["award_count"],
            "contract_start_count": case_facts["contract_start_count"],
            "contract_end_count": case_facts["contract_end_count"],
            "amount_values": case_facts["amount_values"],
            "case_len_values": case_facts["case_len_values"],
            "first_publication_date": case_facts["first_publication_date"],
            "first_participation_date": case_facts["first_participation_date"],
            "first_award_date": case_facts["first_award_date"],
            "first_contract_start_date": case_facts["first_contract_start_date"],
            "first_contract_end_date": case_facts["first_contract_end_date"],
            "t_type_values": case_facts["t_type_values"],
            "electronic_values": case_facts["electronic_values"],
            "framework_agr_values": case_facts["framework_agr_values"],
            "country_values": case_facts["country_values"],
            "nuts_values": case_facts["nuts_values"],
            "cpv_division_values": case_facts["cpv_division_values"],
            "cpv_values": case_facts["cpv_values"],
        }

        return f"""
REGULATION TO ASSESS:
{_json_dump(regulation_payload)}

AVAILABLE LOG FIELDS:
- case_id
- event
- timestamp
- t_type
- amount
- electronic
- framework_agr
- nuts
- country
- cpv_division
- cpv
- case_len

SELECTED CASE SUMMARY:
{_json_dump(case_summary)}

SELECTED CASE TIMELINE:
{chr(10).join("- " + line for line in case_facts["timeline"])}

SELECTED RAW CASE ROWS:
{_json_dump(case_facts["raw_rows"])}

Return JSON with this exact shape:
{{
  "compliance_status": "COMPLIANT | NON_COMPLIANT | HUMAN_REQUIRED | INSUFFICIENT_INFORMATION",
  "has_sufficient_information": true,
  "conflict_found": false,
  "relevant_log_fields": ["field1", "field2"],
  "evidence_from_logs": ["short evidence string 1", "short evidence string 2"],
  "missing_information": null,
  "explanation": "Detailed explanation based only on the logs and this regulation. Explain what the regulation requires, what the logs contain, and why the case is compliant, non-compliant, human-required, or insufficient-information.",
  "confidence_score": 0.0
}}
"""

    def check_single_regulation(
        self,
        regulation: Dict[str, Any],
        case_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(regulation, case_facts)

        try:
            llm_result = self._chat_json(system_prompt, user_prompt)
        except Exception as exc:
            return {
                "regulation_id": regulation.get("regulation_id"),
                "regulation_name": regulation.get("regulation_name"),
                "source_section": regulation.get("source_section"),
                "case_id": case_facts["case_id"],
                "evaluation_mode": "llm_error",
                "compliance_status": "HUMAN_REQUIRED",
                "has_sufficient_information": False,
                "conflict_found": False,
                "relevant_log_fields": [],
                "evidence_from_logs": [],
                "missing_information": None,
                "confidence_score": 0.0,
                "explanation": f"LLM evaluation failed: {exc}",
                "reasoning": f"LLM evaluation failed: {exc}",
            }

        evidence = llm_result.get("evidence_from_logs") or []
        if isinstance(evidence, str):
            evidence = [evidence]

        relevant_log_fields = llm_result.get("relevant_log_fields") or []
        if isinstance(relevant_log_fields, str):
            relevant_log_fields = [relevant_log_fields]

        status = _normalize_status(llm_result.get("compliance_status"))
        has_sufficient_information = llm_result.get("has_sufficient_information")
        if not isinstance(has_sufficient_information, bool):
            has_sufficient_information = status != "INSUFFICIENT_INFORMATION"

        conflict_found = llm_result.get("conflict_found")
        if not isinstance(conflict_found, bool):
            conflict_found = status == "NON_COMPLIANT"

        missing_information = llm_result.get("missing_information")
        if status != "INSUFFICIENT_INFORMATION":
            missing_information = None

        explanation = str(
            llm_result.get("explanation")
            or llm_result.get("reasoning")
            or ""
        ).strip()
        if not explanation:
            explanation = "No explanation returned by the model."

        return {
            "regulation_id": regulation.get("regulation_id"),
            "regulation_name": regulation.get("regulation_name"),
            "source_section": regulation.get("source_section"),
            "case_id": case_facts["case_id"],
            "evaluation_mode": "llm",
            "compliance_status": status,
            "has_sufficient_information": has_sufficient_information,
            "conflict_found": conflict_found,
            "relevant_log_fields": _dedupe_preserve_order([str(x) for x in relevant_log_fields]),
            "evidence_from_logs": _dedupe_preserve_order([str(x) for x in evidence]),
            "missing_information": missing_information,
            "confidence_score": _clamp_confidence(llm_result.get("confidence_score")),
            "explanation": explanation,
            "reasoning": explanation,
        }

    def check_case(
        self,
        case_id: Optional[str] = None,
        case_id_suffix: Optional[str] = None,
        pick: str = "first",
        limit: Optional[int] = None,
        save: Optional[bool] = None,
        output_path: Optional[str] = None,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        case_rows = self.get_case_rows(
            case_id=case_id,
            case_id_suffix=case_id_suffix,
            pick=pick,
        )
        case_facts = self.build_case_facts(case_rows)

        effective_limit = self.default_regulation_limit if limit is None else limit
        regulations = self.regulations[:effective_limit] if effective_limit else self.regulations
        results: List[Dict[str, Any]] = []

        if verbose:
            print(
                f"Checking case_id={case_facts['case_id']} against {len(regulations)} regulations "
                f"(default_limit={self.default_regulation_limit})..."
            )

        for index, regulation in enumerate(regulations, start=1):
            if verbose:
                reg_name = regulation.get("regulation_name") or regulation.get("regulation_id") or "Unknown regulation"
                print(f"[{index}/{len(regulations)}] {reg_name[:90]}")
            result = self.check_single_regulation(regulation, case_facts)
            results.append(result)
            if verbose:
                print(f"   -> {result['compliance_status']}")

        report = self.generate_report(case_facts=case_facts, results=results)
        report["summary"]["default_regulation_limit"] = self.default_regulation_limit
        report["summary"]["effective_regulation_limit"] = effective_limit
        save_enabled = self.auto_save_reports if save is None else save
        if save_enabled:
            save_info = self.save_report(
                report=report,
                output_path=output_path,
            )
            report["save_info"] = save_info
        return report

    @staticmethod
    def generate_report(case_facts: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
        status_counts = Counter(result.get("compliance_status", "UNKNOWN") for result in results)

        if status_counts.get("NON_COMPLIANT", 0) > 0:
            overall_status = "NON_COMPLIANT"
        elif status_counts.get("HUMAN_REQUIRED", 0) > 0:
            overall_status = "HUMAN_REQUIRED"
        elif status_counts.get("COMPLIANT", 0) == len(results):
            overall_status = "COMPLIANT"
        elif status_counts.get("INSUFFICIENT_INFORMATION", 0) == len(results):
            overall_status = "INSUFFICIENT_INFORMATION"
        else:
            overall_status = "PARTIAL"

        summary = {
            "case_id": case_facts["case_id"],
            "log_row_count": case_facts["row_count"],
            "total_regulations_checked": len(results),
            "compliant": status_counts.get("COMPLIANT", 0),
            "non_compliant": status_counts.get("NON_COMPLIANT", 0),
            "human_required": status_counts.get("HUMAN_REQUIRED", 0),
            "insufficient_information": status_counts.get("INSUFFICIENT_INFORMATION", 0),
            "overall_status": overall_status,
        }

        return {
            "summary": summary,
            "case_facts": case_facts,
            "violations": [result for result in results if result.get("compliance_status") == "NON_COMPLIANT"],
            "human_required_items": [result for result in results if result.get("compliance_status") == "HUMAN_REQUIRED"],
            "insufficient_information_items": [
                result for result in results if result.get("compliance_status") == "INSUFFICIENT_INFORMATION"
            ],
            "detailed_results": results,
        }

    def _build_report_paths(
        self,
        case_id: str,
        output_path: Optional[str] = None,
    ) -> Dict[str, str]:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        if output_path:
            latest_path = Path(output_path)
            history_dir = latest_path.parent / "history"
            history_path = history_dir / f"{latest_path.stem}_{timestamp}{latest_path.suffix or '.json'}"
        else:
            base_dir = self.output_dir
            history_dir = base_dir / "history"
            latest_path = base_dir / f"case_{case_id}_latest.json"
            history_path = history_dir / f"case_{case_id}_{timestamp}.json"

        return {
            "latest_path": str(latest_path),
            "history_path": str(history_path),
            "saved_at_utc": timestamp,
        }

    def save_report(
        self,
        report: Dict[str, Any],
        output_path: Optional[str] = None,
    ) -> Dict[str, str]:
        case_id = str(report.get("summary", {}).get("case_id") or report.get("case_facts", {}).get("case_id") or "unknown_case")
        paths = self._build_report_paths(case_id=case_id, output_path=output_path)

        latest_path = Path(paths["latest_path"])
        history_path = Path(paths["history_path"])

        latest_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.parent.mkdir(parents=True, exist_ok=True)

        payload = deepcopy(report)
        payload["save_info"] = {
            "case_id": case_id,
            "latest_path": str(latest_path),
            "history_path": str(history_path),
            "saved_at_utc": paths["saved_at_utc"],
        }

        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        latest_path.write_text(serialized, encoding="utf-8")
        history_path.write_text(serialized, encoding="utf-8")

        return payload["save_info"]


ProcurementLogComplianceChecker = ProcurementLogLLMComplianceChecker


def build_default_checker(
    regulations_json_path: str = "extracted_regulations_CELEX.json",
    logs_csv_path: str = "Example Data/Logs/TED_log_2016-2022_IT.csv",
    model: str = "gpt-5.2",
    default_regulation_limit: int = 20,
    auto_save_reports: bool = True,
    output_dir: str = "log_compliance_outputs",
    api_key: Optional[str] = None,
) -> ProcurementLogLLMComplianceChecker:
    return ProcurementLogLLMComplianceChecker(
        regulations_json_path=regulations_json_path,
        logs_csv_path=logs_csv_path,
        model=model,
        default_regulation_limit=default_regulation_limit,
        auto_save_reports=auto_save_reports,
        output_dir=output_dir,
        api_key=api_key,
    )


def _cli() -> None:
    parser = argparse.ArgumentParser(description="LLM-first compliance checking against procurement logs.")
    parser.add_argument(
        "--regulations-json",
        default="extracted_regulations_CELEX.json",
        help="Path to the extracted regulations JSON.",
    )
    parser.add_argument(
        "--logs-csv",
        default="Example Data/Logs/TED_log_2016-2022_IT.csv",
        help="Path to the procurement logs CSV.",
    )

    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--case-id", help="Exact case_id to evaluate.")
    selector.add_argument(
        "--case-id-suffix",
        help="Select the first/last case_id ending with this suffix, e.g. 45.",
    )

    parser.add_argument(
        "--pick",
        choices=["first", "last"],
        default="first",
        help="When using --case-id-suffix, choose the first or last match.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Evaluate the first N regulations. Default is 20 for fast experimentation.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.2",
        help="OpenAI model to use.",
    )
    parser.add_argument(
        "--api-key",
        help="Optional OpenAI API key override.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional custom path for the latest report JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="log_compliance_outputs",
        help="Directory where reports are auto-saved by case_id.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Disable automatic saving of results.",
    )

    args = parser.parse_args()

    checker = build_default_checker(
        regulations_json_path=args.regulations_json,
        logs_csv_path=args.logs_csv,
        model=args.model,
        default_regulation_limit=args.limit,
        auto_save_reports=not args.no_save,
        output_dir=args.output_dir,
        api_key=args.api_key,
    )

    report = checker.check_case(
        case_id=args.case_id,
        case_id_suffix=args.case_id_suffix,
        pick=args.pick,
        limit=args.limit,
        save=not args.no_save,
        output_path=args.output,
        verbose=True,
    )

    print("\nSummary:")
    print(_json_dump(report["summary"]))

    if report.get("save_info"):
        print("\nSaved report files:")
        print(_json_dump(report["save_info"]))


if __name__ == "__main__":
    _cli()

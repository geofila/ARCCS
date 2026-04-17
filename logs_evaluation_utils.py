from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from log_compliance_checker import OpenAI, ProcurementLogLLMComplianceChecker, openai_legacy


CSV_FIELDS = [
    "case_id",
    "event",
    "timestamp",
    "t_type",
    "amount",
    "electronic",
    "framework_agr",
    "nuts",
    "country",
    "cpv_division",
    "cpv",
    "case_len",
]

RULE_SPECS: List[Dict[str, Any]] = [
    {
        "regulation_id": "R01_AMOUNT_LT_3000000",
        "regulation_name": "All contracts must have an amount below EUR 3,000,000",
        "base_regulation_id": "Directive threshold amounts section (points 4-7, with supplementary prevailing condition)",
        "brief_summary": "All contracts must have an amount below EUR 3,000,000.",
        "requirement": "The contract amount must remain below EUR 3,000,000.",
        "prohibition": "A contract amount above EUR 3,000,000 is not allowed.",
        "keywords": ["amount", "EUR 3,000,000", "threshold", "contract value"],
    },
    {
        "regulation_id": "R02_NO_DUPLICATE_PUBLICATION",
        "regulation_name": "A call already published must not be published again",
        "base_regulation_id": "Supplementary publication rule",
        "brief_summary": "A call already published must not be published again or multiple times.",
        "requirement": "The same call must be published only once.",
        "prohibition": "Republishing the same call is not allowed.",
        "keywords": ["publication", "duplicate publication", "call", "republish"],
    },
    {
        "regulation_id": "R03_NO_AWARD_BEFORE_PUBLICATION",
        "regulation_name": "Award must not occur before publication",
        "base_regulation_id": "Article 56(1)",
        "brief_summary": "The award cannot occur before the publication of the call.",
        "requirement": "Publication must occur before any award.",
        "prohibition": "Award before publication is not allowed.",
        "keywords": ["award", "publication", "sequence", "timing"],
    },
    {
        "regulation_id": "R04_NO_AWARD_BEFORE_PARTICIPATION",
        "regulation_name": "Award must not occur before participation",
        "base_regulation_id": "Article 56(1)",
        "brief_summary": "The award cannot occur before some candidate participates in the call.",
        "requirement": "At least one participation must occur before any award.",
        "prohibition": "Award before participation is not allowed.",
        "keywords": ["award", "participation", "candidate", "sequence"],
    },
    {
        "regulation_id": "R05_PUBLICATION_AND_PARTICIPATION_REQUIRE_AWARD",
        "regulation_name": "Publication and participation must eventually lead to award",
        "base_regulation_id": "Article 56(1)",
        "brief_summary": "If a call has been published and has candidate participation, an award must eventually be declared.",
        "requirement": "Publication together with participation must eventually be followed by award.",
        "prohibition": "Closing the case after publication and participation without any award is not allowed.",
        "keywords": ["publication", "participation", "award", "eventual award"],
    },
    {
        "regulation_id": "R06_AWARD_WITHIN_70_DAYS",
        "regulation_name": "Award must be announced within 70 days of publication",
        "base_regulation_id": "Article 56(1)",
        "brief_summary": "The time between publication and award must not exceed 70 days.",
        "requirement": "The award must be announced within 70 days from publication.",
        "prohibition": "An award more than 70 days after publication is not allowed.",
        "keywords": ["publication", "award", "70 days", "deadline"],
    },
    {
        "regulation_id": "R07_NO_CONTRACT_START_WITHOUT_AWARD",
        "regulation_name": "Contract must not start before award",
        "base_regulation_id": "Article 56(1)",
        "brief_summary": "A contract cannot start if no participant has been awarded.",
        "requirement": "Award must occur before contract start.",
        "prohibition": "Starting a contract before award is not allowed.",
        "keywords": ["contract start", "award", "sequence", "contract commencement"],
    },
    {
        "regulation_id": "R08_NO_CONTRACT_END_BEFORE_PUBLICATION",
        "regulation_name": "Contract must not end before publication",
        "base_regulation_id": "Document-stated lifecycle consistency rules",
        "brief_summary": "A contract cannot end before the publication of its corresponding call.",
        "requirement": "Publication must occur before contract end.",
        "prohibition": "Ending a contract before publication is not allowed.",
        "keywords": ["contract end", "publication", "sequence", "lifecycle"],
    },
    {
        "regulation_id": "R09_NO_CONTRACT_END_RIGHT_AFTER_PUBLICATION_WITHOUT_PARTICIPATION_AND_AWARD",
        "regulation_name": "Contract must not end after publication without participation and award",
        "base_regulation_id": "Document-stated lifecycle consistency rules",
        "brief_summary": "A contract cannot end just after publication without participation and a subsequent award.",
        "requirement": "If a contract ends after publication, participation and award must have occurred beforehand in the scenario described.",
        "prohibition": "Ending a contract after publication with no participation and no award is not allowed.",
        "keywords": ["contract end", "publication", "participation", "award", "incorrect path"],
    },
    {
        "regulation_id": "R10_CONTRACT_START_REQUIRES_CONTRACT_END",
        "regulation_name": "A started contract must have a conclusion date",
        "base_regulation_id": "Document-stated lifecycle consistency rules",
        "brief_summary": "A contract that starts must have a conclusion date.",
        "requirement": "Every started contract must also have a contract end.",
        "prohibition": "A contract start without a contract end is not allowed.",
        "keywords": ["contract start", "contract end", "conclusion date", "lifecycle"],
    },
    {
        "regulation_id": "R11_CONTRACT_END_REQUIRES_CONTRACT_START",
        "regulation_name": "A contract that ended must have started first",
        "base_regulation_id": "Document-stated lifecycle consistency rules",
        "brief_summary": "A contract that has ended must have started beforehand.",
        "requirement": "Contract start must occur before contract end exists.",
        "prohibition": "A contract end without contract start is not allowed.",
        "keywords": ["contract end", "contract start", "lifecycle", "start before end"],
    },
    {
        "regulation_id": "R12_CONTRACT_END_REQUIRES_AWARD",
        "regulation_name": "A terminated contract must have been awarded",
        "base_regulation_id": "Document-stated lifecycle consistency rules",
        "brief_summary": "A contract that is terminated must previously have been awarded to a participant.",
        "requirement": "Award must exist before contract end.",
        "prohibition": "A contract end without award is not allowed.",
        "keywords": ["contract end", "award", "termination", "participant"],
    },
]


class EvaluationCompatibleChecker(ProcurementLogLLMComplianceChecker):
    def _chat_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self._llm_available():
            raise RuntimeError(
                "LLM evaluation requires an OpenAI client and OPENAI_API_KEY."
            )

        request_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        # Some faster GPT-5 variants only accept the default temperature value.
        if self.model not in {"gpt-5-mini", "gpt-5-nano"}:
            request_kwargs["temperature"] = 0.0

        if OpenAI is not None:
            client = self._make_client()
            response = client.chat.completions.create(**request_kwargs)
            return json.loads(response.choices[0].message.content)

        response = openai_legacy.chat.completions.create(
            **request_kwargs,
            api_key=self.api_key,
        )
        return json.loads(response.choices[0].message.content)


def _date_string(base_date: date, offset_days: int) -> str:
    return (base_date + timedelta(days=offset_days)).isoformat()


def _metadata_for_case(case_index: int) -> Dict[str, str]:
    cpv_values = [
        ("33124110", "33"),
        ("33169100", "33"),
        ("30200000", "30"),
        ("45233120", "45"),
        ("50421000", "50"),
    ]
    nuts_values = ["ITI43", "ITI11", "ITI31", "ITI18", "ITI4C"]
    t_types = ["U", "W", "S"]
    cpv, cpv_division = cpv_values[case_index % len(cpv_values)]
    return {
        "t_type": t_types[case_index % len(t_types)],
        "electronic": "Y" if case_index % 2 else "N",
        "framework_agr": "Y" if case_index % 5 == 0 else "N",
        "nuts": nuts_values[case_index % len(nuts_values)],
        "country": "IT",
        "cpv_division": cpv_division,
        "cpv": cpv,
    }


def _build_rows(
    case_id: str,
    case_index: int,
    amount: float,
    events: List[Tuple[str, int]],
    base_date: date,
) -> List[Dict[str, str]]:
    metadata = _metadata_for_case(case_index)
    rows: List[Dict[str, str]] = []
    case_len = str(len(events))
    for event_name, offset_days in events:
        rows.append(
            {
                "case_id": case_id,
                "event": event_name,
                "timestamp": _date_string(base_date, offset_days),
                "t_type": metadata["t_type"],
                "amount": f"{amount:.1f}",
                "electronic": metadata["electronic"],
                "framework_agr": metadata["framework_agr"],
                "nuts": metadata["nuts"],
                "country": metadata["country"],
                "cpv_division": metadata["cpv_division"],
                "cpv": metadata["cpv"],
                "case_len": case_len,
            }
        )
    return rows


def _compliant_events(variant: int) -> Tuple[float, List[Tuple[str, int]]]:
    amount = 2_100_000 + (variant * 10_000)
    events = [
        ("PUBLICATION", 0),
        ("PARTICIPATION", 5 + variant),
        ("AWARD", 30 + variant),
        ("CONTRACT-START", 40 + variant),
        ("CONTRACT-END", 90 + variant),
    ]
    return float(amount), events


def _positive_events(rule_id: str, variant: int) -> Tuple[float, List[Tuple[str, int]]]:
    if rule_id == "R01_AMOUNT_LT_3000000":
        amount = 3_200_000 + (variant * 50_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 4 + variant),
            ("AWARD", 20 + variant),
            ("CONTRACT-START", 35 + variant),
            ("CONTRACT-END", 80 + variant),
        ]
        return float(amount), events

    if rule_id == "R02_NO_DUPLICATE_PUBLICATION":
        amount = 2_300_000 + (variant * 7_500)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("PUBLICATION", 7 + variant),
            ("AWARD", 20 + variant),
            ("CONTRACT-START", 35 + variant),
            ("CONTRACT-END", 70 + variant),
        ]
        return float(amount), events

    if rule_id == "R03_NO_AWARD_BEFORE_PUBLICATION":
        amount = 2_250_000 + (variant * 6_000)
        events = [
            ("PARTICIPATION", 0),
            ("AWARD", 2),
            ("PUBLICATION", 4 + variant),
            ("CONTRACT-START", 20 + variant),
            ("CONTRACT-END", 60 + variant),
        ]
        return float(amount), events

    if rule_id == "R04_NO_AWARD_BEFORE_PARTICIPATION":
        amount = 2_240_000 + (variant * 6_000)
        events = [
            ("PUBLICATION", 0),
            ("AWARD", 2),
            ("PARTICIPATION", 4 + variant),
            ("CONTRACT-START", 20 + variant),
            ("CONTRACT-END", 60 + variant),
        ]
        return float(amount), events

    if rule_id == "R05_PUBLICATION_AND_PARTICIPATION_REQUIRE_AWARD":
        amount = 2_280_000 + (variant * 8_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 4 + variant),
        ]
        return float(amount), events

    if rule_id == "R06_AWARD_WITHIN_70_DAYS":
        amount = 2_350_000 + (variant * 10_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("AWARD", 90 + variant),
            ("CONTRACT-START", 100 + variant),
            ("CONTRACT-END", 140 + variant),
        ]
        return float(amount), events

    if rule_id == "R07_NO_CONTRACT_START_WITHOUT_AWARD":
        amount = 2_180_000 + (variant * 5_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("CONTRACT-START", 10 + variant),
            ("AWARD", 15 + variant),
            ("CONTRACT-END", 50 + variant),
        ]
        return float(amount), events

    if rule_id == "R08_NO_CONTRACT_END_BEFORE_PUBLICATION":
        amount = 2_260_000 + (variant * 6_500)
        events = [
            ("PARTICIPATION", 0),
            ("AWARD", 1),
            ("CONTRACT-START", 2),
            ("CONTRACT-END", 3),
            ("PUBLICATION", 5 + variant),
        ]
        return float(amount), events

    if rule_id == "R09_NO_CONTRACT_END_RIGHT_AFTER_PUBLICATION_WITHOUT_PARTICIPATION_AND_AWARD":
        amount = 2_210_000 + (variant * 4_000)
        events = [
            ("PUBLICATION", 0),
            ("CONTRACT-END", 2 + variant),
        ]
        return float(amount), events

    if rule_id == "R10_CONTRACT_START_REQUIRES_CONTRACT_END":
        amount = 2_290_000 + (variant * 6_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("AWARD", 15),
            ("CONTRACT-START", 25 + variant),
        ]
        return float(amount), events

    if rule_id == "R11_CONTRACT_END_REQUIRES_CONTRACT_START":
        amount = 2_270_000 + (variant * 6_000)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("AWARD", 15),
            ("CONTRACT-END", 25 + variant),
        ]
        return float(amount), events

    if rule_id == "R12_CONTRACT_END_REQUIRES_AWARD":
        amount = 2_220_000 + (variant * 4_500)
        events = [
            ("PUBLICATION", 0),
            ("PARTICIPATION", 5),
            ("CONTRACT-START", 10),
            ("CONTRACT-END", 20 + variant),
        ]
        return float(amount), events

    raise ValueError(f"Unsupported rule_id: {rule_id}")


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def evaluate_truth_for_rows(rows: List[Dict[str, str]]) -> Dict[str, bool]:
    ordered_rows = sorted(rows, key=lambda row: (row["timestamp"], row["event"]))
    events = [row["event"] for row in ordered_rows]
    counts = Counter(events)
    first_dates: Dict[str, Optional[date]] = {}
    for event_name in ("PUBLICATION", "PARTICIPATION", "AWARD", "CONTRACT-START", "CONTRACT-END"):
        matching = [_parse_date(row["timestamp"]) for row in ordered_rows if row["event"] == event_name]
        first_dates[event_name] = next((value for value in matching if value is not None), None)

    amounts: List[float] = []
    for row in ordered_rows:
        try:
            amounts.append(float(row["amount"]))
        except (TypeError, ValueError):
            continue
    max_amount = max(amounts) if amounts else None

    truth = {
        "R01_AMOUNT_LT_3000000": bool(max_amount is not None and max_amount > 3_000_000),
        "R02_NO_DUPLICATE_PUBLICATION": counts["PUBLICATION"] > 1,
        "R03_NO_AWARD_BEFORE_PUBLICATION": counts["AWARD"] > 0
        and (
            first_dates["PUBLICATION"] is None
            or first_dates["AWARD"] < first_dates["PUBLICATION"]
        ),
        "R04_NO_AWARD_BEFORE_PARTICIPATION": counts["AWARD"] > 0
        and (
            first_dates["PARTICIPATION"] is None
            or first_dates["AWARD"] < first_dates["PARTICIPATION"]
        ),
        "R05_PUBLICATION_AND_PARTICIPATION_REQUIRE_AWARD": counts["PUBLICATION"] > 0
        and counts["PARTICIPATION"] > 0
        and counts["AWARD"] == 0,
        "R06_AWARD_WITHIN_70_DAYS": bool(
            first_dates["PUBLICATION"]
            and first_dates["AWARD"]
            and (first_dates["AWARD"] - first_dates["PUBLICATION"]).days > 70
        ),
        "R07_NO_CONTRACT_START_WITHOUT_AWARD": counts["CONTRACT-START"] > 0
        and (
            counts["AWARD"] == 0
            or (
                first_dates["AWARD"] is not None
                and first_dates["CONTRACT-START"] is not None
                and first_dates["CONTRACT-START"] < first_dates["AWARD"]
            )
        ),
        "R08_NO_CONTRACT_END_BEFORE_PUBLICATION": counts["CONTRACT-END"] > 0
        and (
            first_dates["PUBLICATION"] is None
            or first_dates["CONTRACT-END"] < first_dates["PUBLICATION"]
        ),
        "R09_NO_CONTRACT_END_RIGHT_AFTER_PUBLICATION_WITHOUT_PARTICIPATION_AND_AWARD": counts["PUBLICATION"] > 0
        and counts["CONTRACT-END"] > 0
        and counts["PARTICIPATION"] == 0
        and counts["AWARD"] == 0,
        "R10_CONTRACT_START_REQUIRES_CONTRACT_END": counts["CONTRACT-START"] > 0
        and counts["CONTRACT-END"] == 0,
        "R11_CONTRACT_END_REQUIRES_CONTRACT_START": counts["CONTRACT-END"] > 0
        and counts["CONTRACT-START"] == 0,
        "R12_CONTRACT_END_REQUIRES_AWARD": counts["CONTRACT-END"] > 0
        and counts["AWARD"] == 0,
    }

    return truth


def build_custom_regulations(
    regulations_json_path: str = "extracted_regulations_CELEX.json",
) -> List[Dict[str, Any]]:
    payload = json.loads(Path(regulations_json_path).read_text(encoding="utf-8"))
    regulation_items = payload["regulations"] if isinstance(payload, dict) else payload
    base_map = {
        regulation.get("regulation_id"): regulation
        for regulation in regulation_items
        if isinstance(regulation, dict) and regulation.get("regulation_id")
    }

    custom_regulations: List[Dict[str, Any]] = []
    for spec in RULE_SPECS:
        base_regulation = base_map.get(spec["base_regulation_id"], {})
        custom_regulations.append(
            {
                "regulation_id": spec["regulation_id"],
                "regulation_name": spec["regulation_name"],
                "regulation_type": "evaluation_rule",
                "description": {
                    "brief_summary": spec["brief_summary"],
                    "detailed_explanation": (
                        f"This evaluation rule is derived from '{spec['base_regulation_id']}' "
                        f"and isolates one concrete compliance condition for testing the log checker."
                    ),
                },
                "requirements": {
                    "mandatory_obligations": [spec["requirement"]],
                    "prohibited_actions": [spec["prohibition"]],
                    "conditional_requirements": [],
                    "documentation_requirements": [],
                    "reporting_requirements": [],
                    "timeline_requirements": [],
                },
                "restrictions": {
                    "general_restrictions": [spec["prohibition"]],
                    "operational_restrictions": [],
                },
                "compliance_requirements": {
                    "organizational_measures": [],
                    "audit_requirements": [],
                },
                "dates": {},
                "keywords": spec["keywords"],
                "source_section": base_regulation.get("source_section"),
                "related_regulations": {
                    "parent_legislation": "Directive 2014/24/EU evaluation subset",
                    "related_articles": [spec["base_regulation_id"]],
                },
                "evaluation_metadata": {
                    "derived_from_regulation_id": spec["base_regulation_id"],
                },
            }
        )

    return custom_regulations


def generate_evaluation_cases(
    positive_variants_per_rule: int = 5,
    compliant_case_count: int = 40,
) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    case_index = 1

    for rule_position, spec in enumerate(RULE_SPECS, start=1):
        for variant in range(positive_variants_per_rule):
            case_id = f"EVAL{case_index:04d}"
            base_date = date(2024, 1, 1) + timedelta(days=(rule_position - 1) * 120 + variant * 9)
            amount, events = _positive_events(spec["regulation_id"], variant)
            rows = _build_rows(case_id, case_index, amount, events, base_date)
            truth = evaluate_truth_for_rows(rows)
            if not truth[spec["regulation_id"]]:
                raise ValueError(f"Positive case {case_id} does not violate target rule {spec['regulation_id']}.")
            cases.append(
                {
                    "case_id": case_id,
                    "scenario": "targeted_positive",
                    "target_rule": spec["regulation_id"],
                    "variant": variant + 1,
                    "rows": rows,
                    "expected_truth": truth,
                }
            )
            case_index += 1

    for variant in range(compliant_case_count):
        case_id = f"EVAL{case_index:04d}"
        base_date = date(2026, 1, 1) + timedelta(days=variant * 11)
        amount, events = _compliant_events(variant)
        rows = _build_rows(case_id, case_index, amount, events, base_date)
        truth = evaluate_truth_for_rows(rows)
        if any(truth.values()):
            raise ValueError(f"Compliant control case {case_id} unexpectedly violates a rule.")
        cases.append(
            {
                "case_id": case_id,
                "scenario": "compliant_control",
                "target_rule": None,
                "variant": variant + 1,
                "rows": rows,
                "expected_truth": truth,
            }
        )
        case_index += 1

    return cases


def write_evaluation_logs_csv(cases: List[Dict[str, Any]], output_csv_path: Path) -> None:
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with output_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        for case in cases:
            for row in case["rows"]:
                writer.writerow(row)


def _build_run_directories(output_root: str) -> Dict[str, Path]:
    root = Path(output_root)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / f"run_{timestamp}"
    case_reports_dir = run_dir / "case_reports"
    run_dir.mkdir(parents=True, exist_ok=True)
    case_reports_dir.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "run_dir": run_dir,
        "case_reports_dir": case_reports_dir,
        "timestamp": Path(timestamp),
    }


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _binary_metrics(expected_positive: List[bool], predicted_positive: List[bool]) -> Dict[str, Any]:
    tp = sum(1 for exp, pred in zip(expected_positive, predicted_positive) if exp and pred)
    tn = sum(1 for exp, pred in zip(expected_positive, predicted_positive) if not exp and not pred)
    fp = sum(1 for exp, pred in zip(expected_positive, predicted_positive) if not exp and pred)
    fn = sum(1 for exp, pred in zip(expected_positive, predicted_positive) if exp and not pred)

    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": _safe_ratio(tp + tn, tp + tn + fp + fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "support_positive": tp + fn,
        "support_negative": tn + fp,
    }


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_logs_evaluation(
    regulations_json_path: str = "extracted_regulations_CELEX.json",
    model: str = "gpt-5.2",
    api_key: Optional[str] = None,
    output_root: str = "Evaluation Results/logs_evaluiation",
    positive_variants_per_rule: int = 5,
    compliant_case_count: int = 40,
    verbose: bool = True,
) -> Dict[str, Any]:
    directories = _build_run_directories(output_root)
    run_dir = directories["run_dir"]
    case_reports_dir = directories["case_reports_dir"]

    cases = generate_evaluation_cases(
        positive_variants_per_rule=positive_variants_per_rule,
        compliant_case_count=compliant_case_count,
    )
    if len(cases) != 100:
        raise ValueError(f"Expected 100 evaluation cases, found {len(cases)}.")

    custom_regulations = build_custom_regulations(regulations_json_path=regulations_json_path)
    logs_csv_path = run_dir / "evaluation_logs_100.csv"
    write_evaluation_logs_csv(cases, logs_csv_path)

    ground_truth_by_case = {
        case["case_id"]: {
            "scenario": case["scenario"],
            "target_rule": case["target_rule"],
            "variant": case["variant"],
            "expected_truth": case["expected_truth"],
        }
        for case in cases
    }
    _save_json(run_dir / "ground_truth_by_case.json", ground_truth_by_case)

    checker = EvaluationCompatibleChecker(
        regulations_json_path=regulations_json_path,
        logs_csv_path=str(logs_csv_path),
        model=model,
        default_regulation_limit=len(custom_regulations),
        auto_save_reports=False,
        output_dir=str(run_dir / "checker_outputs"),
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
    )
    checker.regulations = custom_regulations

    all_detailed_rows: List[Dict[str, Any]] = []
    case_level_rows: List[Dict[str, Any]] = []

    for case_number, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        if verbose:
            print(f"[{case_number}/{len(cases)}] Evaluating case {case_id}")
        case_rows = checker.get_case_rows(case_id=case_id)
        case_facts = checker.build_case_facts(case_rows)

        detailed_results: List[Dict[str, Any]] = []
        for regulation in custom_regulations:
            result = checker.check_single_regulation(regulation, case_facts)
            expected_violation = bool(case["expected_truth"][regulation["regulation_id"]])
            predicted_violation = result["compliance_status"] == "NON_COMPLIANT"
            enriched_result = {
                **result,
                "expected_violation": expected_violation,
                "predicted_violation": predicted_violation,
                "is_correct_binary": expected_violation == predicted_violation,
                "scenario": case["scenario"],
                "target_rule": case["target_rule"],
                "variant": case["variant"],
            }
            detailed_results.append(enriched_result)

            all_detailed_rows.append(
                {
                    "case_id": case_id,
                    "scenario": case["scenario"],
                    "target_rule": case["target_rule"] or "",
                    "variant": case["variant"],
                    "regulation_id": regulation["regulation_id"],
                    "regulation_name": regulation["regulation_name"],
                    "expected_violation": int(expected_violation),
                    "predicted_violation": int(predicted_violation),
                    "compliance_status": enriched_result["compliance_status"],
                    "is_correct_binary": int(expected_violation == predicted_violation),
                    "confidence_score": enriched_result["confidence_score"],
                    "has_sufficient_information": int(bool(enriched_result["has_sufficient_information"])),
                    "conflict_found": int(bool(enriched_result["conflict_found"])),
                    "relevant_log_fields": "|".join(enriched_result["relevant_log_fields"]),
                    "evidence_from_logs": " || ".join(enriched_result["evidence_from_logs"]),
                    "missing_information": json.dumps(enriched_result["missing_information"], ensure_ascii=False),
                    "explanation": enriched_result["explanation"],
                }
            )

        combined_report = checker.generate_report(case_facts=case_facts, results=detailed_results)
        combined_report["ground_truth"] = ground_truth_by_case[case_id]
        combined_report["evaluation_metadata"] = {
            "model": model,
            "regulation_ids": [regulation["regulation_id"] for regulation in custom_regulations],
        }
        _save_json(case_reports_dir / f"{case_id}.json", combined_report)

        expected_case_violation = any(case["expected_truth"].values())
        predicted_case_violation = combined_report["summary"]["non_compliant"] > 0
        exact_match_all_12 = all(result["is_correct_binary"] for result in detailed_results)

        case_level_rows.append(
            {
                "case_id": case_id,
                "scenario": case["scenario"],
                "target_rule": case["target_rule"] or "",
                "variant": case["variant"],
                "expected_case_violation": int(expected_case_violation),
                "predicted_case_violation": int(predicted_case_violation),
                "exact_match_all_12": int(exact_match_all_12),
                "overall_status": combined_report["summary"]["overall_status"],
                "non_compliant_count": combined_report["summary"]["non_compliant"],
                "compliant_count": combined_report["summary"]["compliant"],
                "human_required_count": combined_report["summary"]["human_required"],
                "insufficient_information_count": combined_report["summary"]["insufficient_information"],
            }
        )

    detailed_csv_fields = [
        "case_id",
        "scenario",
        "target_rule",
        "variant",
        "regulation_id",
        "regulation_name",
        "expected_violation",
        "predicted_violation",
        "compliance_status",
        "is_correct_binary",
        "confidence_score",
        "has_sufficient_information",
        "conflict_found",
        "relevant_log_fields",
        "evidence_from_logs",
        "missing_information",
        "explanation",
    ]
    _save_csv(run_dir / "detailed_case_rule_results.csv", all_detailed_rows, detailed_csv_fields)
    _save_json(run_dir / "detailed_case_rule_results.json", all_detailed_rows)

    case_level_fields = [
        "case_id",
        "scenario",
        "target_rule",
        "variant",
        "expected_case_violation",
        "predicted_case_violation",
        "exact_match_all_12",
        "overall_status",
        "non_compliant_count",
        "compliant_count",
        "human_required_count",
        "insufficient_information_count",
    ]
    _save_csv(run_dir / "case_level_results.csv", case_level_rows, case_level_fields)
    _save_json(run_dir / "case_level_results.json", case_level_rows)

    metrics_by_rule: List[Dict[str, Any]] = []
    for spec in RULE_SPECS:
        rule_rows = [row for row in all_detailed_rows if row["regulation_id"] == spec["regulation_id"]]
        metrics = _binary_metrics(
            expected_positive=[bool(row["expected_violation"]) for row in rule_rows],
            predicted_positive=[bool(row["predicted_violation"]) for row in rule_rows],
        )
        status_counts = Counter(row["compliance_status"] for row in rule_rows)
        metrics_by_rule.append(
            {
                "regulation_id": spec["regulation_id"],
                "regulation_name": spec["regulation_name"],
                "cases_evaluated": len(rule_rows),
                "expected_violations": metrics["support_positive"],
                "predicted_violations": metrics["tp"] + metrics["fp"],
                "tp": metrics["tp"],
                "tn": metrics["tn"],
                "fp": metrics["fp"],
                "fn": metrics["fn"],
                "accuracy": round(metrics["accuracy"], 6),
                "precision": round(metrics["precision"], 6),
                "recall": round(metrics["recall"], 6),
                "f1": round(metrics["f1"], 6),
                "status_compliant": status_counts.get("COMPLIANT", 0),
                "status_non_compliant": status_counts.get("NON_COMPLIANT", 0),
                "status_human_required": status_counts.get("HUMAN_REQUIRED", 0),
                "status_insufficient_information": status_counts.get("INSUFFICIENT_INFORMATION", 0),
            }
        )

    overall_pair_metrics = _binary_metrics(
        expected_positive=[bool(row["expected_violation"]) for row in all_detailed_rows],
        predicted_positive=[bool(row["predicted_violation"]) for row in all_detailed_rows],
    )
    overall_case_metrics = _binary_metrics(
        expected_positive=[bool(row["expected_case_violation"]) for row in case_level_rows],
        predicted_positive=[bool(row["predicted_case_violation"]) for row in case_level_rows],
    )

    summary_metrics = {
        "run_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "cases_evaluated": len(cases),
        "regulations_evaluated": len(custom_regulations),
        "total_case_rule_evaluations": len(all_detailed_rows),
        "overall_pair_metrics": overall_pair_metrics,
        "overall_case_metrics": {
            **overall_case_metrics,
            "exact_match_all_12_cases": sum(row["exact_match_all_12"] for row in case_level_rows),
            "exact_match_all_12_rate": round(
                _safe_ratio(sum(row["exact_match_all_12"] for row in case_level_rows), len(case_level_rows)),
                6,
            ),
        },
        "metrics_by_rule": metrics_by_rule,
    }

    metrics_csv_fields = [
        "regulation_id",
        "regulation_name",
        "cases_evaluated",
        "expected_violations",
        "predicted_violations",
        "tp",
        "tn",
        "fp",
        "fn",
        "accuracy",
        "precision",
        "recall",
        "f1",
        "status_compliant",
        "status_non_compliant",
        "status_human_required",
        "status_insufficient_information",
    ]
    _save_csv(run_dir / "metrics_by_rule.csv", metrics_by_rule, metrics_csv_fields)
    _save_json(run_dir / "summary_metrics.json", summary_metrics)

    manifest = {
        "run_dir": str(run_dir),
        "logs_csv_path": str(logs_csv_path),
        "ground_truth_by_case_path": str(run_dir / "ground_truth_by_case.json"),
        "detailed_results_csv_path": str(run_dir / "detailed_case_rule_results.csv"),
        "detailed_results_json_path": str(run_dir / "detailed_case_rule_results.json"),
        "case_level_results_csv_path": str(run_dir / "case_level_results.csv"),
        "case_level_results_json_path": str(run_dir / "case_level_results.json"),
        "metrics_by_rule_csv_path": str(run_dir / "metrics_by_rule.csv"),
        "summary_metrics_json_path": str(run_dir / "summary_metrics.json"),
        "case_reports_dir": str(case_reports_dir),
        "cases_evaluated": len(cases),
        "case_rule_evaluations": len(all_detailed_rows),
        "custom_regulation_ids": [spec["regulation_id"] for spec in RULE_SPECS],
    }
    _save_json(run_dir / "manifest.json", manifest)
    _save_json(Path(output_root) / "latest_manifest.json", manifest)

    return {
        "manifest": manifest,
        "summary_metrics": summary_metrics,
    }


if __name__ == "__main__":
    api_key = os.getenv("OPENAI_API_KEY")
    result = run_logs_evaluation(api_key=api_key)
    print(json.dumps(result["manifest"], ensure_ascii=False, indent=2))

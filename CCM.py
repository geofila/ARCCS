"""
CCM - Compliance Classification Module
Part of ARCCS (Automated Regulatory Compliance Classification System)

This module handles:
- Regulation-level compliance checking
- Contradiction detection between regulations and documents
- Compliance report generation
- Structured explanations for compliance assessments
"""

import openai
import json
from typing import List, Dict, Optional


# ============================================================
# COMPLIANCE CHECKING
# ============================================================

def check_regulation_compliance(
    regulation: Dict,
    proposal_chunk: str,
    model: str = "gpt-5.2"
) -> Dict:
    """
    Check if a document complies with a specific regulation.
    
    The check focuses on finding CONTRADICTIONS:
    - If contradiction found → NON_COMPLIANT
    - If no contradiction found → COMPLIANT
    
    Args:
        regulation: Dict containing regulation details
        proposal_chunk: Text of document to check
        model: OpenAI model to use
    
    Returns:
        Dict with compliance status and details
    """
    
    reg_name = regulation.get('regulation_name', 'Unknown')
    reg_id = regulation.get('regulation_id', 'N/A')
    
    description = regulation.get('description', {})
    if isinstance(description, dict):
        brief = description.get('brief_summary', 'N/A')
    else:
        brief = str(description)[:500]
    
    requirements = regulation.get('requirements', {})
    restrictions = regulation.get('restrictions', {})
    
    prompt = f"""REGULATION: {reg_name} ({reg_id})
Summary: {brief}
Requirements: {json.dumps(requirements, ensure_ascii=False)}
Restrictions: {json.dumps(restrictions, ensure_ascii=False)}

DOCUMENT TO CHECK:
{proposal_chunk}

---

YOUR TASK: Find if the document CONTRADICTS this regulation.

A CONTRADICTION means:
- Document says X, but regulation REQUIRES Y (opposite things)
- Document permits something regulation FORBIDS
- Document has a number/timeline that conflicts with regulation

EXAMPLES:
- Regulation: "Users must be 16+ in EU" | Document: "Users must be 13" → CONTRADICTION
- Regulation: "Cannot sell data" | Document: "We may sell your data" → CONTRADICTION
- Regulation: "Notify within 72h" | Document: "Notify within 30 days" → CONTRADICTION

NOT A CONTRADICTION:
- Document doesn't mention the topic → NOT a contradiction but INSUFFICIENT_INFORMATION
- No direct, explicit statement addressing the regulation → NOT a contradiction but INSUFFICIENT_INFORMATION
- Regulation: "Notify within 72h" | Document: "Notify within 72 days" → COMPLIANT
- Regulation: "Users must be 16+ in EU" | Document: "Users must be 16 or older" → COMPLIANT


---

Search the document for ANY statement that DIRECTLY CONTRADICTS the regulation.

Return JSON:
{{
    "regulation_id": "{reg_id}",
    "regulation_name": "{reg_name}",
    "contradiction_found": true/false,
    "has_relevant_information": true/false,
    "missing_information": "If has_relevant_information is false: explain what information is missing. Otherwise: null",
    "contradiction_details": "If found: quote the document text and explain the conflict. If not found: null",
    "compliance_status": "NON_COMPLIANT if contradiction found, COMPLIANT if no contradiction and has info, INSUFFICIENT_INFORMATION if no relevant info found, HUMAN_REQUIRED if unclear",
    "evidence": "Quote from document (or null if no relevant info)",
    "confidence_score": 0.0-1.0,
    "explanation": "Detailed justification for the assessment"
}}"""

    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": """You are the Compliance Classification Module (CCM) of ARCCS.

Your task is to check documents for regulatory CONTRADICTIONS.

RULE 1: Assume from the beginning that you have all the necessary information to make a decision. If, however, essential details are missing and you cannot properly evaluate the case, then the result should be INSUFFICIENT_INFORMATION.

RULE 2: If you have all the required information and you do not identify any contradiction between the compared elements, then the document is COMPLIANT.

RULE 3: If you have all the required information and you identify a contradiction between the compared elements, then the document is NON_COMPLIANT.

FINAL RULE: If you have all the necessary information but, for any reason, you still cannot reach a clear decision, then the result should be HUMAN_REQUIRED.

Be precise. Return JSON only."""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Apply classification logic based on findings
        contradiction_found = result.get('contradiction_found', False)
        has_info = result.get('has_relevant_information', True)
        confidence = result.get('confidence_score', 0.5)
        
        # Priority 1: If contradiction found → NON_COMPLIANT
        if contradiction_found == True:
            result['compliance_status'] = 'NON_COMPLIANT'
        # Priority 2: If no relevant information → INSUFFICIENT_INFORMATION
        elif has_info == False:
            result['compliance_status'] = 'INSUFFICIENT_INFORMATION'
        # Priority 3: If low confidence (<0.7) → HUMAN_REQUIRED
        elif confidence < 0.7:
            result['compliance_status'] = 'HUMAN_REQUIRED'
        # Priority 4: Has info, no contradiction, good confidence → COMPLIANT
        else:
            result['compliance_status'] = 'COMPLIANT'
        
        return result
        
    except Exception as e:
        print (e)
        return {
            "regulation_id": reg_id,
            "regulation_name": reg_name,
            "contradiction_found": False,
            "compliance_status": "COMPLIANT",
            "explanation": f"Error during analysis: {str(e)}",
            "error": str(e)
        }


def check_all_regulations(
    regulations: List[Dict],
    proposal_chunk: str,
    model: str = "gpt-5.2",
    only_applicable: bool = True,
    verbose: bool = True
) -> List[Dict]:
    """
    Check compliance against multiple regulations.
    
    Args:
        regulations: List of regulation dicts
        proposal_chunk: Text of document to check
        model: OpenAI model to use
        only_applicable: Whether to skip non-applicable regulations
        verbose: Whether to print progress
    
    Returns:
        List of compliance check results
    """
    results = []
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🔍 ARCCS - CCM: Compliance Classification Module")
        print(f"{'='*60}")
        print(f"Checking {len(regulations)} regulations...\n")
    
    for i, reg in enumerate(regulations):
        reg_name = reg.get('regulation_name') or 'Unknown'
        reg_name = reg_name[:55] if reg_name else 'Unknown'
        
        if verbose:
            print(f"⚖️ [{i+1}/{len(regulations)}] {reg_name}...")
        
        result = check_regulation_compliance(
            regulation=reg,
            proposal_chunk=proposal_chunk,
            model=model
        )
        
        status = result.get('compliance_status', 'UNKNOWN')
        
        if verbose:
            if status == 'NON_COMPLIANT':
                print(f"   ❌ NON_COMPLIANT - Contradiction found!")
                if result.get('contradiction_details'):
                    print(f"      → {result['contradiction_details'][:80]}...")
            elif status == 'INSUFFICIENT_INFORMATION':
                print(f"   ⚠️ INSUFFICIENT_INFORMATION - Missing data")
                if result.get('missing_information'):
                    print(f"      → {result['missing_information'][:80]}...")
            elif status == 'HUMAN_REQUIRED':
                print(f"   🔍 HUMAN_REQUIRED - Low confidence ({result.get('confidence_score', 0):.0%})")
            else:
                print(f"   ✅ COMPLIANT")
            
        results.append(result)
    
    return results


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_compliance_report(results: List[Dict]) -> Dict:
    """
    Generate a comprehensive compliance report.
    
    Args:
        results: List of compliance check results
    
    Returns:
        Dict with summary, violations, and detailed results
    """
    compliant = sum(1 for r in results if r.get('compliance_status') == 'COMPLIANT')
    non_compliant = sum(1 for r in results if r.get('compliance_status') == 'NON_COMPLIANT')
    insufficient_info = sum(1 for r in results if r.get('compliance_status') == 'INSUFFICIENT_INFORMATION')
    human_required = sum(1 for r in results if r.get('compliance_status') == 'HUMAN_REQUIRED')
    
    violations = [r for r in results if r.get('compliance_status') == 'NON_COMPLIANT']
    needs_review = [r for r in results if r.get('compliance_status') in ['INSUFFICIENT_INFORMATION', 'HUMAN_REQUIRED']]
    
    total = len(results)
    
    if non_compliant > 0:
        overall = f"❌ NON-COMPLIANT - {non_compliant} violation(s) found"
    elif insufficient_info > 0 or human_required > 0:
        overall = f"⚠️ REVIEW REQUIRED - {insufficient_info + human_required} item(s) need attention"
    else:
        overall = f"✅ COMPLIANT - No violations found in {total} regulations"
    
    # Calculate compliance rate (only from definitive results)
    definitive_total = compliant + non_compliant
    compliance_rate = (compliant / definitive_total * 100) if definitive_total > 0 else 0
    
    return {
        "overall_status": overall,
        "summary": {
            "compliant": compliant,
            "non_compliant": non_compliant,
            "insufficient_info": insufficient_info,
            "human_required": human_required,
            "total": total,
            "compliance_rate": round(compliance_rate, 1)
        },
        "violations": violations,
        "needs_review": needs_review,
        "detailed_results": results
    }


def print_detailed_report(report: Dict):
    """
    Print a formatted compliance report.
    
    Args:
        report: Report dict from generate_compliance_report
    """
    print(f"\n{'='*70}")
    print(f"📊 ARCCS COMPLIANCE REPORT")
    print(f"{'='*70}")
    
    print(f"\n{report['overall_status']}")
    
    s = report['summary']
    print(f"\n📈 SUMMARY:")
    print(f"   ✅ Compliant:           {s['compliant']}")
    print(f"   ❌ Non-Compliant:       {s['non_compliant']}")
    print(f"   ⚠️  Insufficient Info:   {s.get('insufficient_info', 0)}")
    print(f"   � Human Required:      {s.get('human_required', 0)}")
    print(f"   �📋 Total Checked:       {s['total']}")
    print(f"   📊 Compliance Rate:     {s['compliance_rate']}%")
    
    if report['violations']:
        print(f"\n{'='*70}")
        print(f"🚨 VIOLATIONS FOUND ({len(report['violations'])})")
        print(f"{'='*70}")
        
        for i, v in enumerate(report['violations'], 1):
            print(f"\n{i}. {v.get('regulation_name', 'Unknown')}")
            print(f"   ID: {v.get('regulation_id', 'N/A')}")
            if v.get('contradiction_details'):
                print(f"   Issue: {v['contradiction_details'][:200]}")
            if v.get('evidence'):
                print(f"   Evidence: \"{v['evidence'][:100]}...\"")
            if v.get('explanation'):
                print(f"   Explanation: {v['explanation'][:150]}...")
    
    if report.get('needs_review'):
        print(f"\n{'='*70}")
        print(f"⚠️ NEEDS REVIEW ({len(report['needs_review'])})")
        print(f"{'='*70}")
        
        for i, r in enumerate(report['needs_review'], 1):
            status = r.get('compliance_status', 'UNKNOWN')
            print(f"\n{i}. {r.get('regulation_name', 'Unknown')} [{status}]")
            print(f"   ID: {r.get('regulation_id', 'N/A')}")
            if status == 'INSUFFICIENT_INFORMATION' and r.get('missing_information'):
                print(f"   Missing: {r['missing_information'][:150]}...")
            elif status == 'HUMAN_REQUIRED':
                print(f"   Confidence: {r.get('confidence_score', 0):.0%}")
            if r.get('explanation'):
                print(f"   Note: {r['explanation'][:150]}...")
    
    print(f"\n{'='*70}")


def export_report_to_json(report: Dict, filepath: str):
    """
    Export compliance report to JSON file.
    
    Args:
        report: Report dict
        filepath: Output file path
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"💾 Report saved to '{filepath}'")


# ============================================================
# MODULE INFO
# ============================================================

def print_module_info():
    """Print CCM module information."""
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                           ARCCS - CCM                             ║
║            Compliance Classification Module                       ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  Part of ARCCS (Automated Regulatory Compliance Classification    ║
║  System) - A multi-agent system for regulation-level compliance   ║
║  assessment.                                                      ║
║                                                                   ║
║  Functions:                                                       ║
║    • check_regulation_compliance() - Check single regulation      ║
║    • check_all_regulations()       - Batch compliance check       ║
║    • generate_compliance_report()  - Create summary report        ║
║    • print_detailed_report()       - Display formatted report     ║
║    • export_report_to_json()       - Save report to file          ║
║                                                                   ║
║  Output Labels:                                                   ║
║    • COMPLIANT              - No contradiction, has info          ║
║    • NON_COMPLIANT          - Contradiction detected              ║
║    • INSUFFICIENT_INFO      - Missing relevant information        ║
║    • HUMAN_REQUIRED         - Low confidence, needs review        ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    print_module_info()
"""
RPEM - Regulatory Processing and Extraction Module
Part of ARCCS (Automated Regulatory Compliance Classification System)

This module handles:
- PDF parsing and text extraction
- Section splitting and preprocessing
- AI-powered regulation extraction
- Quality filtering and deduplication
"""

import openai
import json
import re
from typing import List, Dict, Optional
from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import Title


# ============================================================
# DOCUMENT PARSING
# ============================================================

def load_pdf_document(filepath: str, strategy: str = "hi_res") -> List:
    """
    Load and parse a PDF document into elements.
    
    Args:
        filepath: Path to the PDF file
        strategy: Parsing strategy ('hi_res', 'fast', 'auto')
    
    Returns:
        List of document elements
    """
    print(f"📄 Loading document: {filepath}")
    
    elements = partition_pdf(
        filename=filepath,
        strategy=strategy,
        infer_table_structure=True
    )
    
    print(f"✅ Loaded {len(elements)} elements")
    return elements


def elements_to_markdown(elements: List) -> str:
    """
    Convert parsed PDF elements to markdown text.
    
    Args:
        elements: List of document elements from partition_pdf
    
    Returns:
        Markdown-formatted text
    """
    md = ""
    for el in elements:
        if isinstance(el, Title):
            md += f"\n## {el.text}\n"
        else:
            md += f"{el.text}\n"
    return md


def split_into_sections(markdown_text: str) -> List[Dict[str, str]]:
    """
    Split markdown text into sections based on headers.
    
    Args:
        markdown_text: Full markdown text
    
    Returns:
        List of dicts with 'title' and 'content' keys
    """
    pattern = r'(#+\s.*)'
    parts = re.split(pattern, markdown_text)

    sections = []
    current_title = None
    current_content = ""

    for part in parts:
        if part.startswith("#"):
            if current_title:
                sections.append({
                    "title": current_title,
                    "content": current_content.strip()
                })
            current_title = part.strip()
            current_content = ""
        else:
            current_content += part

    if current_title:
        sections.append({
            "title": current_title,
            "content": current_content.strip()
        })

    return sections


# ============================================================
# REGULATION EXTRACTION
# ============================================================

def extract_regulations_from_section(
    section: Dict[str, str],
    model: str = "gpt-4.1"
) -> Dict:
    """
    Use AI to extract structured regulation data from a document section.
    
    Args:
        section: Dict with 'title' and 'content' keys
        model: OpenAI model to use
    
    Returns:
        Dict with extracted regulations and metadata
    """
    
    prompt = f"""You are a senior legal and compliance expert specializing in regulatory analysis. Analyze the following document section and extract ALL regulatory information in extreme detail.

SECTION TITLE: {section['title']}

SECTION CONTENT:
{section['content']}

---

CRITICAL FILTERING RULES - READ CAREFULLY:

Before extracting any regulations, determine if this section is:

1. **INTRODUCTORY/GENERAL SECTION** - DO NOT EXTRACT regulations if the section:
   - Is a table of contents, preamble, or general introduction
   - Only MENTIONS regulations that will be "explained later" or "detailed below"
   - Provides a high-level overview without specific requirements
   - Lists regulation names/numbers without explaining their actual requirements
   - Says things like "the following articles shall apply", "as detailed in subsequent chapters"
   - Is a summary or recital that doesn't contain actionable compliance requirements

2. **DETAILED/SPECIFIC SECTION** - EXTRACT regulations only if the section:
   - Contains SPECIFIC requirements, obligations, or prohibitions
   - Explains WHAT must be done, HOW, and by WHOM
   - Provides actual compliance criteria, not just references
   - Contains concrete definitions, procedures, or thresholds

If this is an introductory/general section, return:
{{
    "contains_regulation": false,
    "confidence_score": 0.0,
    "section_summary": "Introductory/overview section - regulations mentioned but not detailed here",
    "is_introductory": true,
    "regulations": []
}}

---

If this section DOES contain detailed regulation information, provide a comprehensive JSON response with the following structure:

{{
    "contains_regulation": true/false,
    "confidence_score": 0.0-1.0,
    "section_summary": "Detailed summary of what this section covers",
    "is_introductory": false,
    
    "regulations": [
        {{
            "regulation_id": "Official ID (e.g., GDPR Article 5, ISO 27001:2022)",
            "regulation_name": "Full official name of the regulation",
            "regulation_type": "law | directive | regulation | standard | guideline | framework | policy | article | clause",
            
            "jurisdiction": {{
                "geographic_scope": "EU | US | UK | International | Global | Country-specific",
                "applicable_regions": ["List of specific regions/countries"],
                "cross_border_applicability": true/false
            }},
            
            "domain": {{
                "primary_domain": "Data Protection | Financial | Environmental | Health & Safety | Cybersecurity | AI Ethics | Consumer Protection | Employment | Tax | Trade",
                "sub_domains": ["List of specific sub-areas"],
                "industry_sectors": ["List of industries this applies to"]
            }},
            
            "description": {{
                "brief_summary": "One paragraph summary",
                "detailed_explanation": "Comprehensive explanation of the regulation",
                "purpose": "Why this regulation exists",
                "legislative_intent": "What the lawmakers intended to achieve"
            }},
            
            "scope": {{
                "what_it_covers": ["List of activities/processes covered"],
                "who_it_applies_to": {{
                    "target_entities": ["Organizations", "Individuals", "Specific roles"],
                    "entity_types": ["Private companies", "Public bodies", "Non-profits"],
                    "size_thresholds": "Any size requirements (e.g., companies with >250 employees)",
                    "geographic_presence": "Location requirements"
                }},
                "what_it_does_not_cover": ["Explicitly excluded items"]
            }},
            
            "requirements": {{
                "mandatory_obligations": ["List of MUST DO requirements"],
                "prohibited_actions": ["List of MUST NOT DO restrictions"],
                "conditional_requirements": ["Requirements that apply under certain conditions"],
                "documentation_requirements": ["Required records/documents"],
                "reporting_requirements": ["Required reports/notifications"],
                "timeline_requirements": ["Deadlines, response times, retention periods"]
            }},
            
            "restrictions": {{
                "general_restrictions": ["Overall limitations imposed"],
                "data_restrictions": ["Limits on data handling if applicable"],
                "operational_restrictions": ["Limits on business operations"],
                "technical_restrictions": ["Technical limitations required"],
                "geographic_restrictions": ["Location-based limitations"]
            }},
            
            "rights_granted": {{
                "individual_rights": ["Rights given to individuals"],
                "organizational_rights": ["Rights given to organizations"],
                "how_to_exercise_rights": ["Process to claim these rights"]
            }},
            
            "exceptions": {{
                "general_exceptions": ["When the regulation does NOT apply"],
                "conditional_exemptions": ["Partial exemptions under conditions"],
                "legitimate_interest_exceptions": ["Exceptions based on legitimate interests"],
                "public_interest_exceptions": ["Government/public sector exceptions"],
                "size_based_exceptions": ["Exemptions for small businesses etc."]
            }},
            
            "compliance_requirements": {{
                "technical_measures": ["Required technical implementations"],
                "organizational_measures": ["Required policies/procedures"],
                "security_measures": ["Security requirements"],
                "training_requirements": ["Staff training needed"],
                "audit_requirements": ["Audit/assessment requirements"],
                "certification_requirements": ["Required certifications"]
            }},
            
            "enforcement": {{
                "regulatory_authority": "Who enforces this",
                "penalties": {{
                    "financial_penalties": "Fines description and amounts",
                    "criminal_penalties": "Criminal consequences if any",
                    "administrative_penalties": "Administrative sanctions",
                    "reputational_consequences": "Public disclosure etc."
                }},
                "enforcement_mechanisms": ["How violations are detected/handled"]
            }},
            
            "dates": {{
                "effective_date": "When it came into force",
                "compliance_deadline": "When compliance was/is required",
                "review_date": "When it will be reviewed",
                "amendment_history": ["Previous changes"]
            }},
            
            "related_regulations": {{
                "parent_legislation": "Higher-level law this derives from",
                "related_articles": ["Other articles in same regulation"],
                "complementary_regulations": ["Other regulations that work together"],
                "superseded_regulations": ["What this replaced"]
            }},
            
            "practical_implications": {{
                "implementation_steps": ["Steps to achieve compliance"],
                "common_violations": ["Typical mistakes/violations"],
                "best_practices": ["Recommended approaches"],
                "compliance_checklist": ["Key items to verify"]
            }},
            
            "keywords": ["Relevant search terms"],
            "key_definitions": {{
                "term": "definition"
            }}
        }}
    ]
}}

IMPORTANT: 
- DO NOT extract regulations from introductory/overview sections
- Extract ONLY from sections with SPECIFIC, ACTIONABLE requirements
- If information is not available, use null instead of guessing
- Be extremely thorough - this will be used for compliance checking
- Include exact quotes where relevant
- Identify ALL restrictions, exceptions, and requirements mentioned

Return ONLY valid JSON."""

    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior legal and compliance expert. Extract regulatory details ONLY from sections with specific requirements. Skip introductory, summary, or overview sections that merely mention regulations without detailing them. Always respond with valid JSON only, no markdown formatting or code blocks."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        result["section_title"] = section["title"]
        result["original_content"] = section["content"][:500] + "..." if len(section["content"]) > 500 else section["content"]
        return result
        
    except Exception as e:
        return {
            "section_title": section["title"],
            "contains_regulation": False,
            "confidence_score": 0.0,
            "regulations": [],
            "section_summary": None,
            "error": str(e)
        }


def process_all_sections(
    sections: List[Dict[str, str]],
    model: str = "gpt-4.1",
    verbose: bool = True
) -> List[Dict]:
    """
    Process all document sections and extract regulations.
    
    Args:
        sections: List of section dicts with 'title' and 'content'
        model: OpenAI model to use
        verbose: Whether to print progress
    
    Returns:
        List of analysis results for each section
    """
    results = []
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🔍 RPEM: Processing {len(sections)} sections")
        print(f"{'='*60}\n")
    
    for i, section in enumerate(sections):
        if verbose:
            title_preview = section['title'][:50] + "..." if len(section['title']) > 50 else section['title']
            print(f"📖 [{i+1}/{len(sections)}] {title_preview}")
        
        analysis = extract_regulations_from_section(section, model)
        results.append(analysis)
        
        if verbose:
            if analysis.get("contains_regulation"):
                reg_count = len(analysis.get("regulations", []))
                print(f"   ✅ Found {reg_count} regulation(s)")
            else:
                print(f"   ⚪ No regulations found")
        
    return results


def collect_all_regulations(analysis_results: List[Dict]) -> List[Dict]:
    """
    Extract all regulations from analysis results into a flat list.
    
    Args:
        analysis_results: List of section analysis results
    
    Returns:
        List of all extracted regulations
    """
    all_regulations = []
    
    for result in analysis_results:
        if result.get("contains_regulation") and result.get("regulations"):
            for reg in result["regulations"]:
                reg["source_section"] = result.get("section_title")
                all_regulations.append(reg)
    
    return all_regulations


# ============================================================
# QUALITY FILTERING
# ============================================================

def calculate_quality_score(regulation: Dict) -> Dict:
    """
    Calculate a quality score for a regulation based on completeness.
    
    Args:
        regulation: Regulation dict
    
    Returns:
        Dict with score, issues, and recommendation
    """
    score = 0
    issues = []
    strengths = []
    
    # Critical fields (40 points)
    critical_fields = {
        "regulation_id": 10,
        "regulation_name": 10,
        "regulation_type": 10,
        "description": 10
    }
    
    for field, points in critical_fields.items():
        value = regulation.get(field)
        if value and value not in [None, "null", "", "N/A", "Unknown"]:
            if isinstance(value, dict):
                non_null = sum(1 for v in value.values() if v and v not in [None, "null", ""])
                score += points * (non_null / max(len(value), 1))
                strengths.append(f"✓ Has {field}")
            else:
                score += points
                strengths.append(f"✓ Has {field}")
        else:
            issues.append(f"✗ Missing: {field}")
    
    # Important fields (30 points)
    important_fields = {
        "jurisdiction": 6,
        "domain": 6,
        "scope": 6,
        "requirements": 6,
        "restrictions": 6
    }
    
    for field, points in important_fields.items():
        value = regulation.get(field)
        if value and value not in [None, "null", ""]:
            if isinstance(value, dict):
                non_null = sum(1 for v in value.values() if v and v not in [None, "null", ""])
                score += points * (non_null / max(len(value), 1))
            elif isinstance(value, list):
                score += points * (1 if len(value) > 0 else 0)
            else:
                score += points
        else:
            issues.append(f"⚠ Missing: {field}")
    
    # Supplementary fields (30 points)
    supplementary_fields = {
        "rights_granted": 5,
        "exceptions": 5,
        "compliance_requirements": 5,
        "enforcement": 5,
        "dates": 5,
        "keywords": 5
    }
    
    for field, points in supplementary_fields.items():
        value = regulation.get(field)
        if value and value not in [None, "null", ""]:
            score += points
    
    # Determine recommendation
    if score >= 70:
        recommendation = "KEEP"
        status = "🟢"
    elif score >= 40:
        recommendation = "REVIEW"
        status = "🟡"
    else:
        recommendation = "DISCARD"
        status = "🔴"
    
    return {
        "score": round(score, 1),
        "max_score": 100,
        "percentage": round(score, 1),
        "recommendation": recommendation,
        "status": status,
        "issues": issues,
        "strengths": strengths
    }


def filter_regulations_by_quality(
    regulations: List[Dict],
    min_score: float = 40,
    verbose: bool = True
) -> Dict:
    """
    Filter regulations based on quality score.
    
    Args:
        regulations: List of regulation dicts
        min_score: Minimum score to keep (0-100)
        verbose: Whether to print details
    
    Returns:
        Dict with kept, review, and discarded lists
    """
    kept = []
    review = []
    discarded = []
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"🔍 RPEM: Quality Filtering")
        print(f"{'='*60}")
        print(f"   Minimum score: {min_score}")
        print(f"   Regulations to analyze: {len(regulations)}\n")
    
    for reg in regulations:
        quality = calculate_quality_score(reg)
        reg["_quality_score"] = quality
        
        if quality["score"] >= 70:
            kept.append(reg)
        elif quality["score"] >= min_score:
            review.append(reg)
        else:
            discarded.append(reg)
    
    if verbose:
        print(f"{'='*60}")
        print(f"📊 FILTERING RESULTS")
        print(f"{'='*60}")
        print(f"   🟢 KEPT (score ≥ 70):      {len(kept):3d}")
        print(f"   🟡 REVIEW (score ≥ {min_score}):    {len(review):3d}")
        print(f"   🔴 DISCARDED (score < {min_score}): {len(discarded):3d}")
        print(f"{'='*60}")
    
    return {
        "kept": kept,
        "review": review,
        "discarded": discarded,
        "statistics": {
            "total": len(regulations),
            "kept_count": len(kept),
            "review_count": len(review),
            "discarded_count": len(discarded)
        }
    }


# ============================================================
# MAIN PROCESSING PIPELINE
# ============================================================

def process_regulation_document(
    pdf_path: str,
    output_path: Optional[str] = None,
    model: str = "gpt-4.1",
    min_quality_score: float = 40,
    verbose: bool = True
) -> Dict:
    """
    Complete pipeline to process a regulation document.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path to save results JSON
        model: OpenAI model to use
        min_quality_score: Minimum quality score for filtering
        verbose: Whether to print progress
    
    Returns:
        Dict with all processing results
    """
    if verbose:
        print(f"\n{'='*70}")
        print(f"🔍 ARCCS - RPEM: Regulatory Processing and Extraction Module")
        print(f"{'='*70}\n")
    
    # Step 1: Load and parse PDF
    elements = load_pdf_document(pdf_path)
    markdown_text = elements_to_markdown(elements)
    sections = split_into_sections(markdown_text)
    
    if verbose:
        print(f"📑 Split into {len(sections)} sections\n")
    
    # Step 2: Extract regulations from each section
    analysis_results = process_all_sections(sections, model, verbose)
    
    # Step 3: Collect all regulations
    all_regulations = collect_all_regulations(analysis_results)
    
    if verbose:
        print(f"\n📋 Total regulations extracted: {len(all_regulations)}")
    
    # Step 4: Filter by quality
    filtered = filter_regulations_by_quality(all_regulations, min_quality_score, verbose)
    
    # Prepare output
    output = {
        "document_analysis": {
            "source_file": pdf_path,
            "total_sections": len(sections),
            "sections_with_regulations": sum(1 for r in analysis_results if r.get("contains_regulation")),
            "total_regulations_extracted": len(all_regulations),
            "regulations_after_filtering": len(filtered["kept"]) + len(filtered["review"])
        },
        "section_analyses": analysis_results,
        "all_regulations": all_regulations,
        "filtered_regulations": filtered["kept"],
        "regulations_for_review": filtered["review"],
        "discarded_regulations": filtered["discarded"]
    }
    
    # Save if path provided
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        if verbose:
            print(f"\n💾 Results saved to '{output_path}'")
    
    return output


# ============================================================
# MODULE INFO
# ============================================================

def print_module_info():
    """Print RPEM module information."""
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                           ARCCS - RPEM                            ║
║        Regulatory Processing and Extraction Module                ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  Part of ARCCS (Automated Regulatory Compliance Classification    ║
║  System) - A multi-agent system for regulation-level compliance   ║
║  assessment.                                                      ║
║                                                                   ║
║  Functions:                                                       ║
║    • load_pdf_document()      - Load and parse PDF files          ║
║    • elements_to_markdown()   - Convert to markdown format        ║
║    • split_into_sections()    - Split by headers                  ║
║    • extract_regulations_from_section() - AI extraction           ║
║    • process_all_sections()   - Process entire document           ║
║    • filter_regulations_by_quality() - Quality filtering          ║
║    • process_regulation_document() - Complete pipeline            ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    print_module_info()

from typing import Dict, List

# 🔍 Filter functions for quality control of extracted regulations

def calculate_regulation_quality_score(regulation: Dict) -> Dict:
    """
    Calculate a quality score for a regulation based on completeness and validity.
    Returns a dict with score, reasons, and recommendation.
    """
    score = 0
    max_score = 100
    issues = []
    strengths = []
    
    # === CRITICAL FIELDS (40 points) ===
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
                # Check if dict has actual content
                non_null_values = [v for v in value.values() if v and v not in [None, "null", ""]]
                if len(non_null_values) > 0:
                    score += points
                    strengths.append(f"✓ {field} is present")
                else:
                    issues.append(f"✗ {field} is empty dict")
            else:
                score += points
                strengths.append(f"✓ {field} is present")
        else:
            issues.append(f"✗ Missing critical field: {field}")
    
    # === IMPORTANT FIELDS (30 points) ===
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
                non_null = sum(1 for v in value.values() if v and v not in [None, "null", "", []])
                total = len(value)
                if total > 0:
                    partial_score = points * (non_null / total)
                    score += partial_score
                    if non_null >= total * 0.5:
                        strengths.append(f"✓ {field} is {int(non_null/total*100)}% complete")
                    else:
                        issues.append(f"⚠ {field} is only {int(non_null/total*100)}% complete")
            elif isinstance(value, list):
                if len(value) > 0:
                    score += points
                    strengths.append(f"✓ {field} has {len(value)} items")
                else:
                    issues.append(f"⚠ {field} is empty list")
            else:
                score += points
        else:
            issues.append(f"⚠ Missing important field: {field}")
    
    # === SUPPLEMENTARY FIELDS (30 points) ===
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
            if isinstance(value, dict):
                non_null = sum(1 for v in value.values() if v and v not in [None, "null", "", []])
                if non_null > 0:
                    score += points * min(1, non_null / 2)  # At least 2 sub-fields for full points
            elif isinstance(value, list) and len(value) > 0:
                score += points
            else:
                score += points
    
    # === PENALTY FOR EXCESSIVE NULL VALUES ===
    def count_nulls(obj, depth=0):
        if depth > 5:  # Prevent infinite recursion
            return 0, 0
        null_count = 0
        total_count = 0
        
        if isinstance(obj, dict):
            for v in obj.values():
                if v in [None, "null", "", "N/A", "Unknown", []]:
                    null_count += 1
                    total_count += 1
                elif isinstance(v, (dict, list)):
                    n, t = count_nulls(v, depth + 1)
                    null_count += n
                    total_count += t
                else:
                    total_count += 1
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    n, t = count_nulls(item, depth + 1)
                    null_count += n
                    total_count += t
                elif item in [None, "null", "", "N/A"]:
                    null_count += 1
                    total_count += 1
                else:
                    total_count += 1
        
        return null_count, total_count
    
    null_count, total_count = count_nulls(regulation)
    null_ratio = null_count / total_count if total_count > 0 else 1
    
    if null_ratio > 0.7:
        penalty = 20
        score = max(0, score - penalty)
        issues.append(f"✗ Too many null values ({int(null_ratio*100)}% empty)")
    elif null_ratio > 0.5:
        penalty = 10
        score = max(0, score - penalty)
        issues.append(f"⚠ Many null values ({int(null_ratio*100)}% empty)")
    
    # === DETERMINE RECOMMENDATION ===
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
        "max_score": max_score,
        "percentage": round(score / max_score * 100, 1),
        "null_ratio": round(null_ratio * 100, 1),
        "recommendation": recommendation,
        "status": status,
        "issues": issues,
        "strengths": strengths
    }


def filter_regulations(regulations: List[Dict], 
                       min_score: float = 40,
                       show_details: bool = True) -> Dict:
    """
    Filter regulations based on quality score.
    
    Args:
        regulations: List of regulation dicts
        min_score: Minimum score to keep (0-100)
        show_details: Whether to print detailed analysis
    
    Returns:
        Dict with kept, review, and discarded regulations
    """
    kept = []
    review = []
    discarded = []
    
    print(f"\n{'='*70}")
    print(f"🔍 REGULATION QUALITY FILTER")
    print(f"{'='*70}")
    print(f"   Minimum score to keep: {min_score}")
    print(f"   Total regulations to analyze: {len(regulations)}")
    print(f"{'='*70}\n")
    
    for i, reg in enumerate(regulations):
        quality = calculate_regulation_quality_score(reg)
        reg["_quality_score"] = quality
        
        reg_name = reg.get("regulation_name", reg.get("regulation_id", f"Regulation {i+1}"))
        reg_name = reg_name[:50] + "..." if len(str(reg_name)) > 50 else reg_name
        
        if show_details:
            print(f"{quality['status']} [{quality['percentage']:5.1f}%] {reg_name}")
            print(f"   └─ Recommendation: {quality['recommendation']} | Null ratio: {quality['null_ratio']}%")
            
            if quality['issues'] and len(quality['issues']) <= 3:
                for issue in quality['issues'][:3]:
                    print(f"      {issue}")
            print()
        
        if quality["score"] >= 70:
            kept.append(reg)
        elif quality["score"] >= min_score:
            review.append(reg)
        else:
            discarded.append(reg)
    
    # Summary
    print(f"\n{'='*70}")
    print(f"📊 FILTER SUMMARY")
    print(f"{'='*70}")
    print(f"   🟢 KEPT (score ≥ 70):      {len(kept):3d} regulations")
    print(f"   🟡 REVIEW (score ≥ {min_score}):    {len(review):3d} regulations")
    print(f"   🔴 DISCARDED (score < {min_score}): {len(discarded):3d} regulations")
    print(f"{'='*70}")
    
    return {
        "kept": kept,
        "review": review,
        "discarded": discarded,
        "statistics": {
            "total": len(regulations),
            "kept_count": len(kept),
            "review_count": len(review),
            "discarded_count": len(discarded),
            "kept_percentage": round(len(kept) / len(regulations) * 100, 1) if regulations else 0,
            "avg_score": round(sum(r["_quality_score"]["score"] for r in regulations) / len(regulations), 1) if regulations else 0
        }
    }




def is_general_overview(regulation: Dict) -> bool:
    """
    Detect if a regulation entry is a general overview vs specific article.
    """
    indicators = 0
    
    # Check 1: No specific article number in ID
    reg_id = str(regulation.get("regulation_id", "")).lower()
    if "article" not in reg_id and "section" not in reg_id and "chapter" not in reg_id:
        indicators += 1
    
    # Check 2: Too many mandatory obligations (general overviews have many)
    requirements = regulation.get("requirements", {})
    mandatory = requirements.get("mandatory_obligations", [])
    if len(mandatory) > 10:
        indicators += 2  # Strong indicator
    
    # Check 3: Too many individual rights listed
    rights = regulation.get("rights_granted", {})
    individual_rights = rights.get("individual_rights", [])
    if len(individual_rights) > 8:
        indicators += 2  # Strong indicator
    
    # Check 4: Source section is intro/overview
    source = str(regulation.get("source_section", "")).lower()
    overview_keywords = ["april 2016", "regulation", "chapter i", "general provisions", "preamble"]
    if any(kw in source for kw in overview_keywords):
        indicators += 1
    
    # Check 5: Too many key definitions (overviews define everything)
    definitions = regulation.get("key_definitions", {})
    if len(definitions) > 8:
        indicators += 1
    
    return indicators >= 3


def separate_regulations(regulations: List[Dict]) -> Dict:
    """
    Separate general overviews from specific article regulations.
    """
    general = []
    specific = []
    
    for reg in regulations:
        if is_general_overview(reg):
            general.append(reg)
        else:
            specific.append(reg)
    
    print(f"\n📊 REGULATION SEPARATION")
    print(f"{'='*50}")
    print(f"   📚 General overviews: {len(general)}")
    print(f"   📄 Specific articles: {len(specific)}")
    print(f"{'='*50}")
    
    return {
        "general_overviews": general,
        "specific_articles": specific
    }

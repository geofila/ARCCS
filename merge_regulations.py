import openai
import json
from typing import List, Dict, Tuple

def merge_duplicate_regulations(
    regulations: List[Dict],
    api_key: str,
    model: str = "gpt-5.2",
    batch_size: int = 50
) -> Tuple[List[Dict], List[Dict]]:
    """
    Merge duplicate regulations by identifying exact duplicates and keeping 
    only the most specific/detailed version.
    
    Args:
        regulations: List of regulation dictionaries
        api_key: OpenAI API key
        model: Model to use (default gpt-5.2)
        batch_size: Number of regulations to process at once
        
    Returns:
        Tuple of (cleaned_regulations, deletion_log)
    """
    openai.api_key = api_key
    
    if len(regulations) <= 1:
        return regulations, []
    
    # Prepare simplified regulation summaries for the LLM
    reg_summaries = []
    for i, reg in enumerate(regulations):
        summary = {
            "index": i,
            "regulation_id": reg.get("regulation_id", "N/A"),
            "regulation_name": reg.get("regulation_name", "Unknown"),
            "regulation_type": reg.get("regulation_type", "N/A"),
            "source_section": reg.get("source_section", "N/A"),
            "description_brief": reg.get("description", {}).get("brief_summary", "")[:300] if isinstance(reg.get("description"), dict) else str(reg.get("description", ""))[:300],
            "requirements_summary": str(reg.get("requirements", {}))[:500]
        }
        reg_summaries.append(summary)
    
    # Process in batches if needed
    all_deletions = []
    
    for batch_start in range(0, len(reg_summaries), batch_size):
        batch = reg_summaries[batch_start:batch_start + batch_size]
        
        prompt = f"""You are a legal expert analyzing a list of extracted regulations for EXACT DUPLICATES.

These regulations were extracted from different sections of the same document. Some regulations appear multiple times because:
1. Introductory chapters mention all regulations of a law broadly
2. Later chapters explain the same regulation in more detail
3. The same article/regulation is referenced in multiple places

YOUR TASK: Identify ONLY EXACT DUPLICATES - regulations that refer to THE SAME SPECIFIC ARTICLE/CLAUSE.

IMPORTANT RULES:
- ONLY mark as duplicates if they refer to THE EXACT SAME regulation (same article number, same law)
- Keep the MORE SPECIFIC/DETAILED version (usually from later sections)
- Delete the LESS DETAILED version (usually from introductory/overview sections)
- DO NOT delete regulations that are SIMILAR but DIFFERENT (e.g., Article 5 vs Article 6)
- When in doubt, DO NOT delete

REGULATIONS TO ANALYZE:
{json.dumps(batch, indent=2, ensure_ascii=False)}

Return a JSON response with this structure:
{{
    "duplicates_found": [
        {{
            "delete_index": <index of regulation to DELETE>,
            "keep_index": <index of regulation to KEEP>,
            "regulation_id": "<the regulation ID they both refer to>",
            "reason": "<brief explanation why these are exact duplicates and why you chose to keep one over the other>"
        }}
    ],
    "analysis_notes": "<any general observations about the regulations>"
}}

Return ONLY regulations that are CLEARLY THE SAME. If unsure, do not include them.
Return ONLY valid JSON."""

        try:
            response = openai.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise legal analyst. Only identify EXACT duplicate regulations. Be conservative - when in doubt, do not mark as duplicate. Always respond with valid JSON only."
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
            
            for dup in result.get("duplicates_found", []):
                # Adjust indices for batch offset
                dup["delete_index"] = dup["delete_index"] + batch_start if batch_start > 0 else dup["delete_index"]
                dup["keep_index"] = dup["keep_index"] + batch_start if batch_start > 0 else dup["keep_index"]
                all_deletions.append(dup)
                
            print(f"   📦 Batch {batch_start//batch_size + 1}: Found {len(result.get('duplicates_found', []))} duplicates")
            
        except Exception as e:
            print(f"   ❌ Error processing batch: {str(e)}")
            continue
    
    # Build deletion log with full regulation info
    deletion_log = []
    indices_to_delete = set()
    
    for dup in all_deletions:
        delete_idx = dup["delete_index"]
        keep_idx = dup["keep_index"]
        
        if delete_idx < len(regulations) and keep_idx < len(regulations):
            deletion_log.append({
                "deleted_regulation": {
                    "index": delete_idx,
                    "regulation_id": regulations[delete_idx].get("regulation_id"),
                    "regulation_name": regulations[delete_idx].get("regulation_name"),
                    "source_section": regulations[delete_idx].get("source_section")
                },
                "kept_regulation": {
                    "index": keep_idx,
                    "regulation_id": regulations[keep_idx].get("regulation_id"),
                    "regulation_name": regulations[keep_idx].get("regulation_name"),
                    "source_section": regulations[keep_idx].get("source_section")
                },
                "reason": dup["reason"]
            })
            indices_to_delete.add(delete_idx)
    
    # Create cleaned list
    cleaned_regulations = [
        reg for i, reg in enumerate(regulations) 
        if i not in indices_to_delete
    ]
    
    return cleaned_regulations, deletion_log


def print_deduplication_report(
    original_count: int,
    cleaned_regulations: List[Dict],
    deletion_log: List[Dict]
):
    """Print a summary report of the deduplication process."""
    
    print(f"\n{'='*60}")
    print(f"📊 DEDUPLICATION REPORT")
    print(f"{'='*60}")
    print(f"   Original regulations: {original_count}")
    print(f"   After deduplication: {len(cleaned_regulations)}")
    print(f"   Duplicates removed: {len(deletion_log)}")
    print(f"   Reduction: {(len(deletion_log)/original_count)*100:.1f}%")
    
    if deletion_log:
        print(f"\n📋 DELETIONS:")
        for i, entry in enumerate(deletion_log, 1):
            print(f"\n   {i}. DELETED: {entry['deleted_regulation']['regulation_name']}")
            print(f"      ID: {entry['deleted_regulation']['regulation_id']}")
            print(f"      From section: {entry['deleted_regulation']['source_section'][:50]}...")
            print(f"      ➡️ KEPT version from: {entry['kept_regulation']['source_section'][:50]}...")
            print(f"      Reason: {entry['reason']}")
    
    print(f"\n{'='*60}")


def deduplicate_regulations(
    regulations: List[Dict],
    api_key: str,
    save_to_file: str = None,
    model: str = "gpt-4.1"
) -> Dict:
    """
    Main function to deduplicate regulations with full reporting.
    
    Args:
        regulations: List of regulation dictionaries
        api_key: OpenAI API key
        save_to_file: Optional path to save results
        model: Model to use
        
    Returns:
        Dictionary with cleaned_regulations, deletion_log, and summary
    """
    print(f"🔄 Starting deduplication of {len(regulations)} regulations...")
    
    cleaned, deletion_log = merge_duplicate_regulations(
        regulations=regulations,
        api_key=api_key,
        model=model
    )
    
    print_deduplication_report(len(regulations), cleaned, deletion_log)
    
    result = {
        "cleaned_regulations": cleaned,
        "deletion_log": deletion_log,
        "summary": {
            "original_count": len(regulations),
            "cleaned_count": len(cleaned),
            "duplicates_removed": len(deletion_log)
        }
    }
    
    if save_to_file:
        with open(save_to_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to '{save_to_file}'")
    
    return result

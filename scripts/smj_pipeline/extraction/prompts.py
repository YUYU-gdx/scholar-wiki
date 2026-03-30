EXTRACTION_SYSTEM_PROMPT = """You normalize localized SMJ evidence into strict JSON for audit-friendly downstream parsing.
Return JSON only with the required top-level keys and list values.
"""


def build_extraction_prompt(evidence_json: str) -> str:
    return (
        EXTRACTION_SYSTEM_PROMPT.strip()
        + "\n\nRequired keys: relations, variable_level_theory_grounding, "
        + "relation_level_theory_grounding, hypotheses, citations.\n"
        + "Evidence spans JSON:\n"
        + evidence_json
    )

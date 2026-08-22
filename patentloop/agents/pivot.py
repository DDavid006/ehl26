"""Expert redesign/pivot agent."""

PIVOT_SCHEMA = {"name": "pivot", "schema": {"type": "object", "required": ["new_idea_text", "changed_elements", "avoided_claims", "rationale"], "properties": {"new_idea_text": {"type": "string"}, "changed_elements": {"type": "array"}, "avoided_claims": {"type": "array"}, "rationale": {"type": "string"}}}}


def pivot_idea(llm, current_idea: str, field: str, persona_hint: str, collisions: list[dict], closest: list[dict], previous: list[str]):
    output = llm.chat(
        f"Act as an expert in {field} ({persona_hint}). Produce a technically plausible non-repeating redesign.\n"
        + str({"current_idea": current_idea, "collisions": collisions, "closest_papers": closest, "previous_pivots": previous}),
        PIVOT_SCHEMA,
        agent="pivot",
    )
    return output, getattr(llm, "last_log_path", None)

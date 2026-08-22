"""Hard feasibility and claim-scope gate."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import re

STRUCTURE_WORDS = re.compile(r"\b(compris(?:es|ing)|module|sensor|controller|processor|configured|steps?|receiv(?:es|ing)|determining|generating|coupled)\b", re.I)
ASPIRATION_WORDS = re.compile(r"\b(an app|use ai to optimize|make the world|platform for|improve .* experience)\b", re.I)


def rule_checks(extracted: dict) -> dict:
    elements = extracted.get("elements", [])
    text = " ".join(item.get("text", "") for item in elements)
    return {
        "element_count": len(elements) >= 3,
        "concrete_language": bool(STRUCTURE_WORDS.search(text)),
        "not_aspiration": not bool(ASPIRATION_WORDS.search(text)),
    }


def feasibility_gate(extracted: dict, judges: list[dict]) -> dict:
    rules = rule_checks(extracted)
    judge_results = [
        item.get("decision", item.get("result", "fail")).lower() == "pass"
        for item in judges
    ]
    feasible = bool(judge_results and judge_results[0] and all(rules.values()))
    scoped = bool(len(judge_results) > 1 and judge_results[1] and all(rules.values()))
    return {
        "feasible": feasible,
        "scoped": scoped,
        "rules": rules,
        "judges": judges,
    }


class FeasibilityAgent:
    def __init__(self, llm):
        self.llm = llm

    def run(self, idea_text: str, extracted: dict) -> tuple[dict, list[str]]:
        jobs = (
            ("feasibility_physical", "Judge doable: fail for known physical/engineering constraints or commoditized restatements."),
            ("feasibility_scope", "Judge scoped: pass only if mechanism, structure, or method steps support a claim."),
        )
        def judge(job):
            name, prompt = job
            output = self.llm.chat(prompt + "\n" + str({"idea": idea_text, "extracted": extracted}), {"name": name, "schema": {"type": "object", "required": ["decision", "reasoning"], "properties": {"decision": {"type": "string"}, "reasoning": {"type": "string"}}}}, agent=name)
            return output, getattr(self.llm, "last_log_path", None)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(judge, jobs))
        outputs = [output for output, _ in results]
        paths = [path for _, path in results if path]
        result = feasibility_gate(extracted, outputs)
        result["feasible"] = result["feasible"] and result["scoped"]
        return result, paths

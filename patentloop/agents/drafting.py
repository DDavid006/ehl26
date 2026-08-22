"""Provisional application markdown and local PDF rendering."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


DRAFT_SCHEMA = {"name": "draft_application", "schema": {"type": "object", "required": ["title", "field", "background", "summary", "detailed_description", "claims", "why_novel"], "properties": {key: {"type": "string"} for key in ("title", "field", "background", "summary", "detailed_description", "claims", "why_novel")}}}


def render_pdf(markdown: str, path: Path) -> None:
    styles = getSampleStyleSheet()
    document = SimpleDocTemplate(str(path), pagesize=LETTER, rightMargin=inch, leftMargin=inch)
    story = []
    for block in markdown.split("\n\n"):
        text = block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        story.extend([Paragraph(text, styles["BodyText"]), Spacer(1, 8)])
    document.build(story)


class DraftingAgent:
    def __init__(self, llm):
        self.llm = llm

    def run(self, idea_text: str, extracted: dict, research: dict, patents: dict, *, run_dir) -> dict:
        output = self.llm.chat(
            "Write a complete provisional patent application draft. Include one independent and at least three dependent claims, and cite only supplied prior art.\n"
            + str({"idea": idea_text, "extracted": extracted, "research": research, "patents": patents}),
            DRAFT_SCHEMA,
            agent="drafting",
        )
        claims = output.get("claims", "")
        markdown = "\n\n".join([
            f"# {output.get('title', 'PatentLoop Draft')}",
            "**Drafting aid, not legal advice.**",
            f"## Field\n{output.get('field', '')}",
            f"## Background\n{output.get('background', '')}",
            f"## Summary\n{output.get('summary', '')}",
            f"## Detailed Description\n{output.get('detailed_description', '')}",
            f"## Claims\n{claims}",
            f"## Why This Is Novel\n{output.get('why_novel', '')}",
        ])
        run_path = Path(run_dir)
        md_path, pdf_path = run_path / "draft_application.md", run_path / "draft_application.pdf"
        md_path.write_text(markdown + "\n")
        render_pdf(markdown, pdf_path)
        path = getattr(self.llm, "last_log_path", None)
        return {"markdown_path": str(md_path), "pdf_path": str(pdf_path), "llm_paths": [path] if path else [], "content": markdown}

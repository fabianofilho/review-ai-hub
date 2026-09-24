"""
AI Screening Service.

Uses OpenAI to pre-screen articles based on inclusion/exclusion criteria.
For title/abstract phase: sends text. For full-text phase: sends PDF.
"""

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import LoggerMixin
from app.infrastructure.storage.base import StorageAdapter
from app.models.article import Article, ArticleFile
from app.models.extraction import AISuggestion
from app.repositories.screening_repository import (
    ScreeningConfigRepository,
    ScreeningRunRepository,
)
from app.services.openai_service import OpenAIService

from sqlalchemy import select, and_


SCREENING_SYSTEM_PROMPT = """\
You are a systematic review screening assistant. Your task is to evaluate whether \
a scientific article meets the inclusion criteria for a systematic review.

Given the article information and the screening criteria, evaluate each criterion \
and provide your overall screening decision.

Respond with a JSON object containing:
- decision: "include", "exclude", or "maybe"
- relevance_score: a float between 0.0 and 1.0 indicating relevance
- reasoning: brief explanation of your decision (2-3 sentences)
- criteria_evaluations: array of objects, one per criterion, each with:
  - criterion_id: the criterion ID
  - met: true/false/null (null if unable to determine)
  - reasoning: brief explanation

Be conservative: when in doubt, use "maybe" rather than "exclude".\
"""

SCREENING_RESULT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "screening_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["include", "exclude", "maybe"]},
                "relevance_score": {"type": "number"},
                "reasoning": {"type": "string"},
                "criteria_evaluations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion_id": {"type": "string"},
                            "met": {"type": ["boolean", "null"]},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["criterion_id", "met", "reasoning"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["decision", "relevance_score", "reasoning", "criteria_evaluations"],
            "additionalProperties": False,
        },
    },
}


class AIScreeningService(LoggerMixin):
    """AI-powered article screening."""

    def __init__(
        self,
        db: AsyncSession,
        user_id: str | UUID,
        storage: StorageAdapter,
        trace_id: str | None = None,
        openai_api_key: str | None = None,
    ):
        self.db = db
        self.user_id = str(user_id)
        self.storage = storage
        self.trace_id = trace_id
        self.openai = OpenAIService(trace_id=trace_id, api_key=openai_api_key)
        self.config_repo = ScreeningConfigRepository(db)
        self.run_repo = ScreeningRunRepository(db)

    async def screen_article(
        self,
        project_id: UUID,
        article_id: UUID,
        phase: str,
        model: str = "gpt-4o-mini",
    ) -> AISuggestion:
        """
        AI-screen a single article.

        For title_abstract: uses title + abstract text.
        For full_text: uses the PDF via Responses API.
        """
        # Get config with criteria
        config = await self.config_repo.get_by_project_and_phase(project_id, phase)
        if not config:
            raise ValueError(f"No screening config for phase {phase}")

        # Get article (must belong to the project being screened)
        article = await self.db.get(Article, article_id)
        if not article or str(article.project_id) != str(project_id):
            raise ValueError(f"Article {article_id} not found")

        # Build criteria prompt
        criteria_text = self._build_criteria_prompt(config.criteria)

        if phase == "title_abstract":
            result = await self._screen_title_abstract(article, criteria_text, model)
        else:
            result = await self._screen_full_text(
                article, project_id, criteria_text, model
            )

        # Parse result
        data = json.loads(result["output_text"]) if isinstance(result.get("output_text"), str) else result.get("output_text", {})

        # Create AI suggestion
        suggestion = AISuggestion(
            suggested_value=data,
            confidence_score=data.get("relevance_score"),
            reasoning=data.get("reasoning"),
            status="pending",
            metadata_={
                "phase": phase,
                "model": model,
                "input_tokens": result.get("input_tokens", 0),
                "output_tokens": result.get("output_tokens", 0),
                "article_id": str(article_id),
            },
        )
        self.db.add(suggestion)
        await self.db.flush()
        await self.db.refresh(suggestion)

        return suggestion

    async def screen_batch(
        self,
        project_id: UUID,
        article_ids: list[UUID],
        phase: str,
        model: str = "gpt-4o-mini",
    ) -> dict:
        """
        AI-screen a batch of articles.

        Creates a ScreeningRun for tracking. Returns run results.
        """
        run = await self.run_repo.create_run(
            project_id=project_id,
            phase=phase,
            stage="ai_screen_batch",
            created_by=UUID(self.user_id),
            parameters={
                "article_ids": [str(a) for a in article_ids],
                "model": model,
            },
        )
        await self.run_repo.start_run(run.id)

        success_count = 0
        fail_count = 0
        suggestion_ids = []

        for article_id in article_ids:
            try:
                suggestion = await self.screen_article(
                    project_id, article_id, phase, model
                )
                # Link suggestion to the run
                suggestion.screening_run_id = run.id
                await self.db.flush()

                suggestion_ids.append(str(suggestion.id))
                success_count += 1
            except Exception as e:
                fail_count += 1
                self.logger.error(
                    "ai_screening_article_error",
                    trace_id=self.trace_id,
                    article_id=str(article_id),
                    error=str(e),
                )

        results = {
            "success_count": success_count,
            "fail_count": fail_count,
            "suggestion_ids": suggestion_ids,
        }

        await self.run_repo.complete_run(run.id, results)
        return results

    def _build_criteria_prompt(self, criteria: list | dict) -> str:
        """Build a prompt section from screening criteria."""
        if not criteria:
            return "No specific criteria provided. Evaluate general relevance."

        lines = ["Screening criteria:"]
        items = criteria if isinstance(criteria, list) else []
        for c in items:
            criterion_type = c.get("type", "inclusion").upper()
            label = c.get("label", "")
            desc = c.get("description", "")
            lines.append(f"- [{criterion_type}] {label}: {desc}")

        return "\n".join(lines)

    async def _screen_title_abstract(
        self, article: Article, criteria_text: str, model: str
    ) -> dict:
        """Screen using title + abstract (chat completion)."""
        user_prompt = f"""Evaluate this article for inclusion in the systematic review.

Title: {article.title or 'Not available'}

Abstract: {article.abstract or 'Not available'}

Authors: {', '.join(article.authors) if article.authors else 'Not available'}
Year: {article.publication_year or 'Not available'}
Journal: {article.journal_title or 'Not available'}

{criteria_text}"""

        content = await self.openai.chat_completion(
            messages=[
                {"role": "system", "content": SCREENING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            response_format=SCREENING_RESULT_SCHEMA,
        )

        return {"output_text": content, "input_tokens": 0, "output_tokens": 0}

    async def _screen_full_text(
        self,
        article: Article,
        project_id: UUID,
        criteria_text: str,
        model: str,
    ) -> dict:
        """Screen using full PDF via Responses API."""
        # Find the main PDF
        result = await self.db.execute(
            select(ArticleFile).where(
                and_(
                    ArticleFile.article_id == article.id,
                    ArticleFile.file_role == "MAIN",
                )
            )
        )
        pdf_file = result.scalar_one_or_none()

        if not pdf_file:
            # Fallback to title/abstract
            return await self._screen_title_abstract(article, criteria_text, model)

        pdf_bytes = await self.storage.download("articles", pdf_file.storage_key)

        user_prompt = f"""Evaluate this article for inclusion in the systematic review based on the full text.

{criteria_text}"""

        return await self.openai.responses_api_with_pdf(
            pdf_data=pdf_bytes,
            system_prompt=SCREENING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_format=SCREENING_RESULT_SCHEMA,
            model=model,
            filename=pdf_file.original_filename or "article.pdf",
        )

    async def close(self) -> None:
        """Cleanup resources."""
        await self.openai.close()

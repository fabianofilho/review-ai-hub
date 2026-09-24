"""
PDF Metadata Extraction Service.

Uses OpenAI Responses API to extract bibliographic metadata from a PDF.
"""

import json

from app.core.logging import LoggerMixin
from app.schemas.article_import import ExtractedArticleMetadata, PDFMetadataExtractionResponse
from app.services.openai_service import OpenAIService

SYSTEM_PROMPT = """\
You are a bibliographic metadata extraction assistant. Given a scientific article PDF, \
extract the following metadata fields as accurately as possible. Only extract information \
that is clearly present in the document. Return null for any field you cannot determine.

Fields to extract:
- title: Full article title
- abstract: Complete abstract text
- authors: List of author names in "LastName, FirstName" format (or full name if not separable)
- publication_year: Year of publication (integer)
- publication_month: Month of publication (integer 1-12, if available)
- journal_title: Name of the journal or publication venue
- journal_issn: ISSN of the journal (if shown)
- volume: Journal volume
- issue: Journal issue number
- pages: Page range (e.g. "123-145")
- doi: Digital Object Identifier (just the DOI, not the full URL)
- pmid: PubMed ID (if shown)
- pmcid: PubMed Central ID (if shown)
- keywords: List of author keywords or index keywords
- article_type: Type of article (e.g. "Original Article", "Review", "Case Report", "Letter")
- language: Language of the article (e.g. "English", "Portuguese")
- url_landing: URL to the article landing page (if shown)
- study_design: Study design (e.g. "Randomized Controlled Trial", "Cohort Study", "Cross-sectional", "Systematic Review")

Return the result as a JSON object with these exact field names.\
"""

USER_PROMPT = "Extract all bibliographic metadata from this scientific article PDF."


# JSON schema for structured output
METADATA_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_article_metadata",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": ["string", "null"]},
                "abstract": {"type": ["string", "null"]},
                "authors": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "publication_year": {"type": ["integer", "null"]},
                "publication_month": {"type": ["integer", "null"]},
                "journal_title": {"type": ["string", "null"]},
                "journal_issn": {"type": ["string", "null"]},
                "volume": {"type": ["string", "null"]},
                "issue": {"type": ["string", "null"]},
                "pages": {"type": ["string", "null"]},
                "doi": {"type": ["string", "null"]},
                "pmid": {"type": ["string", "null"]},
                "pmcid": {"type": ["string", "null"]},
                "keywords": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "article_type": {"type": ["string", "null"]},
                "language": {"type": ["string", "null"]},
                "url_landing": {"type": ["string", "null"]},
                "study_design": {"type": ["string", "null"]},
            },
            "required": [
                "title",
                "abstract",
                "authors",
                "publication_year",
                "publication_month",
                "journal_title",
                "journal_issn",
                "volume",
                "issue",
                "pages",
                "doi",
                "pmid",
                "pmcid",
                "keywords",
                "article_type",
                "language",
                "url_landing",
                "study_design",
            ],
            "additionalProperties": False,
        },
    },
}


class PDFMetadataExtractionService(LoggerMixin):
    """Extracts article metadata from PDF using OpenAI."""

    def __init__(
        self,
        trace_id: str | None = None,
        openai_api_key: str | None = None,
    ):
        self.trace_id = trace_id
        self.openai = OpenAIService(trace_id=trace_id, api_key=openai_api_key)

    async def extract_metadata(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
        model: str = "gpt-4o-mini",
    ) -> PDFMetadataExtractionResponse:
        """
        Extract bibliographic metadata from a PDF.

        Args:
            pdf_bytes: Raw PDF bytes.
            filename: Original filename.
            model: OpenAI model to use.

        Returns:
            PDFMetadataExtractionResponse with extracted metadata.
        """
        self.logger.info(
            "pdf_metadata_extraction_start",
            trace_id=self.trace_id,
            filename=filename,
            pdf_size_bytes=len(pdf_bytes),
            model=model,
        )

        result = await self.openai.responses_api_with_pdf(
            pdf_data=pdf_bytes,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT,
            response_format=METADATA_JSON_SCHEMA,
            model=model,
            filename=filename,
        )

        output_text = result.get("output_text")
        if not output_text:
            self.logger.error(
                "pdf_metadata_extraction_empty_response",
                trace_id=self.trace_id,
            )
            raise ValueError("OpenAI returned empty response for PDF metadata extraction")

        data = json.loads(output_text)
        metadata = ExtractedArticleMetadata.model_validate(data)

        self.logger.info(
            "pdf_metadata_extraction_complete",
            trace_id=self.trace_id,
            title=metadata.title[:80] if metadata.title else None,
            has_abstract=metadata.abstract is not None,
            authors_count=len(metadata.authors) if metadata.authors else 0,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            duration_ms=result.get("duration_ms", 0),
        )

        return PDFMetadataExtractionResponse(
            metadata=metadata,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            duration_ms=result.get("duration_ms", 0),
        )

    async def close(self) -> None:
        """Cleanup resources."""
        await self.openai.close()

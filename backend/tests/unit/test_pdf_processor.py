"""
PDF Processor Unit Tests.
"""

import pytest

from app.services.pdf_processor import PageContent, PDFMetadata, PDFProcessor, TextChunk


@pytest.fixture
def pdf_processor() -> PDFProcessor:
    """Fixture para instância do PDFProcessor."""
    return PDFProcessor()


@pytest.fixture
def valid_pdf_bytes() -> bytes:
    """
    Fixture com PDF válido para testes.

    Este é um PDF mínimo válido com uma página contendo "Test PDF".
    """
    return b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 12 Tf 100 700 Td (Test PDF Content) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000270 00000 n 
0000000363 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
444
%%EOF"""


class TestPDFProcessor:
    """Testes para PDFProcessor."""

    @pytest.mark.asyncio
    async def test_extract_text_returns_string(
        self,
        pdf_processor: PDFProcessor,
        valid_pdf_bytes: bytes,
    ) -> None:
        """Test que extract_text retorna string."""
        text = await pdf_processor.extract_text(valid_pdf_bytes)

        assert isinstance(text, str)

    @pytest.mark.asyncio
    async def test_extract_pages_returns_list(
        self,
        pdf_processor: PDFProcessor,
        valid_pdf_bytes: bytes,
    ) -> None:
        """Test que extract_pages retorna lista de PageContent."""
        pages = await pdf_processor.extract_pages(valid_pdf_bytes)

        assert isinstance(pages, list)
        assert len(pages) >= 1
        assert all(isinstance(p, PageContent) for p in pages)

    @pytest.mark.asyncio
    async def test_get_metadata_returns_pdfmetadata(
        self,
        pdf_processor: PDFProcessor,
        valid_pdf_bytes: bytes,
    ) -> None:
        """Test que get_metadata retorna PDFMetadata."""
        metadata = await pdf_processor.get_metadata(valid_pdf_bytes)

        assert isinstance(metadata, PDFMetadata)
        assert metadata.pages >= 1
        assert isinstance(metadata.md5_hash, str)
        assert len(metadata.md5_hash) == 32  # MD5 tem 32 caracteres hex

    @pytest.mark.asyncio
    async def test_extract_text_chunked(
        self,
        pdf_processor: PDFProcessor,
        valid_pdf_bytes: bytes,
    ) -> None:
        """Test que extract_text_chunked retorna lista de chunks."""
        chunks = await pdf_processor.extract_text_chunked(
            valid_pdf_bytes,
            max_chars_per_chunk=1000,
        )

        assert isinstance(chunks, list)
        assert all(isinstance(c, TextChunk) for c in chunks)

    @pytest.mark.asyncio
    async def test_extract_text_invalid_pdf_raises_error(
        self,
        pdf_processor: PDFProcessor,
    ) -> None:
        """Test que PDF inválido levanta ValueError."""
        invalid_pdf = b"not a pdf file"

        with pytest.raises(ValueError, match="Failed to extract"):
            await pdf_processor.extract_text(invalid_pdf)

    def test_estimate_tokens(self, pdf_processor: PDFProcessor) -> None:
        """Test estimativa de tokens."""
        text = "Hello world! " * 100  # ~1300 caracteres

        tokens = pdf_processor.estimate_tokens(text)

        # Aproximadamente 4 caracteres por token
        assert 200 < tokens < 500

    def test_clean_text(self, pdf_processor: PDFProcessor) -> None:
        """Test limpeza de texto."""
        dirty_text = "Hello\x00World\n\n\n\nTest"

        clean = pdf_processor._clean_text(dirty_text)

        assert "\x00" not in clean
        assert "\n\n\n\n" not in clean


class TestSectionDetection:
    """Testes para detecção de seções."""

    @pytest.mark.asyncio
    async def test_detect_sections_finds_common_sections(
        self,
        pdf_processor: PDFProcessor,
    ) -> None:
        """Test que detecta seções comuns de artigos científicos."""
        text = """
        Abstract
        This is the abstract.
        
        Introduction
        This is the introduction.
        
        Methods
        This describes the methods.
        
        Results
        These are the results.
        
        Discussion
        This is the discussion.
        
        Conclusion
        This is the conclusion.
        
        References
        1. Reference one.
        """

        sections = await pdf_processor.detect_sections(text)

        assert len(sections) >= 5
        section_names = [s["name"].lower() for s in sections]

        assert any("abstract" in n for n in section_names)
        assert any("introduction" in n for n in section_names)
        assert any("method" in n for n in section_names)

    @pytest.mark.asyncio
    async def test_extract_section_text(
        self,
        pdf_processor: PDFProcessor,
    ) -> None:
        """Test extração de texto de uma seção."""
        text = """
        Introduction
        This is the introduction content.
        It has multiple lines.
        
        Methods
        This is the methods section.
        """

        intro_text = await pdf_processor.extract_section_text(text, "Introduction", "Methods")

        assert "introduction content" in intro_text.lower()
        assert "methods section" not in intro_text.lower()

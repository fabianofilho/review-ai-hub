"""
Unit tests for ArticlesExportService and its format builders.

Covers:
- CSV, RIS and RDF builders (content, escaping, truncation, optional fields)
- Folder name sanitization and RIS author formatting helpers
- run_export for every file scope (none, main_only, all), including ZIP entries
  and the skipped files manifest when storage downloads fail
- run_export_async upload and signed URL flow

The storage adapter and the article repository are mocked; no database or
network access is needed.
"""

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage.base import StorageAdapter, StorageError
from app.models.article import Article, ArticleFile
from app.repositories.project_repository import ProjectMemberRepository
from app.services.articles_export_service import (
    ArticlesExportService,
    _authors_ris,
    _build_csv,
    _build_rdf,
    _build_ris,
    _sanitize_folder_name,
    _xml_esc,
)

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC_NS = "http://purl.org/dc/elements/1.1/"
BIBO_NS = "http://purl.org/ontology/bibo/"

CSV_HEADER = [
    "title",
    "authors",
    "publication_year",
    "journal_title",
    "doi",
    "pmid",
    "keywords",
    "abstract",
]


# =================== FACTORIES ===================


def make_article(
    *,
    article_id: UUID | None = None,
    title: str = "Deep learning for sepsis prediction",
    authors: list[str] | None = None,
    publication_year: int | None = 2021,
    journal_title: str | None = "Critical Care",
    doi: str | None = "10.1000/xyz123",
    pmid: str | None = "123456",
    keywords: list[str] | None = None,
    abstract: str | None = "Background and methods.",
    files: list[ArticleFile] | None = None,
) -> Article:
    """Build a transient Article instance (never added to a session)."""
    article = Article(
        id=article_id or uuid4(),
        project_id=uuid4(),
        title=title,
        authors=["Smith J", "Doe A"] if authors is None else authors,
        publication_year=publication_year,
        journal_title=journal_title,
        doi=doi,
        pmid=pmid,
        keywords=["sepsis", "machine learning"] if keywords is None else keywords,
        abstract=abstract,
    )
    article.files = files or []
    return article


def make_file(
    storage_key: str,
    *,
    original_filename: str | None = None,
    file_role: str | None = "MAIN",
    file_id: UUID | None = None,
) -> ArticleFile:
    """Build a transient ArticleFile instance."""
    return ArticleFile(
        id=file_id or uuid4(),
        storage_key=storage_key,
        original_filename=original_filename,
        file_role=file_role,
        file_type="application/pdf",
    )


def make_storage(blobs: dict[str, bytes] | None = None) -> MagicMock:
    """
    Build a StorageAdapter mock whose download serves the given blobs.

    Keys missing from ``blobs`` raise StorageError, emulating a failed download.
    """
    blobs = blobs or {}
    storage = MagicMock(spec=StorageAdapter)

    async def download(bucket: str, path: str) -> bytes:
        if path in blobs:
            return blobs[path]
        raise StorageError("Download failed: object not found", bucket, path)

    storage.download = AsyncMock(side_effect=download)
    storage.upload = AsyncMock(return_value="exports/uploaded.zip")
    storage.get_signed_url = AsyncMock(return_value="https://storage.test/signed/export.zip")
    return storage


def make_service(
    articles: list[Article],
    storage: MagicMock | None = None,
) -> tuple[ArticlesExportService, AsyncMock]:
    """Build the service with a patched repository returning ``articles``."""
    service = ArticlesExportService(
        db=AsyncMock(spec=AsyncSession),
        user_id="user-123",
        storage=storage or make_storage(),
        trace_id="trace-abc",
    )
    repo = MagicMock()
    repo.get_by_ids = AsyncMock(return_value=articles)
    service._articles_repo = MagicMock(return_value=repo)
    return service, repo.get_by_ids


def parse_csv(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8"))))


def open_zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


# =================== HELPERS ===================


class TestSanitizeFolderName:
    """Tests for _sanitize_folder_name."""

    def test_prefixes_id_and_replaces_whitespace(self):
        article_id = uuid4()

        result = _sanitize_folder_name("  Deep   learning in sepsis  ", article_id)

        assert result == f"{article_id}_Deep_learning_in_sepsis"

    def test_control_characters_are_removed_before_whitespace_collapse(self):
        article_id = uuid4()

        result = _sanitize_folder_name("Deep\tlearning\nstudy", article_id)

        assert result == f"{article_id}_Deeplearningstudy"

    def test_removes_invalid_path_characters(self):
        article_id = uuid4()

        result = _sanitize_folder_name('a<b>c:d"e/f\\g|h?i*j\x01k', article_id)

        assert result == f"{article_id}_abcdefghijk"

    def test_truncates_to_80_characters(self):
        article_id = uuid4()

        result = _sanitize_folder_name("x" * 200, article_id)

        assert result == f"{article_id}_{'x' * 80}"

    @pytest.mark.parametrize("title", [None, "", "   ", '<>:"/\\|?*'])
    def test_falls_back_to_article_when_title_is_empty(self, title):
        article_id = uuid4()

        assert _sanitize_folder_name(title, article_id) == f"{article_id}_article"


class TestAuthorsRis:
    """Tests for _authors_ris."""

    @pytest.mark.parametrize("authors", [None, []])
    def test_returns_empty_list_without_authors(self, authors):
        assert _authors_ris(authors) == []

    def test_strips_and_drops_blank_entries(self):
        result = _authors_ris(["  Smith J ", "", "   ", "Doe A"])

        assert result == ["Smith J", "Doe A"]


class TestXmlEscape:
    """Tests for _xml_esc."""

    def test_escapes_special_characters(self):
        assert _xml_esc('A & B <c> "d"') == "A &amp; B &lt;c&gt; &quot;d&quot;"

    def test_ampersand_is_escaped_first(self):
        # An already escaped entity must be escaped again, not left as-is.
        assert _xml_esc("&lt;") == "&amp;lt;"


# =================== CSV ===================


class TestBuildCsv:
    """Tests for _build_csv."""

    def test_header_and_row_values(self):
        article = make_article(abstract="Line one\nLine two")

        rows = parse_csv(_build_csv([article]))

        assert rows[0] == CSV_HEADER
        assert rows[1] == [
            "Deep learning for sepsis prediction",
            "Smith J; Doe A",
            "2021",
            "Critical Care",
            "10.1000/xyz123",
            "123456",
            "sepsis; machine learning",
            "Line one Line two",
        ]

    def test_missing_fields_are_empty_strings(self):
        article = make_article(
            authors=[],
            publication_year=None,
            journal_title=None,
            doi=None,
            pmid=None,
            keywords=[],
            abstract=None,
        )

        rows = parse_csv(_build_csv([article]))

        assert rows[1] == ["Deep learning for sepsis prediction", "", "", "", "", "", "", ""]

    def test_quotes_values_with_commas_and_quotes(self):
        article = make_article(title='Risk, "outcomes" and costs')

        content = _build_csv([article]).decode("utf-8")

        assert '"Risk, ""outcomes"" and costs"' in content
        assert parse_csv(content.encode("utf-8"))[1][0] == 'Risk, "outcomes" and costs'

    def test_one_row_per_article_in_order(self):
        articles = [make_article(title=f"Title {i}") for i in range(3)]

        rows = parse_csv(_build_csv(articles))

        assert [r[0] for r in rows[1:]] == ["Title 0", "Title 1", "Title 2"]

    def test_empty_list_only_has_header(self):
        assert parse_csv(_build_csv([])) == [CSV_HEADER]

    def test_output_is_utf8(self):
        article = make_article(title="Naïve Bayes in Zürich cohorts")

        content = _build_csv([article])

        assert "Zürich".encode() in content


# =================== RIS ===================


class TestBuildRis:
    """Tests for _build_ris."""

    def test_full_record(self):
        article = make_article()

        lines = _build_ris([article]).decode("utf-8").split("\r\n")

        assert lines == [
            "TY  - JOUR",
            "TI  - Deep learning for sepsis prediction",
            "AU  - Smith J",
            "AU  - Doe A",
            "PY  - 2021",
            "JO  - Critical Care",
            "AB  - Background and methods.",
            "DO  - 10.1000/xyz123",
            "AN  - 123456",
            "ER  - ",
        ]

    def test_optional_tags_are_omitted_when_missing(self):
        article = make_article(
            authors=[],
            publication_year=None,
            journal_title=None,
            doi=None,
            pmid=None,
            abstract=None,
        )

        lines = _build_ris([article]).decode("utf-8").split("\r\n")

        assert lines == ["TY  - JOUR", "TI  - Deep learning for sepsis prediction", "ER  - "]

    def test_newlines_are_flattened(self):
        article = make_article(
            title="Title\r\nsecond line",
            journal_title="Journal\nof tests",
            abstract="First\r\nsecond",
        )

        lines = _build_ris([article]).decode("utf-8").split("\r\n")

        assert "TI  - Title second line" in lines
        assert "JO  - Journal of tests" in lines
        assert "AB  - First second" in lines

    def test_abstract_is_truncated_to_255_characters(self):
        article = make_article(abstract="a" * 400)

        lines = _build_ris([article]).decode("utf-8").split("\r\n")
        ab_line = next(line for line in lines if line.startswith("AB  - "))

        assert ab_line == "AB  - " + "a" * 255

    def test_multiple_records_are_separated_by_end_tags(self):
        articles = [make_article(title="First"), make_article(title="Second")]

        content = _build_ris(articles).decode("utf-8")

        assert content.count("TY  - JOUR") == 2
        assert content.count("ER  - ") == 2
        assert content.index("TI  - First") < content.index("TI  - Second")

    def test_empty_list_yields_empty_content(self):
        assert _build_ris([]) == b""


# =================== RDF ===================


class TestBuildRdf:
    """Tests for _build_rdf."""

    def test_is_well_formed_xml_with_expected_elements(self):
        article = make_article()

        root = ET.fromstring(_build_rdf([article]))
        descriptions = root.findall(f"{{{RDF_NS}}}Description")

        assert root.tag == f"{{{RDF_NS}}}RDF"
        assert len(descriptions) == 1
        desc = descriptions[0]
        assert desc.get(f"{{{RDF_NS}}}about") == f"#{article.id.hex}"
        rdf_type = desc.find(f"{{{RDF_NS}}}type")
        assert rdf_type is not None
        assert rdf_type.get(f"{{{RDF_NS}}}resource") == f"{BIBO_NS}AcademicArticle"
        assert desc.findtext(f"{{{DC_NS}}}title") == "Deep learning for sepsis prediction"
        assert [c.text for c in desc.findall(f"{{{DC_NS}}}creator")] == ["Smith J", "Doe A"]
        # The journal title itself is not asserted: the builder only emits a
        # reference to a journal node that is never defined in the document.
        assert desc.findtext(f"{{{BIBO_NS}}}issued") == "2021"
        assert desc.findtext(f"{{{BIBO_NS}}}abstract") == "Background and methods."
        assert desc.findtext(f"{{{BIBO_NS}}}doi") == "10.1000/xyz123"

    def test_escapes_xml_special_characters(self):
        article = make_article(
            title='Cats & <dogs> "study"',
            authors=["O'Brien & Sons"],
            abstract="p < 0.05 & q > 1",
            doi="10.1/a&b",
        )

        content = _build_rdf([article])
        desc = ET.fromstring(content).find(f"{{{RDF_NS}}}Description")

        assert b"Cats &amp; &lt;dogs&gt; &quot;study&quot;" in content
        assert desc is not None
        assert desc.findtext(f"{{{DC_NS}}}title") == 'Cats & <dogs> "study"'
        assert desc.findtext(f"{{{DC_NS}}}creator") == "O'Brien & Sons"
        assert desc.findtext(f"{{{BIBO_NS}}}abstract") == "p < 0.05 & q > 1"
        assert desc.findtext(f"{{{BIBO_NS}}}doi") == "10.1/a&b"

    def test_optional_elements_are_omitted(self):
        article = make_article(
            authors=["  ", ""],
            publication_year=None,
            journal_title=None,
            doi=None,
            abstract=None,
        )

        desc = ET.fromstring(_build_rdf([article])).find(f"{{{RDF_NS}}}Description")

        assert desc is not None
        assert desc.findall(f"{{{DC_NS}}}creator") == []
        assert desc.find(f"{{{BIBO_NS}}}Journal") is None
        assert desc.find(f"{{{BIBO_NS}}}issued") is None
        assert desc.find(f"{{{BIBO_NS}}}abstract") is None
        assert desc.find(f"{{{BIBO_NS}}}doi") is None

    def test_creators_are_stripped(self):
        article = make_article(authors=["  Smith J  "])

        desc = ET.fromstring(_build_rdf([article])).find(f"{{{RDF_NS}}}Description")

        assert desc is not None
        assert desc.findtext(f"{{{DC_NS}}}creator") == "Smith J"

    def test_abstract_is_truncated_to_2000_characters(self):
        article = make_article(abstract="b" * 2500)

        desc = ET.fromstring(_build_rdf([article])).find(f"{{{RDF_NS}}}Description")

        assert desc is not None
        assert desc.findtext(f"{{{BIBO_NS}}}abstract") == "b" * 2000

    def test_one_description_per_article(self):
        articles = [make_article(title="A"), make_article(title="B")]

        root = ET.fromstring(_build_rdf(articles))
        titles = [d.findtext(f"{{{DC_NS}}}title") for d in root.findall(f"{{{RDF_NS}}}Description")]

        assert titles == ["A", "B"]

    def test_empty_list_is_still_valid_document(self):
        root = ET.fromstring(_build_rdf([]))

        assert root.tag == f"{{{RDF_NS}}}RDF"
        assert list(root) == []


# =================== SERVICE: REPOSITORIES ===================


class TestServiceRepositories:
    """Tests for repository wiring and article loading."""

    def test_init_defaults_trace_id_to_empty_string(self):
        service = ArticlesExportService(db=MagicMock(), user_id="u1", storage=make_storage())

        assert service.trace_id == ""
        assert service.user_id == "u1"

    def test_project_members_repo_uses_service_session(self):
        db = AsyncMock(spec=AsyncSession)
        service = ArticlesExportService(db=db, user_id="u1", storage=make_storage())

        repo = service._project_members_repo()

        assert isinstance(repo, ProjectMemberRepository)
        assert repo.db is db

    async def test_get_articles_for_export_delegates_to_repository(self):
        db = AsyncMock(spec=AsyncSession)
        service = ArticlesExportService(db=db, user_id="u1", storage=make_storage())
        project_id = uuid4()
        article_ids = [uuid4(), uuid4()]
        articles = [make_article(), make_article()]

        with patch("app.services.articles_export_service.ArticleRepository") as repo_cls:
            repo_cls.return_value.get_by_ids = AsyncMock(return_value=articles)

            result = await service.get_articles_for_export(
                project_id, article_ids, include_files=False
            )

        assert result == articles
        repo_cls.assert_called_once_with(db)
        repo_cls.return_value.get_by_ids.assert_awaited_once_with(
            article_ids, project_id, include_files=False
        )

    async def test_get_articles_for_export_includes_files_by_default(self):
        service = ArticlesExportService(db=MagicMock(), user_id="u1", storage=make_storage())

        with patch("app.services.articles_export_service.ArticleRepository") as repo_cls:
            repo_cls.return_value.get_by_ids = AsyncMock(return_value=[])

            await service.get_articles_for_export(uuid4(), [uuid4()])

        assert repo_cls.return_value.get_by_ids.await_args.kwargs == {"include_files": True}


# =================== SERVICE: run_export (metadata only) ===================


class TestRunExportMetadataOnly:
    """Tests for run_export with file_scope='none'."""

    async def test_no_articles_returns_empty_binary(self):
        storage = make_storage()
        service, get_by_ids = make_service([], storage)
        project_id = uuid4()
        article_ids = [uuid4()]

        result = await service.run_export(project_id, article_ids, ["csv"], "none")

        assert result == (b"", "application/octet-stream", "export.bin", [])
        get_by_ids.assert_awaited_once_with(article_ids, project_id, include_files=False)
        storage.download.assert_not_awaited()

    async def test_single_csv(self):
        article = make_article()
        service, get_by_ids = make_service([article])

        content, ctype, name, skipped = await service.run_export(
            uuid4(), [article.id], ["csv"], "none"
        )

        assert ctype == "text/csv"
        assert name == "articles_export.csv"
        assert skipped == []
        assert content == _build_csv([article])
        assert parse_csv(content)[1][0] == article.title
        assert get_by_ids.await_args.kwargs == {"include_files": False}

    async def test_single_ris(self):
        article = make_article()
        service, _ = make_service([article])

        content, ctype, name, skipped = await service.run_export(
            uuid4(), [article.id], ["ris"], "none"
        )

        assert ctype == "application/x-research-info-systems"
        assert name == "articles_export.ris"
        assert skipped == []
        assert content.startswith(b"TY  - JOUR")
        assert content == _build_ris([article])

    async def test_single_rdf(self):
        article = make_article()
        service, _ = make_service([article])

        content, ctype, name, skipped = await service.run_export(
            uuid4(), [article.id], ["rdf"], "none"
        )

        assert ctype == "application/rdf+xml"
        assert name == "articles_export.rdf"
        assert skipped == []
        assert ET.fromstring(content).tag == f"{{{RDF_NS}}}RDF"

    async def test_single_format_is_case_insensitive(self):
        article = make_article()
        service, _ = make_service([article])

        content, ctype, name, _ = await service.run_export(uuid4(), [article.id], ["CSV"], "none")

        assert (ctype, name) == ("text/csv", "articles_export.csv")
        assert content == _build_csv([article])

    async def test_multiple_formats_are_zipped(self):
        articles = [make_article(title="A"), make_article(title="B")]
        storage = make_storage()
        service, _ = make_service(articles, storage)

        content, ctype, name, skipped = await service.run_export(
            uuid4(), [a.id for a in articles], ["csv", "RIS", "rdf"], "none"
        )

        assert ctype == "application/zip"
        assert name == "articles_export.zip"
        assert skipped == []
        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == [
                "articles_export.csv",
                "articles_export.rdf",
                "articles_export.ris",
            ]
            assert zf.read("articles_export.csv") == _build_csv(articles)
            assert zf.read("articles_export.ris") == _build_ris(articles)
            assert zf.read("articles_export.rdf") == _build_rdf(articles)
        storage.download.assert_not_awaited()

    async def test_zip_contains_only_requested_formats(self):
        article = make_article()
        service, _ = make_service([article])

        content, ctype, _, _ = await service.run_export(
            uuid4(), [article.id], ["csv", "rdf"], "none"
        )

        assert ctype == "application/zip"
        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == ["articles_export.csv", "articles_export.rdf"]


# =================== SERVICE: run_export (main_only) ===================


class TestRunExportMainOnly:
    """Tests for run_export with file_scope='main_only'."""

    async def test_flat_zip_with_metadata_and_main_files(self):
        a1 = make_article(
            title="First",
            files=[
                make_file("p/a1/main.pdf", original_filename="first.pdf", file_role="MAIN"),
                make_file("p/a1/supp.pdf", original_filename="supp.pdf", file_role="SUPPLEMENT"),
            ],
        )
        a2 = make_article(
            title="Second",
            files=[make_file("p/a2/main.pdf", original_filename="second.pdf", file_role="main")],
        )
        storage = make_storage(
            {
                "p/a1/main.pdf": b"%PDF-first",
                "p/a1/supp.pdf": b"%PDF-supp",
                "p/a2/main.pdf": b"%PDF-second",
            }
        )
        service, get_by_ids = make_service([a1, a2], storage)
        project_id = uuid4()

        content, ctype, name, skipped = await service.run_export(
            project_id, [a1.id, a2.id], ["csv", "ris", "rdf"], "main_only"
        )

        assert (ctype, name, skipped) == ("application/zip", "articles_export.zip", [])
        assert get_by_ids.await_args.kwargs == {"include_files": True}
        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == [
                "articles_export.csv",
                "articles_export.rdf",
                "articles_export.ris",
                "first.pdf",
                "second.pdf",
            ]
            assert zf.read("first.pdf") == b"%PDF-first"
            assert zf.read("second.pdf") == b"%PDF-second"
            assert zf.read("articles_export.csv") == _build_csv([a1, a2])
        # Only MAIN files are downloaded, always from the "articles" bucket.
        assert [c.args for c in storage.download.await_args_list] == [
            ("articles", "p/a1/main.pdf"),
            ("articles", "p/a2/main.pdf"),
        ]

    async def test_article_without_main_file_only_contributes_metadata(self):
        article = make_article(
            files=[make_file("p/x/supp.pdf", original_filename="s.pdf", file_role="SUPPLEMENT")]
        )
        no_files = make_article(files=[])
        storage = make_storage({"p/x/supp.pdf": b"supp"})
        service, _ = make_service([article, no_files], storage)

        content, _, _, skipped = await service.run_export(
            uuid4(), [article.id, no_files.id], ["csv"], "main_only"
        )

        assert skipped == []
        with open_zip(content) as zf:
            assert zf.namelist() == ["articles_export.csv"]
            assert len(parse_csv(zf.read("articles_export.csv"))) == 3
        storage.download.assert_not_awaited()

    async def test_file_without_role_is_not_treated_as_main(self):
        article = make_article(files=[make_file("p/x/unknown.pdf", file_role=None)])
        storage = make_storage({"p/x/unknown.pdf": b"data"})
        service, _ = make_service([article], storage)

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["ris"], "main_only")

        with open_zip(content) as zf:
            assert zf.namelist() == ["articles_export.ris"]
        storage.download.assert_not_awaited()

    async def test_main_file_name_falls_back_to_article_id(self):
        article = make_article(files=[make_file("p/x/blob", original_filename=None)])
        service, _ = make_service([article], make_storage({"p/x/blob": b"pdf-bytes"}))

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["csv"], "main_only")

        with open_zip(content) as zf:
            assert zf.read(f"{article.id}.pdf") == b"pdf-bytes"

    async def test_main_file_name_is_sanitized(self):
        article = make_article(
            files=[make_file("p/x/main.pdf", original_filename='a<b>c:"d"|e?*.pdf')]
        )
        service, _ = make_service([article], make_storage({"p/x/main.pdf": b"pdf"}))

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["csv"], "main_only")

        with open_zip(content) as zf:
            assert "a_b_c__d__e__.pdf" in zf.namelist()

    async def test_failed_download_is_reported_and_listed_in_manifest(self):
        ok = make_article(
            title="Ok", files=[make_file("p/ok/main.pdf", original_filename="ok.pdf")]
        )
        broken = make_article(
            title="Broken", files=[make_file("p/broken/main.pdf", original_filename="b.pdf")]
        )
        storage = make_storage({"p/ok/main.pdf": b"ok-bytes"})
        service, _ = make_service([ok, broken], storage)

        content, ctype, _, skipped = await service.run_export(
            uuid4(), [ok.id, broken.id], ["csv"], "main_only"
        )

        assert ctype == "application/zip"
        assert len(skipped) == 1
        assert skipped[0]["article_id"] == str(broken.id)
        assert skipped[0]["storage_key"] == "p/broken/main.pdf"
        assert "Download failed" in skipped[0]["reason"]
        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == ["README_export.txt", "articles_export.csv", "ok.pdf"]
            manifest = zf.read("README_export.txt").decode("utf-8").splitlines()
        assert manifest[0] == "Skipped files (could not be included):"
        assert manifest[1] == f"{broken.id}\tp/broken/main.pdf\t{skipped[0]['reason']}"


# =================== SERVICE: run_export (all) ===================


class TestRunExportAllFiles:
    """Tests for run_export with file_scope='all'."""

    async def test_one_folder_per_article_with_metadata_and_all_files(self):
        article = make_article(
            title="My Study: part 1",
            files=[
                make_file("p/a/main.pdf", original_filename="main.pdf", file_role="MAIN"),
                make_file("p/a/data.csv", original_filename="data.csv", file_role="DATASET"),
            ],
        )
        storage = make_storage({"p/a/main.pdf": b"main-bytes", "p/a/data.csv": b"x,y\n1,2"})
        service, get_by_ids = make_service([article], storage)
        folder = f"{article.id}_My_Study_part_1"

        content, ctype, name, skipped = await service.run_export(
            uuid4(), [article.id], ["csv", "ris", "rdf"], "all"
        )

        assert (ctype, name, skipped) == ("application/zip", "articles_export.zip", [])
        assert get_by_ids.await_args.kwargs == {"include_files": True}
        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == sorted(
                [
                    f"{folder}/article.csv",
                    f"{folder}/article.ris",
                    f"{folder}/article.rdf",
                    f"{folder}/main.pdf",
                    f"{folder}/data.csv",
                ]
            )
            assert zf.read(f"{folder}/article.csv") == _build_csv([article])
            assert zf.read(f"{folder}/article.ris") == _build_ris([article])
            assert zf.read(f"{folder}/article.rdf") == _build_rdf([article])
            assert zf.read(f"{folder}/main.pdf") == b"main-bytes"
            assert zf.read(f"{folder}/data.csv") == b"x,y\n1,2"
        assert storage.download.await_count == 2

    async def test_each_article_gets_its_own_metadata(self):
        a1 = make_article(title="Alpha")
        a2 = make_article(title="Beta")
        service, _ = make_service([a1, a2])

        content, _, _, _ = await service.run_export(uuid4(), [a1.id, a2.id], ["csv"], "all")

        with open_zip(content) as zf:
            assert sorted(zf.namelist()) == sorted(
                [f"{a1.id}_Alpha/article.csv", f"{a2.id}_Beta/article.csv"]
            )
            rows = parse_csv(zf.read(f"{a2.id}_Beta/article.csv"))
        assert [r[0] for r in rows[1:]] == ["Beta"]

    async def test_file_name_falls_back_to_storage_key_basename(self):
        article = make_article(title="T", files=[make_file("p/a/stored.pdf")])
        service, _ = make_service([article], make_storage({"p/a/stored.pdf": b"s"}))

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["csv"], "all")

        with open_zip(content) as zf:
            assert zf.read(f"{article.id}_T/stored.pdf") == b"s"

    async def test_file_name_falls_back_to_file_id(self):
        file_id = uuid4()
        article = make_article(title="T", files=[make_file("p/a/", file_id=file_id)])
        service, _ = make_service([article], make_storage({"p/a/": b"raw"}))

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["csv"], "all")

        with open_zip(content) as zf:
            assert zf.read(f"{article.id}_T/{file_id}.bin") == b"raw"

    async def test_file_name_is_sanitized(self):
        article = make_article(
            title="T", files=[make_file("p/a/f.pdf", original_filename="re:port?.pdf")]
        )
        service, _ = make_service([article], make_storage({"p/a/f.pdf": b"r"}))

        content, _, _, _ = await service.run_export(uuid4(), [article.id], ["csv"], "all")

        with open_zip(content) as zf:
            assert zf.read(f"{article.id}_T/re_port_.pdf") == b"r"

    async def test_failed_downloads_are_skipped_and_listed(self):
        article = make_article(
            title="T",
            files=[
                make_file("p/a/good.pdf", original_filename="good.pdf"),
                make_file("p/a/missing.pdf", original_filename="missing.pdf", file_role="OTHER"),
            ],
        )
        storage = make_storage({"p/a/good.pdf": b"g"})
        service, _ = make_service([article], storage)

        content, _, _, skipped = await service.run_export(uuid4(), [article.id], ["ris"], "all")

        assert [(s["article_id"], s["storage_key"]) for s in skipped] == [
            (str(article.id), "p/a/missing.pdf")
        ]
        with open_zip(content) as zf:
            names = zf.namelist()
            manifest = zf.read("README_export.txt").decode("utf-8")
        assert f"{article.id}_T/good.pdf" in names
        assert f"{article.id}_T/missing.pdf" not in names
        assert f"{article.id}\tp/a/missing.pdf\t" in manifest


# =================== SERVICE: run_export_async ===================


class TestRunExportAsync:
    """Tests for run_export_async (upload plus signed URL)."""

    async def test_uploads_zip_and_returns_signed_url(self):
        article = make_article(title="T", files=[make_file("p/a/m.pdf", original_filename="m.pdf")])
        storage = make_storage({"p/a/m.pdf": b"m"})
        service, _ = make_service([article], storage)
        before = datetime.now(UTC)

        result = await service.run_export_async(
            uuid4(), [article.id], ["csv", "ris"], "all", job_id="job-42"
        )

        after = datetime.now(UTC)
        storage.upload.assert_awaited_once()
        bucket, path, data, content_type = storage.upload.await_args.args
        assert (bucket, path, content_type) == (
            "articles",
            "exports/user-123/job-42.zip",
            "application/zip",
        )
        with open_zip(data) as zf:
            assert f"{article.id}_T/m.pdf" in zf.namelist()
        storage.get_signed_url.assert_awaited_once_with(
            "articles", "exports/user-123/job-42.zip", expires_in=3600
        )
        assert result["download_url"] == "https://storage.test/signed/export.zip"
        assert result["skipped_files"] == []
        expires_at = datetime.fromisoformat(result["expires_at"])
        assert before + timedelta(seconds=3600) <= expires_at <= after + timedelta(seconds=3600)

    async def test_skipped_files_use_camel_case_keys(self):
        article = make_article(
            title="T", files=[make_file("p/a/gone.pdf", original_filename="gone.pdf")]
        )
        storage = make_storage({})
        service, _ = make_service([article], storage)

        result = await service.run_export_async(
            uuid4(), [article.id], ["csv"], "main_only", job_id="job-7"
        )

        assert len(result["skipped_files"]) == 1
        entry = result["skipped_files"][0]
        assert set(entry) == {"articleId", "storageKey", "reason"}
        assert entry["articleId"] == str(article.id)
        assert entry["storageKey"] == "p/a/gone.pdf"
        assert "Download failed" in entry["reason"]
        uploaded = storage.upload.await_args.args[2]
        with open_zip(uploaded) as zf:
            assert "README_export.txt" in zf.namelist()

    async def test_upload_error_propagates_without_signing(self):
        article = make_article()
        storage = make_storage()
        storage.upload = AsyncMock(side_effect=StorageError("Upload failed", "articles", "p"))
        service, _ = make_service([article], storage)

        with pytest.raises(StorageError, match="Upload failed"):
            await service.run_export_async(
                uuid4(), [article.id], ["csv", "rdf"], "none", job_id="job-1"
            )

        storage.get_signed_url.assert_not_awaited()

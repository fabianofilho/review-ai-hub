"""
Articles Export Service.

Constrói export de artigos em CSV, RIS e RDF; monta ZIP com opção de arquivos;
faz upload para storage e retorna URL assinada.
"""

import csv
import io
import re
import zipfile
from datetime import UTC, datetime
from uuid import UUID

from app.core.logging import LoggerMixin
from app.infrastructure.storage.base import StorageAdapter
from app.models.article import Article
from app.repositories.article_repository import ArticleRepository
from app.repositories.project_repository import ProjectMemberRepository


def _sanitize_folder_name(title: str | None, article_id: UUID) -> str:
    """Gera nome de pasta: id_sanitized_title. Remove caracteres inválidos."""
    safe = (title or "").strip()
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", safe)[:80].strip() or "article"
    safe = re.sub(r"\s+", "_", safe)
    return f"{article_id}_{safe}"


def _authors_ris(authors: list[str] | None) -> list[str]:
    """Formata autores para RIS (AU - um por linha)."""
    if not authors:
        return []
    out = []
    for a in authors:
        a = (a or "").strip()
        if a:
            out.append(a)
    return out


def _build_csv(articles: list[Article]) -> bytes:
    """Gera CSV com colunas: title, authors, publication_year, journal_title, doi, pmid, keywords, abstract."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(
        [
            "title",
            "authors",
            "publication_year",
            "journal_title",
            "doi",
            "pmid",
            "keywords",
            "abstract",
        ]
    )
    for a in articles:
        writer.writerow(
            [
                (a.title or ""),
                "; ".join(a.authors or []),
                a.publication_year or "",
                a.journal_title or "",
                a.doi or "",
                a.pmid or "",
                "; ".join(a.keywords or []),
                (a.abstract or "").replace("\n", " "),
            ]
        )
    return buf.getvalue().encode("utf-8")


def _build_ris(articles: list[Article]) -> bytes:
    """Gera RIS: TY, TI, AU, PY, JO, AB, DO, AN, ER por registro."""
    lines: list[str] = []
    for a in articles:
        lines.append("TY  - JOUR")
        lines.append(f"TI  - {(a.title or '').replace(chr(10), ' ').replace(chr(13), '')}")
        for au in _authors_ris(a.authors):
            lines.append(f"AU  - {au}")
        if a.publication_year:
            lines.append(f"PY  - {a.publication_year}")
        if a.journal_title:
            lines.append(f"JO  - {(a.journal_title or '').replace(chr(10), ' ')}")
        if a.abstract:
            lines.append(
                f"AB  - {(a.abstract or '').replace(chr(10), ' ').replace(chr(13), '')[:255]}"
            )
        if a.doi:
            lines.append(f"DO  - {a.doi}")
        if a.pmid:
            lines.append(f"AN  - {a.pmid}")
        lines.append("ER  - ")
    return "\r\n".join(lines).encode("utf-8")


def _build_rdf(articles: list[Article]) -> bytes:
    """Gera RDF mínimo compatível com Zotero (Bibliontology-style)."""
    # Namespace e documento RDF mínimo para importação Zotero
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
        '  xmlns:dc="http://purl.org/dc/elements/1.1/"',
        '  xmlns:bibo="http://purl.org/ontology/bibo/">',
    ]
    for a in articles:
        aid = a.id.hex
        parts.append(f'  <rdf:Description rdf:about="#{aid}">')
        parts.append('    <rdf:type rdf:resource="http://purl.org/ontology/bibo/AcademicArticle"/>')
        parts.append(f"    <dc:title>{_xml_esc(a.title or '')}</dc:title>")
        for au in a.authors or []:
            if (au or "").strip():
                parts.append(f"    <dc:creator>{_xml_esc(au.strip())}</dc:creator>")
        if a.journal_title:
            parts.append(f'    <bibo:Journal rdf:resource="#journal_{aid}"/>')
        if a.publication_year:
            parts.append(f"    <bibo:issued>{a.publication_year}</bibo:issued>")
        if a.abstract:
            parts.append(
                f"    <bibo:abstract>{_xml_esc((a.abstract or '')[:2000])}</bibo:abstract>"
            )
        if a.doi:
            parts.append(f"    <bibo:doi>{_xml_esc(a.doi)}</bibo:doi>")
        parts.append("  </rdf:Description>")
    parts.append("</rdf:RDF>")
    return "\n".join(parts).encode("utf-8")


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class ArticlesExportService(LoggerMixin):
    """
    Serviço de exportação de artigos (CSV, RIS, RDF) com opção de arquivos.
    """

    def __init__(
        self,
        db,
        user_id: str,
        storage: StorageAdapter,
        trace_id: str | None = None,
    ):
        self.db = db
        self.user_id = user_id
        self.storage = storage
        self.trace_id = trace_id or ""

    def _articles_repo(self) -> ArticleRepository:
        return ArticleRepository(self.db)

    def _project_members_repo(self) -> ProjectMemberRepository:
        return ProjectMemberRepository(self.db)

    async def get_articles_for_export(
        self,
        project_id: UUID,
        article_ids: list[UUID],
        *,
        include_files: bool = True,
    ) -> list[Article]:
        """Carrega artigos por IDs no projeto; verifica permissão via project_id."""
        repo = self._articles_repo()
        return await repo.get_by_ids(
            article_ids,
            project_id,
            include_files=include_files,
        )

    async def run_export(
        self,
        project_id: UUID,
        article_ids: list[UUID],
        formats: list[str],
        file_scope: str,
        job_id: str | None = None,
    ) -> tuple[bytes, str, str, list[dict]]:
        """
        Executa export síncrono: gera conteúdo (CSV/RIS/RDF e opcionalmente ZIP com arquivos).
        Retorna (content_bytes, content_type, suggested_filename, skipped_files).
        """
        articles = await self.get_articles_for_export(
            project_id,
            article_ids,
            include_files=(file_scope != "none"),
        )
        if not articles:
            return b"", "application/octet-stream", "export.bin", []

        skipped: list[dict] = []
        bucket = "articles"

        if file_scope == "none":
            # Apenas metadados: um ou mais arquivos; se um formato, retorna direto
            if len(formats) == 1:
                fmt = formats[0].lower()
                if fmt == "csv":
                    content = _build_csv(articles)
                    return content, "text/csv", "articles_export.csv", []
                if fmt == "ris":
                    content = _build_ris(articles)
                    return content, "application/x-research-info-systems", "articles_export.ris", []
                if fmt == "rdf":
                    content = _build_rdf(articles)
                    return content, "application/rdf+xml", "articles_export.rdf", []
            # Múltiplos formatos -> ZIP
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if "csv" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.csv", _build_csv(articles))
                if "ris" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.ris", _build_ris(articles))
                if "rdf" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.rdf", _build_rdf(articles))
            return buf.getvalue(), "application/zip", "articles_export.zip", []

        # file_scope main_only ou all: sempre ZIP
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if file_scope == "main_only":
                # Flat: metadata files + um arquivo por artigo (main)
                if "csv" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.csv", _build_csv(articles))
                if "ris" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.ris", _build_ris(articles))
                if "rdf" in [f.lower() for f in formats]:
                    zf.writestr("articles_export.rdf", _build_rdf(articles))
                for art in articles:
                    main_file = next(
                        (
                            f
                            for f in (art.files or [])
                            if (getattr(f, "file_role", None) or "").upper() == "MAIN"
                        ),
                        None,
                    )
                    if main_file:
                        try:
                            data = await self.storage.download(bucket, main_file.storage_key)
                            name = main_file.original_filename or f"{art.id}.pdf"
                            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
                            zf.writestr(name, data)
                        except Exception as e:
                            skipped.append(
                                {
                                    "article_id": str(art.id),
                                    "storage_key": main_file.storage_key,
                                    "reason": str(e),
                                }
                            )
                    # else: artigo sem main file -> só metadata, sem erro
            else:
                # all: pasta por artigo id_sanitized_title
                for art in articles:
                    folder = _sanitize_folder_name(art.title, art.id)
                    if "csv" in [f.lower() for f in formats]:
                        zf.writestr(f"{folder}/article.csv", _build_csv([art]))
                    if "ris" in [f.lower() for f in formats]:
                        zf.writestr(f"{folder}/article.ris", _build_ris([art]))
                    if "rdf" in [f.lower() for f in formats]:
                        zf.writestr(f"{folder}/article.rdf", _build_rdf([art]))
                    for f in art.files or []:
                        try:
                            data = await self.storage.download(bucket, f.storage_key)
                            name = (
                                f.original_filename or f.storage_key.split("/")[-1] or f"{f.id}.bin"
                            )
                            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
                            zf.writestr(f"{folder}/{name}", data)
                        except Exception as e:
                            skipped.append(
                                {
                                    "article_id": str(art.id),
                                    "storage_key": f.storage_key,
                                    "reason": str(e),
                                }
                            )
            if skipped:
                manifest = "Skipped files (could not be included):\n" + "\n".join(
                    f"{s['article_id']}\t{s['storage_key']}\t{s['reason']}" for s in skipped
                )
                zf.writestr("README_export.txt", manifest)
        return zip_buf.getvalue(), "application/zip", "articles_export.zip", skipped

    async def run_export_async(
        self,
        project_id: UUID,
        article_ids: list[UUID],
        formats: list[str],
        file_scope: str,
        job_id: str,
    ) -> dict:
        """
        Executa export e faz upload do ZIP para storage; retorna download_url, expires_at, skipped_files.
        """
        content, _ct, _name, skipped = await self.run_export(
            project_id, article_ids, formats, file_scope, job_id=job_id
        )
        path = f"exports/{self.user_id}/{job_id}.zip"
        await self.storage.upload("articles", path, content, "application/zip")
        expires_in = 3600
        download_url = await self.storage.get_signed_url("articles", path, expires_in=expires_in)
        from datetime import timedelta

        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
        return {
            "download_url": download_url,
            "expires_at": expires_at,
            "skipped_files": [
                {
                    "articleId": s["article_id"],
                    "storageKey": s["storage_key"],
                    "reason": s["reason"],
                }
                for s in skipped
            ],
        }

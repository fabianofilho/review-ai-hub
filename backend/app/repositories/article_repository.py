"""
Article Repository.

Gerencia acesso a dados de artigos e arquivos.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.article import Article, ArticleFile
from app.models.article_author import ArticleSyncEvent, ArticleSyncRun
from app.repositories.base import BaseRepository


class ArticleRepository(BaseRepository[Article]):
    """
    Repository para operações com artigos.

    Encapsula queries de artigos e arquivos relacionados.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, Article)

    async def get_by_project(
        self,
        project_id: UUID | str,
        *,
        skip: int = 0,
        limit: int = 100,
        include_files: bool = False,
    ) -> list[Article]:
        """
        Lista artigos de um projeto.

        Args:
            project_id: ID do projeto.
            skip: Offset para paginação.
            limit: Limite de resultados.
            include_files: Se deve incluir arquivos.

        Returns:
            Lista de artigos do projeto.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        query = select(Article).where(Article.project_id == project_id)

        if include_files:
            query = query.options(selectinload(Article.files))

        query = query.offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_files(self, article_id: UUID | str) -> Article | None:
        """
        Busca artigo com seus arquivos.

        Args:
            article_id: ID do artigo.

        Returns:
            Artigo com arquivos ou None.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        result = await self.db.execute(
            select(Article).options(selectinload(Article.files)).where(Article.id == article_id)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(
        self,
        article_ids: list[UUID] | list[str],
        project_id: UUID | str,
        *,
        include_files: bool = False,
    ) -> list[Article]:
        """
        Busca artigos por lista de IDs, restritos ao projeto.

        Args:
            article_ids: IDs dos artigos.
            project_id: ID do projeto (artigos devem pertencer a este projeto).
            include_files: Se deve carregar arquivos relacionados.

        Returns:
            Lista de artigos encontrados, na ordem dos IDs solicitados.
        """
        if not article_ids:
            return []
        ids = [UUID(aid) if isinstance(aid, str) else aid for aid in article_ids]
        if isinstance(project_id, str):
            project_id = UUID(project_id)
        query = select(Article).where(
            Article.id.in_(ids),
            Article.project_id == project_id,
        )
        if include_files:
            query = query.options(selectinload(Article.files))
        result = await self.db.execute(query)
        rows = list(result.scalars().all())
        # Manter ordem dos IDs solicitados
        by_id = {a.id: a for a in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def ensure_in_project(
        self,
        article_ids: list[UUID] | list[str],
        project_id: UUID | str,
    ) -> None:
        """
        Ensure that every article exists and belongs to the project.

        Raises:
            ValueError: When any article is missing or belongs to another project.
        """
        ids = {UUID(str(aid)) for aid in article_ids}
        if not ids:
            return
        project_uuid = UUID(str(project_id))
        result = await self.db.execute(
            select(Article.id).where(
                Article.id.in_(ids),
                Article.project_id == project_uuid,
            )
        )
        missing = ids - set(result.scalars().all())
        if missing:
            raise ValueError(f"{len(missing)} article(s) not found in project {project_uuid}")

    async def get_by_zotero_item_key(
        self,
        project_id: UUID | str,
        zotero_item_key: str,
    ) -> Article | None:
        """
        Busca artigo por zotero_item_key dentro de um projeto.

        Args:
            project_id: ID do projeto.
            zotero_item_key: Key do item no Zotero.

        Returns:
            Artigo encontrado ou None.
        """
        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(Article)
            .where(Article.project_id == project_id)
            .where(Article.zotero_item_key == zotero_item_key)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_by_project(self, project_id: UUID | str) -> int:
        """
        Conta artigos de um projeto.

        Args:
            project_id: ID do projeto.

        Returns:
            Número de artigos.
        """
        from sqlalchemy import func

        if isinstance(project_id, str):
            project_id = UUID(project_id)

        result = await self.db.execute(
            select(func.count()).select_from(Article).where(Article.project_id == project_id)
        )
        return result.scalar_one()

    async def get_by_canonical_identity(
        self,
        project_id: UUID,
        *,
        zotero_item_key: str | None = None,
        doi: str | None = None,
        url_landing: str | None = None,
    ) -> Article | None:
        if zotero_item_key:
            return await self.get_by_zotero_item_key(project_id, zotero_item_key)

        clauses = []
        if doi:
            clauses.append(Article.doi == doi)
        if url_landing:
            clauses.append(Article.url_landing == url_landing)
        if not clauses:
            return None

        result = await self.db.execute(
            select(Article)
            .where(Article.project_id == project_id)
            .where(clauses[0] if len(clauses) == 1 else clauses[0] | clauses[1])
            .order_by(Article.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_by_canonical_identity(
        self,
        *,
        project_id: UUID,
        payload: dict,
        canonical_identity: dict[str, str | None],
    ) -> tuple[Article, bool]:
        existing = await self.get_by_canonical_identity(
            project_id,
            zotero_item_key=canonical_identity.get("zotero_item_key"),
            doi=canonical_identity.get("doi"),
            url_landing=canonical_identity.get("url_landing"),
        )
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.last_synced_at = datetime.now(UTC)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing, False

        article = Article(
            project_id=project_id,
            last_synced_at=datetime.now(UTC),
            **payload,
        )
        created = await self.create(article)
        return created, True

    async def mark_removed_at_source(self, article: Article) -> Article:
        article.sync_state = "removed_at_source"
        article.removed_at_source_at = datetime.now(UTC)
        article.last_synced_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def mark_reactivated(self, article: Article) -> Article:
        article.sync_state = "reactivated"
        article.removed_at_source_at = None
        article.last_synced_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def update_screening_phase(
        self,
        article_id: UUID | str,
        phase: str,
        decision: str,
    ) -> None:
        """
        Update the denormalized screening_phase on an article.

        Args:
            article_id: ID of the article.
            phase: Current screening phase (title_abstract or full_text).
            decision: Screening decision (include, exclude, maybe).
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        article = await self.db.get(Article, article_id)
        if article:
            if decision == "include" and phase == "full_text":
                article.screening_phase = "included"
            elif decision == "exclude":
                article.screening_phase = f"excluded_{phase}"
            else:
                article.screening_phase = phase
            await self.db.flush()

    async def get_zotero_project_articles(
        self, project_id: UUID, collection_key: str | None = None
    ) -> list[Article]:
        query = select(Article).where(
            Article.project_id == project_id,
            Article.ingestion_source == "zotero",
            Article.zotero_item_key.is_not(None),
        )
        if collection_key:
            query = query.where(Article.zotero_collection_key == collection_key)
        result = await self.db.execute(query)
        return list(result.scalars().all())


class ArticleSyncRunRepository(BaseRepository[ArticleSyncRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, ArticleSyncRun)

    async def create_run(
        self,
        *,
        project_id: UUID,
        requested_by_user_id: UUID,
        source: str,
        source_collection_key: str | None,
    ) -> ArticleSyncRun:
        run = ArticleSyncRun(
            project_id=project_id,
            requested_by_user_id=requested_by_user_id,
            started_at=datetime.now(UTC),
            status="pending",
            source=source,
            source_collection_key=source_collection_key,
        )
        return await self.create(run)

    async def get_owned_run(self, sync_run_id: UUID, user_id: UUID) -> ArticleSyncRun | None:
        result = await self.db.execute(
            select(ArticleSyncRun)
            .where(ArticleSyncRun.id == sync_run_id)
            .where(ArticleSyncRun.requested_by_user_id == user_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_counts(
        self, run: ArticleSyncRun, counts: dict[str, int], status: str
    ) -> ArticleSyncRun:
        run.total_received = counts.get("total_received", run.total_received)
        run.persisted = counts.get("persisted", run.persisted)
        run.updated = counts.get("updated", run.updated)
        run.skipped = counts.get("skipped", run.skipped)
        run.failed = counts.get("failed", run.failed)
        run.removed_at_source = counts.get("removed_at_source", run.removed_at_source)
        run.reactivated = counts.get("reactivated", run.reactivated)
        run.status = status
        if status in {"completed", "failed", "cancelled"}:
            run.completed_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(run)
        return run


class ArticleSyncEventRepository(BaseRepository[ArticleSyncEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, ArticleSyncEvent)

    async def create_event(
        self,
        *,
        project_id: UUID,
        sync_run_id: UUID,
        status: str,
        zotero_item_key: str | None,
        article_id: UUID | None = None,
        authority_rule_applied: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        event_payload: dict | None = None,
    ) -> ArticleSyncEvent:
        event = ArticleSyncEvent(
            project_id=project_id,
            article_id=article_id,
            sync_run_id=sync_run_id,
            zotero_item_key=zotero_item_key,
            status=status,
            authority_rule_applied=authority_rule_applied,
            error_code=error_code,
            error_message=error_message,
            event_payload=event_payload,
            processed_at=datetime.now(UTC),
        )
        return await self.create(event)

    async def list_run_events(
        self,
        *,
        sync_run_id: UUID,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[ArticleSyncEvent], int]:
        query = select(ArticleSyncEvent).where(ArticleSyncEvent.sync_run_id == sync_run_id)
        count_query = (
            select(func.count())
            .select_from(ArticleSyncEvent)
            .where(ArticleSyncEvent.sync_run_id == sync_run_id)
        )
        if status_filter:
            query = query.where(ArticleSyncEvent.status == status_filter)
            count_query = count_query.where(ArticleSyncEvent.status == status_filter)

        result = await self.db.execute(
            query.order_by(ArticleSyncEvent.processed_at.desc()).offset(offset).limit(limit)
        )
        total_result = await self.db.execute(count_query)
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def list_failed_by_run(
        self, sync_run_id: UUID, limit: int = 100
    ) -> list[ArticleSyncEvent]:
        result = await self.db.execute(
            select(ArticleSyncEvent)
            .where(ArticleSyncEvent.sync_run_id == sync_run_id)
            .where(ArticleSyncEvent.status == "failed")
            .order_by(ArticleSyncEvent.processed_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ArticleFileRepository(BaseRepository[ArticleFile]):
    """
    Repository para arquivos de artigos.

    Gerencia arquivos PDF e outros anexos.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ArticleFile)

    async def get_by_article(
        self,
        article_id: UUID | str,
        file_type: str | None = None,
    ) -> list[ArticleFile]:
        """
        Lista arquivos de um artigo.

        Args:
            article_id: ID do artigo.
            file_type: Filtro por tipo (opcional).

        Returns:
            Lista de arquivos.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        query = select(ArticleFile).where(ArticleFile.article_id == article_id)

        if file_type:
            query = query.where(ArticleFile.file_type.ilike(f"%{file_type}%"))

        query = query.order_by(ArticleFile.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_latest_pdf(self, article_id: UUID | str) -> ArticleFile | None:
        """
        Busca o PDF mais recente de um artigo.

        Args:
            article_id: ID do artigo.

        Returns:
            Arquivo PDF ou None.
        """
        if isinstance(article_id, str):
            article_id = UUID(article_id)

        result = await self.db.execute(
            select(ArticleFile)
            .where(ArticleFile.article_id == article_id)
            .where(ArticleFile.file_type.ilike("%pdf%"))
            .order_by(ArticleFile.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_storage_key(self, storage_key: str) -> ArticleFile | None:
        """
        Busca arquivo por storage key.

        Args:
            storage_key: Chave do storage.

        Returns:
            Arquivo ou None.
        """
        result = await self.db.execute(
            select(ArticleFile).where(ArticleFile.storage_key == storage_key)
        )
        return result.scalar_one_or_none()

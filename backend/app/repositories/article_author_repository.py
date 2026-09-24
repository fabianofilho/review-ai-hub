"""
Article author repository.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article_author import ArticleAuthor, ArticleAuthorLink
from app.repositories.base import BaseRepository


def normalize_author_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class ArticleAuthorRepository(BaseRepository[ArticleAuthor]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, ArticleAuthor)

    async def get_by_identity(
        self, normalized_name: str, orcid: str | None
    ) -> ArticleAuthor | None:
        query = select(ArticleAuthor).where(ArticleAuthor.normalized_name == normalized_name)
        if orcid:
            query = query.where(ArticleAuthor.orcid == orcid)
        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        display_name: str,
        *,
        orcid: str | None = None,
        source_hint: dict | None = None,
    ) -> ArticleAuthor:
        normalized_name = normalize_author_name(display_name)
        existing = await self.get_by_identity(normalized_name, orcid)
        if existing:
            if source_hint:
                existing.source_hint = source_hint
                await self.db.flush()
            return existing

        author = ArticleAuthor(
            normalized_name=normalized_name,
            display_name=display_name,
            orcid=orcid,
            source_hint=source_hint,
        )
        return await self.create(author)


class ArticleAuthorLinkRepository(BaseRepository[ArticleAuthorLink]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, ArticleAuthorLink)

    async def replace_article_links(
        self, article_id: UUID, links: list[ArticleAuthorLink]
    ) -> list[ArticleAuthorLink]:
        await self.db.execute(
            delete(ArticleAuthorLink).where(ArticleAuthorLink.article_id == article_id)
        )
        for link in links:
            self.db.add(link)
        await self.db.flush()
        return links

    async def get_by_article(self, article_id: UUID) -> list[ArticleAuthorLink]:
        result = await self.db.execute(
            select(ArticleAuthorLink)
            .where(ArticleAuthorLink.article_id == article_id)
            .order_by(ArticleAuthorLink.author_order.asc())
        )
        return list(result.scalars().all())

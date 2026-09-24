"""
Extraction Run Repository.

Gerencia acesso a dados de execuções de IA para extração.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import ExtractionRun, ExtractionRunStage, ExtractionRunStatus
from app.repositories.base import BaseRepository


class ExtractionRunRepository(BaseRepository[ExtractionRun]):
    """
    Repository para execuções de extração de IA.

    Gerencia o ciclo de vida das extraction_runs.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db, ExtractionRun)

    async def create_run(
        self,
        project_id: UUID,
        article_id: UUID,
        template_id: UUID,
        stage: ExtractionRunStage,
        created_by: UUID,
        parameters: dict[str, Any] | None = None,
    ) -> ExtractionRun:
        """
        Cria uma nova execução de extração.

        Args:
            project_id: ID do projeto.
            article_id: ID do artigo.
            template_id: ID do template.
            stage: Estágio da execução (data_suggest, parsing, etc.).
            created_by: ID do usuário que criou.
            parameters: Parâmetros da execução (modelo, etc.).

        Returns:
            ExtractionRun criado.
        """
        # Converter Enum para string para garantir compatibilidade
        stage_value = stage.value if isinstance(stage, ExtractionRunStage) else str(stage)
        status_value = ExtractionRunStatus.PENDING.value

        run = ExtractionRun(
            project_id=project_id,
            article_id=article_id,
            template_id=template_id,
            stage=stage_value,
            status=status_value,
            parameters=parameters or {},
            results={},
            created_by=created_by,
        )

        return await self.create(run)

    async def start_run(self, run_id: UUID) -> ExtractionRun | None:
        """
        Marca uma execução como iniciada.

        Args:
            run_id: ID da execução.

        Returns:
            ExtractionRun atualizado ou None.
        """
        await self.db.execute(
            update(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .values(
                status=ExtractionRunStatus.RUNNING.value,
                started_at=datetime.now(UTC),
            )
        )
        await self.db.flush()
        return await self.get_by_id(run_id)

    async def complete_run(
        self,
        run_id: UUID,
        results: dict[str, Any],
    ) -> ExtractionRun | None:
        """
        Marca uma execução como concluída.

        Args:
            run_id: ID da execução.
            results: Resultados da execução.

        Returns:
            ExtractionRun atualizado ou None.
        """
        await self.db.execute(
            update(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .values(
                status=ExtractionRunStatus.COMPLETED.value,
                completed_at=datetime.now(UTC),
                results=results,
            )
        )
        await self.db.flush()
        return await self.get_by_id(run_id)

    async def fail_run(
        self,
        run_id: UUID,
        error_message: str,
    ) -> ExtractionRun | None:
        """
        Marca uma execução como falha.

        Args:
            run_id: ID da execução.
            error_message: Mensagem de erro.

        Returns:
            ExtractionRun atualizado ou None.
        """
        await self.db.execute(
            update(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .values(
                status=ExtractionRunStatus.FAILED.value,
                completed_at=datetime.now(UTC),
                error_message=error_message,
            )
        )
        await self.db.flush()
        return await self.get_by_id(run_id)

    async def get_by_article(
        self,
        article_id: UUID,
        stage: ExtractionRunStage | None = None,
        status: ExtractionRunStatus | None = None,
    ) -> list[ExtractionRun]:
        """
        Lista execuções de um artigo.

        Args:
            article_id: ID do artigo.
            stage: Filtro por estágio (opcional).
            status: Filtro por status (opcional).

        Returns:
            Lista de execuções.
        """
        query = select(ExtractionRun).where(ExtractionRun.article_id == article_id)

        if stage:
            query = query.where(ExtractionRun.stage == stage.value)

        if status:
            query = query.where(ExtractionRun.status == status.value)

        query = query.order_by(ExtractionRun.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_latest_by_article(
        self,
        article_id: UUID,
        stage: ExtractionRunStage,
    ) -> ExtractionRun | None:
        """
        Busca a execução mais recente de um artigo para um estágio.

        Args:
            article_id: ID do artigo.
            stage: Estágio da execução.

        Returns:
            ExtractionRun mais recente ou None.
        """
        result = await self.db.execute(
            select(ExtractionRun)
            .where(ExtractionRun.article_id == article_id)
            .where(ExtractionRun.stage == stage.value)
            .order_by(ExtractionRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_project(
        self,
        project_id: UUID,
        status: ExtractionRunStatus | None = None,
        limit: int = 50,
    ) -> list[ExtractionRun]:
        """
        Lista execuções de um projeto.

        Args:
            project_id: ID do projeto.
            status: Filtro por status (opcional).
            limit: Limite de resultados.

        Returns:
            Lista de execuções.
        """
        query = select(ExtractionRun).where(ExtractionRun.project_id == project_id)

        if status:
            query = query.where(ExtractionRun.status == status.value)

        query = query.order_by(ExtractionRun.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

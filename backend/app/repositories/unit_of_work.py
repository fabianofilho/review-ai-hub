"""
Unit of Work Pattern.

Coordena transações e garante consistência entre repositories.

O QUE É UNIT OF WORK?
=====================

O padrão Unit of Work (UoW) é uma abstração que:
1. Agrupa múltiplas operações de banco em uma única transação
2. Controla quando as mudanças são commitadas
3. Faz rollback automático se algo falhar
4. Centraliza o acesso a todos os repositories

POR QUE USAR?
=============

1. ATOMICIDADE: Múltiplas operações são tratadas como uma só
   - Se criar artigo e arquivo falhar no arquivo, ambos são revertidos

2. CONSISTÊNCIA: Evita estados inconsistentes no banco
   - Não há commits parciais

3. ORGANIZAÇÃO: Um ponto de entrada para todos os repositories
   - Não precisa criar repositories manualmente

4. SEGURANÇA: Rollback automático em exceções
   - async with garante cleanup adequado

COMO USAR
=========

Exemplo básico:
    async with UnitOfWork(session) as uow:
        article = await uow.articles.get_by_id(article_id)
        await uow.articles.update(article, {"title": "Novo título"})
        await uow.commit()  # Persiste a mudança

Exemplo com múltiplas operações:
    async with UnitOfWork(session) as uow:
        # Criar artigo
        article = Article(title="Novo", project_id=project_id)
        await uow.articles.create(article)

        # Criar arquivo do artigo (usa article.id já disponível)
        file = ArticleFile(article_id=article.id, file_type="pdf")
        await uow.article_files.create(file)

        # Commit de tudo de uma vez
        await uow.commit()

Exemplo com tratamento de erro:
    async with UnitOfWork(session) as uow:
        try:
            await uow.articles.create(article)
            await uow.commit()
        except Exception as e:
            # Rollback é automático via __aexit__
            raise

SEM USAR UoW (não recomendado):
    # Isso funciona, mas você perde as garantias de transação
    repo = ArticleRepository(session)
    await repo.create(article)
    await session.commit()  # Você controla o commit
"""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.article_author_repository import (
    ArticleAuthorLinkRepository,
    ArticleAuthorRepository,
)
from app.repositories.article_repository import (
    ArticleFileRepository,
    ArticleRepository,
    ArticleSyncEventRepository,
    ArticleSyncRunRepository,
)
from app.repositories.assessment_repository import (
    AIAssessmentRepository,
    AssessmentEvidenceRepository,
    AssessmentInstanceRepository,
    AssessmentInstrumentRepository,
    AssessmentItemRepository,
    AssessmentResponseRepository,
)
from app.repositories.extraction_repository import (
    AISuggestionRepository,
    ExtractionEntityTypeRepository,
    ExtractionInstanceRepository,
    ExtractionTemplateRepository,
    GlobalTemplateRepository,
)
from app.repositories.integration_repository import ZoteroIntegrationRepository
from app.repositories.project_repository import ProjectMemberRepository, ProjectRepository


class UnitOfWork:
    """
    Unit of Work para coordenação de transações.

    Agrupa repositories e controla commit/rollback.
    Deve SEMPRE ser usado com 'async with' para garantir cleanup.

    Attributes:
        session: Sessão SQLAlchemy subjacente
        articles: Repository de artigos
        article_files: Repository de arquivos de artigos
        projects: Repository de projetos
        project_members: Repository de membros de projetos
        assessment_instances: Repository de assessment instances (nova estrutura)
        assessment_responses: Repository de assessment responses (nova estrutura)
        ... (outros repositories)

    Example:
        # Uso básico
        async with UnitOfWork(session) as uow:
            article = await uow.articles.get_by_id(article_id)
            await uow.articles.update(article, {"title": "New Title"})
            await uow.commit()

        # Múltiplas operações atômicas
        async with UnitOfWork(session) as uow:
            project = await uow.projects.create(Project(name="Novo"))
            member = await uow.project_members.create(
                ProjectMember(project_id=project.id, user_id=user_id)
            )
            await uow.commit()  # Ambos são criados ou nenhum

    Warning:
        NUNCA use repositories fora do contexto 'async with'.
        O rollback automático só funciona dentro do context manager.
    """

    def __init__(self, session: AsyncSession):
        """
        Inicializa Unit of Work.

        Args:
            session: Sessão async do SQLAlchemy.
        """
        self.session = session
        self._init_repositories()

    def _init_repositories(self) -> None:
        """Inicializa todos os repositories."""
        # Articles
        self.articles = ArticleRepository(self.session)
        self.article_files = ArticleFileRepository(self.session)
        self.article_authors = ArticleAuthorRepository(self.session)
        self.article_author_links = ArticleAuthorLinkRepository(self.session)
        self.article_sync_runs = ArticleSyncRunRepository(self.session)
        self.article_sync_events = ArticleSyncEventRepository(self.session)

        # Projects
        self.projects = ProjectRepository(self.session)
        self.project_members = ProjectMemberRepository(self.session)

        # Assessments (new structure)
        self.assessment_instruments = AssessmentInstrumentRepository(self.session)
        self.assessment_items = AssessmentItemRepository(self.session)
        self.assessment_instances = AssessmentInstanceRepository(self.session)
        self.assessment_responses = AssessmentResponseRepository(self.session)
        self.assessment_evidence = AssessmentEvidenceRepository(self.session)
        self.ai_assessments = AIAssessmentRepository(self.session)

        # Extractions
        self.extraction_templates = ExtractionTemplateRepository(self.session)
        self.global_templates = GlobalTemplateRepository(self.session)
        self.entity_types = ExtractionEntityTypeRepository(self.session)
        self.extraction_instances = ExtractionInstanceRepository(self.session)
        self.ai_suggestions = AISuggestionRepository(self.session)

        # Integrations
        self.zotero_integrations = ZoteroIntegrationRepository(self.session)

    async def commit(self) -> None:
        """
        Confirma transação atual.

        IMPORTANTE: Sempre chame commit() explicitamente quando terminar
        as operações. Sem commit(), as mudanças NÃO são persistidas.

        Example:
            async with UnitOfWork(session) as uow:
                await uow.articles.create(article)
                await uow.commit()  # OBRIGATÓRIO para persistir
        """
        await self.session.commit()

    async def rollback(self) -> None:
        """
        Reverte transação atual.

        Descarta todas as mudanças pendentes (flush mas não commit).
        Chamado automaticamente se exceção ocorrer no 'async with'.

        Example:
            async with UnitOfWork(session) as uow:
                await uow.articles.create(article)
                await uow.rollback()  # Descarta a criação
        """
        await self.session.rollback()

    async def flush(self) -> None:
        """
        Sincroniza mudanças pendentes com o banco.

        Envia os comandos SQL para o banco, mas NÃO faz commit.
        Útil para obter IDs gerados ou forçar validação de constraints.
        Os repositories já fazem flush() automaticamente.
        """
        await self.session.flush()

    async def refresh(self, obj: object) -> None:
        """
        Atualiza objeto com dados atuais do banco.

        Útil para recarregar relacionamentos ou verificar mudanças
        feitas por triggers/defaults do banco.

        Args:
            obj: Qualquer objeto de modelo SQLAlchemy
        """
        await self.session.refresh(obj)

    async def __aenter__(self) -> Self:
        """
        Entra no contexto async.

        Retorna self para uso com 'async with'.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Sai do contexto async.

        IMPORTANTE: Faz rollback AUTOMÁTICO se exceção ocorrer.
        Isso garante que operações parciais não sejam commitadas.

        Se não houver exceção e você esqueceu de chamar commit(),
        as mudanças serão perdidas (não commitadas).
        """
        if exc_type is not None:
            await self.rollback()

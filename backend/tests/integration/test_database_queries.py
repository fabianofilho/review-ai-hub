"""
Testes de integração para queries no banco de dados.

Estes testes validam:
- Queries de leitura em tabelas existentes
- Contagem de registros
- Joins entre tabelas
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestProjectsQueries:
    """Testes de queries na tabela projects."""

    async def test_count_projects(self, db_session: AsyncSession) -> None:
        """Conta projetos existentes."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM projects"))
        row = result.fetchone()
        assert row is not None
        # Pode ter 0 ou mais projetos
        assert row[0] >= 0

    async def test_select_projects_with_owner(self, db_session: AsyncSession) -> None:
        """Query de projetos com join no criador."""
        result = await db_session.execute(
            text("""
                SELECT p.id, p.name, p.review_type, pr.full_name as owner_name
                FROM projects p
                LEFT JOIN profiles pr ON p.created_by_id = pr.id
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        # Pode retornar 0 ou mais linhas
        assert isinstance(rows, list)


@pytest.mark.asyncio
class TestArticlesQueries:
    """Testes de queries na tabela articles."""

    async def test_count_articles(self, db_session: AsyncSession) -> None:
        """Conta artigos existentes."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM articles"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_select_articles_with_project(self, db_session: AsyncSession) -> None:
        """Query de artigos com join no projeto."""
        result = await db_session.execute(
            text("""
                SELECT a.id, a.title, a.created_at, p.name as project_name
                FROM articles a
                LEFT JOIN projects p ON a.project_id = p.id
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)


@pytest.mark.asyncio
class TestAssessmentQueries:
    """Testes de queries nas tabelas de assessment."""

    async def test_count_assessment_instruments(self, db_session: AsyncSession) -> None:
        """Conta instrumentos de avaliação."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessment_instruments"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_count_assessment_items(self, db_session: AsyncSession) -> None:
        """Conta itens de avaliação."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessment_items"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_instruments_with_items_count(self, db_session: AsyncSession) -> None:
        """Query de instrumentos com contagem de itens."""
        result = await db_session.execute(
            text("""
                SELECT 
                    ai.id, 
                    ai.name, 
                    ai.tool_type,
                    COUNT(ait.id) as item_count
                FROM assessment_instruments ai
                LEFT JOIN assessment_items ait ON ai.id = ait.instrument_id
                GROUP BY ai.id, ai.name, ai.tool_type
                ORDER BY ai.name
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)


@pytest.mark.asyncio
class TestExtractionQueries:
    """Testes de queries nas tabelas de extração."""

    async def test_count_extraction_templates(self, db_session: AsyncSession) -> None:
        """Conta templates de extração globais."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM extraction_templates_global"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_count_extraction_entity_types(self, db_session: AsyncSession) -> None:
        """Conta tipos de entidade."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM extraction_entity_types"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_templates_with_entity_types(self, db_session: AsyncSession) -> None:
        """Query de templates com tipos de entidade."""
        result = await db_session.execute(
            text("""
                SELECT 
                    t.id,
                    t.name as template_name,
                    e.name as entity_name,
                    e.description
                FROM extraction_templates_global t
                LEFT JOIN extraction_entity_types e ON t.id = e.template_id
                ORDER BY t.name, e.name
                LIMIT 20
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)


@pytest.mark.asyncio
class TestIntegrationQueries:
    """Testes de queries nas tabelas de integração."""

    async def test_count_zotero_integrations(self, db_session: AsyncSession) -> None:
        """Conta integrações Zotero."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM zotero_integrations"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0


@pytest.mark.asyncio
class TestComplexQueries:
    """Testes de queries complexas com múltiplos joins."""

    async def test_project_summary_query(self, db_session: AsyncSession) -> None:
        """Query de resumo de projeto com contagens."""
        result = await db_session.execute(
            text("""
                SELECT 
                    p.id,
                    p.name,
                    p.review_type,
                    COUNT(DISTINCT a.id) as article_count,
                    COUNT(DISTINCT pm.user_id) as member_count
                FROM projects p
                LEFT JOIN articles a ON p.id = a.project_id
                LEFT JOIN project_members pm ON p.id = pm.project_id
                GROUP BY p.id, p.name, p.review_type
                ORDER BY p.created_at DESC
                LIMIT 5
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

    async def test_article_assessment_status(self, db_session: AsyncSession) -> None:
        """Query de status de avaliação por artigo."""
        result = await db_session.execute(
            text("""
                SELECT 
                    a.id,
                    a.title,
                    COUNT(DISTINCT ass.id) as assessment_count,
                    COUNT(DISTINCT ai.id) as ai_assessment_count
                FROM articles a
                LEFT JOIN assessments ass ON a.id = ass.article_id
                LEFT JOIN ai_assessments ai ON a.id = ai.article_id
                GROUP BY a.id, a.title
                ORDER BY a.created_at DESC
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

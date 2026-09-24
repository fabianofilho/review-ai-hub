"""
Base Repository.

Classe base genérica para todos os repositories.
Implementa operações CRUD comuns com SQLAlchemy async.

IMPORTANTE - Gerenciamento de Transações:
=========================================

Os métodos deste repository NÃO fazem commit automaticamente.
Usamos flush() para sincronizar mudanças e obter IDs gerados,
mas o commit() deve ser chamado explicitamente via UnitOfWork.

Por que flush() em vez de commit()?
-----------------------------------
1. Permite operações compostas (criar múltiplas entidades relacionadas)
2. Possibilita rollback se alguma parte falhar
3. Segue o padrão Unit of Work corretamente
4. Evita commits parciais em operações complexas

Como usar corretamente:
-----------------------
    # Forma recomendada: via UnitOfWork
    async with UnitOfWork(session) as uow:
        article = Article(title="Novo")
        await uow.articles.create(article)
        await uow.commit()  # Commit explícito

    # Se usar repository direto (não recomendado):
    repo = ArticleRepository(session)
    article = await repo.create(Article(title="Novo"))
    await session.commit()  # VOCÊ deve fazer o commit!

Relacionamento com UnitOfWork:
------------------------------
- Repositories são criados pelo UnitOfWork
- UnitOfWork controla commit/rollback
- Se exceção ocorrer, UnitOfWork faz rollback automático
"""

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import UUIDMixin

# Type var para modelo SQLAlchemy
# Bound to UUIDMixin because the generic queries below filter on the UUID
# primary key ``id``; every repository model is a Base subclass with this mixin.
T = TypeVar("T", bound=UUIDMixin)


class BaseRepository(Generic[T]):
    """
    Repository base genérico com operações CRUD.

    IMPORTANTE: Este repository usa flush() e NÃO commit().
    O commit deve ser feito via UnitOfWork ou diretamente na session.
    Isso permite agrupar múltiplas operações em uma transação.

    Attributes:
        db: Sessão async do SQLAlchemy.
        model: Classe do modelo SQLAlchemy.

    Usage com UnitOfWork (recomendado):
        async with UnitOfWork(session) as uow:
            article = await uow.articles.get_by_id(id)
            await uow.articles.update(article, {"title": "Novo"})
            await uow.commit()  # Commit explícito

    Usage direto (apenas para casos especiais):
        repo = ArticleRepository(session)
        article = await repo.create(Article(title="Test"))
        await session.commit()  # Você controla o commit
    """

    def __init__(self, db: AsyncSession, model: type[T]):
        """
        Inicializa o repository.

        Args:
            db: Sessão async do SQLAlchemy.
            model: Classe do modelo.
        """
        self.db = db
        self.model = model

    async def get_by_id(self, id: UUID | str) -> T | None:
        """
        Busca entidade por ID.

        Args:
            id: UUID ou string do ID.

        Returns:
            Entidade encontrada ou None.
        """
        if isinstance(id, str):
            id = UUID(id)

        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[T]:
        """
        Lista todas as entidades com paginação.

        Args:
            skip: Offset para paginação.
            limit: Limite de resultados.

        Returns:
            Lista de entidades.
        """
        result = await self.db.execute(select(self.model).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def create(self, obj: T) -> T:
        """
        Cria nova entidade.

        NOTA: Faz flush() para obter ID gerado, mas NÃO faz commit().
        Use UnitOfWork.commit() ou session.commit() após criar.

        Args:
            obj: Instância do modelo a criar.

        Returns:
            Entidade criada com ID gerado.

        Example:
            async with UnitOfWork(session) as uow:
                article = Article(title="Novo", project_id=project_id)
                created = await uow.articles.create(article)
                print(created.id)  # ID já está disponível (flush)
                await uow.commit()  # Persiste no banco
        """
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def create_from_dict(self, data: dict[str, Any]) -> T:
        """
        Cria entidade a partir de dicionário.

        Args:
            data: Dados para criar a entidade.

        Returns:
            Entidade criada.
        """
        obj = self.model(**data)
        return await self.create(obj)

    async def update(self, obj: T, data: dict[str, Any]) -> T:
        """
        Atualiza entidade existente.

        NOTA: Faz flush() para sincronizar, mas NÃO faz commit().
        Use UnitOfWork.commit() ou session.commit() após atualizar.

        Args:
            obj: Entidade a atualizar.
            data: Dados para atualizar (chave=atributo, valor=novo valor).

        Returns:
            Entidade atualizada.

        Example:
            async with UnitOfWork(session) as uow:
                article = await uow.articles.get_by_id(id)
                updated = await uow.articles.update(article, {"title": "Novo"})
                await uow.commit()
        """
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: T) -> None:
        """
        Remove entidade.

        NOTA: Faz flush() para sincronizar, mas NÃO faz commit().
        Use UnitOfWork.commit() ou session.commit() após deletar.

        Args:
            obj: Entidade a remover.

        Example:
            async with UnitOfWork(session) as uow:
                article = await uow.articles.get_by_id(id)
                await uow.articles.delete(article)
                await uow.commit()
        """
        await self.db.delete(obj)
        await self.db.flush()

    async def delete_by_id(self, id: UUID | str) -> bool:
        """
        Remove entidade por ID.

        Args:
            id: ID da entidade.

        Returns:
            True se removida, False se não encontrada.
        """
        obj = await self.get_by_id(id)
        if obj:
            await self.delete(obj)
            return True
        return False

    async def exists(self, id: UUID | str) -> bool:
        """
        Verifica se entidade existe.

        Args:
            id: ID da entidade.

        Returns:
            True se existe.
        """
        if isinstance(id, str):
            id = UUID(id)

        result = await self.db.execute(select(func.count()).where(self.model.id == id))
        return result.scalar_one() > 0

    async def count(self) -> int:
        """
        Conta total de entidades.

        Returns:
            Número total de entidades.
        """
        result = await self.db.execute(select(func.count()).select_from(self.model))
        return result.scalar_one()

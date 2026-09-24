"""
Factory Functions.

Funções factory para criação de dependências de forma centralizada.
Elimina duplicação e garante consistência na inicialização de componentes.
"""

from supabase import Client

from app.infrastructure.storage import StorageAdapter, SupabaseStorageAdapter


def create_storage_adapter(supabase: Client) -> StorageAdapter:
    """
    Cria StorageAdapter a partir de cliente Supabase.

    Factory centralizada que elimina duplicação na criação
    do adapter de storage em múltiplos endpoints.

    Args:
        supabase: Cliente Supabase autenticado.

    Returns:
        StorageAdapter configurado para Supabase.

    Exemplo:
        storage = create_storage_adapter(supabase)
        service = ModelExtractionService(db=db, storage=storage, ...)
    """
    return SupabaseStorageAdapter(supabase)

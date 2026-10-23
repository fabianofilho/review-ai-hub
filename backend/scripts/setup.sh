#!/bin/bash
# Script de setup do backend FastAPI
# 
# Uso: ./scripts/setup.sh
#
# O script irá:
# 1. Criar ambiente virtual com uv
# 2. Instalar dependências
# 3. Criar arquivo .env se não existir
# 4. Instruções para iniciar

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Prumo Backend - Setup Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Navegar para o diretório do backend
cd "$(dirname "$0")/.."
BACKEND_DIR=$(pwd)

echo -e "${YELLOW}📁 Diretório do backend: ${BACKEND_DIR}${NC}"
echo ""

# Verificar se uv está instalado
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv não está instalado.${NC}"
    echo -e "${YELLOW}Instale com: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi

echo -e "${GREEN}✓ uv encontrado: $(uv --version)${NC}"

# Criar ambiente virtual
echo ""
echo -e "${YELLOW}🔧 Criando ambiente virtual...${NC}"
uv venv

# Ativar ambiente virtual
echo -e "${YELLOW}🔧 Ativando ambiente virtual...${NC}"
source .venv/bin/activate

# Instalar dependências
echo ""
echo -e "${YELLOW}📦 Instalando dependências...${NC}"
uv sync

# Instalar dependências de desenvolvimento
echo -e "${YELLOW}📦 Instalando dependências de desenvolvimento...${NC}"
uv sync --extra dev

# Criar .env se não existir
if [ ! -f .env ]; then
    echo ""
    echo -e "${YELLOW}📄 Criando arquivo .env...${NC}"
    
    if [ -f .env.example ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ .env criado a partir de .env.example${NC}"
    else
        cat > .env << 'EOF'
# Prumo Backend - Environment Variables
# Copie este arquivo para .env e preencha os valores

# App
DEBUG=true
PROJECT_NAME="Prumo API"
API_V1_PREFIX="/api/v1"

# CORS
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080

# Supabase
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sua-service-role-key

# Database (PostgreSQL)
DATABASE_URL=postgresql://postgres:postgres@localhost:54322/postgres

# OpenAI
OPENAI_API_KEY=sk-...
# LLM_DEFAULT_MODEL — code default is gpt-5.6-luna; see app/core/config.py

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60

# Logfire LLM observability (optional — fully inert when unset)
# LOGFIRE_TOKEN=
EOF
        echo -e "${GREEN}✓ .env criado com valores padrão${NC}"
    fi
    
    echo -e "${YELLOW}⚠️  IMPORTANTE: Edite o arquivo .env com suas credenciais${NC}"
else
    echo ""
    echo -e "${GREEN}✓ .env já existe${NC}"
fi

# Verificar lint
echo ""
echo -e "${YELLOW}🔍 Verificando lint...${NC}"
if uv run ruff check . --fix 2>/dev/null; then
    echo -e "${GREEN}✓ Lint passou${NC}"
else
    echo -e "${YELLOW}⚠️  Alguns warnings de lint${NC}"
fi

# Verificar tipos
echo ""
echo -e "${YELLOW}🔍 Verificando tipos...${NC}"
if uv run mypy app --ignore-missing-imports 2>/dev/null; then
    echo -e "${GREEN}✓ Type check passou${NC}"
else
    echo -e "${YELLOW}⚠️  Alguns warnings de tipo${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ Setup completo!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Próximos passos:${NC}"
echo ""
echo -e "  1. Edite o arquivo ${YELLOW}.env${NC} com suas credenciais"
echo -e "     ${YELLOW}DATABASE_URL${NC} remoto recomendado (Supabase pooler):"
echo -e "     ${YELLOW}postgresql://postgres.<project_ref>:<db_password>@aws-1-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require${NC}"
echo -e "     ${YELLOW}Dica:${NC} evite host db.<project_ref>.supabase.co quando houver erro de DNS local."
echo ""
echo -e "  2. Ative o ambiente virtual:"
echo -e "     ${YELLOW}source .venv/bin/activate${NC}"
echo ""
echo -e "  3. Inicie o servidor de desenvolvimento:"
echo -e "     ${YELLOW}uvicorn app.main:app --reload${NC}"
echo ""
echo -e "  4. Acesse a documentação:"
echo -e "     ${YELLOW}http://localhost:8000/api/v1/docs${NC}"
echo ""
echo -e "  5. Execute os testes:"
echo -e "     ${YELLOW}pytest${NC}"
echo ""
echo -e "  6. Aplicar migrations no banco remoto (quando aplicável):"
echo -e "     ${YELLOW}uv run alembic upgrade head${NC}"
echo ""


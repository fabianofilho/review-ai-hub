#!/usr/bin/env bash
# =============================================================================
# validate_migration_boundaries.sh
# =============================================================================
# CI gate: Ensure no Alembic migration file *creates*, *drops*, or *alters*
# objects in the auth.* or storage.* schemas.
#
# Legitimate patterns that are ALLOWED:
#   - REFERENCES auth.users(id)        — FK to Supabase auth table
#   - auth.uid()                       — Supabase RLS helper function call
#   - auth.role()                      — Supabase role check
#   - SELECT ... FROM auth.users       — read-only reference in function body
#   - is_project_member(id, auth.uid()) — using auth function as an argument
#   - DROP POLICY IF EXISTS "..." ON storage.objects
#                                      — the article file policies on storage.objects
#                                        reference application tables, so they are
#                                        created in Alembic (0001) and dropped before
#                                        re-creation to keep the migration idempotent
#
# Patterns that are FORBIDDEN (Alembic managing Supabase-owned schemas):
#   - CREATE TABLE auth.*
#   - ALTER TABLE auth.*
#   - DROP TABLE storage.*
#   - CREATE TRIGGER ... ON auth.users (targeting auth schema)
#   - CREATE FUNCTION auth.* (creating a function IN auth schema)
#
# Usage:
#   ./scripts/validate_migration_boundaries.sh
#
# Exit codes:
#   0 — No violations found
#   1 — One or more violations found (or the versions directory is missing)
#
# =============================================================================

set -euo pipefail

VERSIONS_DIR="backend/alembic/versions"

# ---------------------------------------------------------------------------
# Locate the versions directory relative to the repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSIONS_PATH="${REPO_ROOT}/${VERSIONS_DIR}"

if [[ ! -d "${VERSIONS_PATH}" ]]; then
  echo "ERROR: Alembic versions directory not found: ${VERSIONS_PATH}"
  echo "       Run 'cd backend && uv run alembic upgrade head' first."
  exit 1
fi

echo "Scanning ${VERSIONS_PATH} for DDL operations on auth.* or storage.* schemas..."

# ---------------------------------------------------------------------------
# Step 1: Find lines that contain DDL verbs AND auth./storage. on the same line.
# Using -E (extended regex) for portability across GNU and BSD grep.
# Case-insensitive via -i.
# ---------------------------------------------------------------------------
RAW_MATCHES=$(grep -rniE \
  "(CREATE|DROP|ALTER|GRANT|REVOKE).*(auth|storage)\." \
  --include="*.py" \
  "${VERSIONS_PATH}" 2>/dev/null || true)

if [[ -z "${RAW_MATCHES}" ]]; then
  echo "OK: No cross-schema DDL contamination detected in Alembic migrations."
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: Exclude known-safe patterns (FKs, auth function calls, SELECT refs).
# Each exclusion pattern removes lines that are definitely not DDL violations.
# ---------------------------------------------------------------------------
VIOLATIONS=$(echo "${RAW_MATCHES}" | grep -vE \
  "(REFERENCES (auth|storage)\.|auth\.uid\(\)|auth\.role\(\)|FROM (auth|storage)\.|JOIN (auth|storage)\.|# .*(auth|storage)\.|DROP POLICY IF EXISTS \"[^\"]+\" ON storage\.objects)" \
  || true)

if [[ -z "${VIOLATIONS}" ]]; then
  echo "OK: No cross-schema DDL contamination detected in Alembic migrations."
  exit 0
fi

# ---------------------------------------------------------------------------
# Violations found — print them and fail
# ---------------------------------------------------------------------------
echo ""
echo "ERROR: Alembic migration files MUST NOT create, drop, or alter objects"
echo "       in the auth.* or storage.* schemas."
echo "       Supabase CLI manages those schemas exclusively."
echo ""
echo "Violations found:"
echo "---"
echo "${VIOLATIONS}"
echo "---"
echo ""
echo "Note: REFERENCES auth.users (FK) and auth.uid()/auth.role() calls are allowed."
echo ""
echo "Fix: Remove or move the offending DDL to a Supabase migration file"
echo "     (supabase/migrations/) if it targets auth.* or storage.* objects."
exit 1

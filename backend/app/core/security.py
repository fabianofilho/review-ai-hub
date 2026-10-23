"""
Security Module - JWT Validation with Supabase Auth.

Este modulo implementa validacao de JWT compativel com:
- Supabase Cloud (RS256 via JWKS)
- Supabase Local (HS256 via JWT_SECRET)

Referencia: https://supabase.com/docs/guides/auth/jwts
"""

import hashlib
from datetime import datetime, timedelta
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Security scheme for extrair Bearer token
# FastAPI gera automaticamente o security scheme in the OpenAPI
security = HTTPBearer(
    scheme_name="Supabase JWT",
    description="JWT token do Supabase Auth",
)

# JWT Secret for Supabase local (HS256)
# Em producao, JWKS e usado (RS256)
SUPABASE_LOCAL_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
LOCAL_JWT_ALGS = {"HS256"}
JWKS_JWT_ALGS = {"RS256", "ES256"}

# Clock-skew tolerance for iat/exp/nbf. PyJWT validates a future iat
# (python-jose never did) with zero default leeway, so a backend clock
# lagging Supabase Auth by even ~1s would 401 freshly minted tokens.
JWT_LEEWAY_SECONDS = 10


class TokenPayload(BaseModel):
    """
    Payload extraido do JWT do Supabase.

    Contem claims padrao do Supabase Auth.
    """

    sub: str  # User ID (UUID)
    email: str | None = None
    role: str = "authenticated"
    aal: str = "aal1"  # Authenticator Assurance Level
    exp: int | None = None  # Expiration

    # Supabase sends more claims than this (phone, session_id, iat,
    # app_metadata, ...); Pydantic's default extra="ignore" drops the ones
    # nothing reads. Add a field here only when a caller consumes it.


class JWKSCache:
    """
    Cache for JWKS do Supabase.

    Evita requisicoes repetidas ao endpoint JWKS mantendo
    as keys em cache por um periodo configuravel.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._jwks: dict[str, Any] | None = None
        self._expires_at: datetime | None = None
        self._ttl = timedelta(seconds=ttl_seconds)

    async def get_jwks(self, jwks_url: str) -> dict[str, Any]:
        """
        Return JWKS, buscando do endpoint se cache expirado.

        Args:
            jwks_url: URL do endpoint JWKS.

        Returns:
            Dict with as keys publicas (JWKS).
        """
        now = datetime.utcnow()

        if self._jwks and self._expires_at and now < self._expires_at:
            return self._jwks

        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10.0)
            response.raise_for_status()
            self._jwks = response.json()
            self._expires_at = now + self._ttl

        return self._jwks


# Instancia global do cache
_jwks_cache = JWKSCache()


async def get_jwks() -> dict[str, Any]:
    """
    Fetch JWKS do Supabase with cache.

    Returns:
        Dict with as keys publicas JWKS.
    """
    jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    return await _jwks_cache.get_jwks(jwks_url)


def _expected_issuer() -> str:
    """Return o issuer esperado with base in the SUPABASE_URL."""
    return f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"


async def _decode_with_jwks(
    token: str,
    alg: str,
    kid: str | None,
    expected_issuer: str,
) -> dict[str, Any]:
    """Decodifica JWT usando JWKS do Supabase."""
    jwks = await get_jwks()

    signing_jwk: dict[str, Any] | None = None
    for key in jwks.get("keys", []):
        if kid and key.get("kid") == kid:
            signing_jwk = key
            break

    if not signing_jwk:
        if not jwks.get("keys"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signing keys not available for Supabase JWKS",
                headers={"WWW-Authenticate": "Bearer"},
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signing key not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return jwt.decode(
        token,
        jwt.PyJWK(signing_jwk, algorithm=alg).key,
        algorithms=[alg],
        audience="authenticated",
        issuer=expected_issuer,
        leeway=JWT_LEEWAY_SECONDS,
    )


async def verify_supabase_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenPayload:
    """
    Valida JWT do Supabase Auth.

    Suporta dois modos:
    - Supabase Cloud: Validacao via JWKS (RS256)
    - Supabase Local: Validacao via JWT_SECRET (HS256)

    Args:
        credentials: Credenciais extraidas do header Authorization.

    Returns:
        TokenPayload with data do user.

    Raises:
        HTTPException 401: Token invalid or expirado.
    """
    token = credentials.credentials

    logger.debug("jwt_validation_start")

    try:
        # Decodificar header sem verificar for pegar algoritmo
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "HS256")
        expected_issuer = _expected_issuer()
        supabase_env = settings.supabase_env

        # Segredo for validacao local (HS256)
        jwt_secret = settings.SUPABASE_JWT_SECRET or SUPABASE_LOCAL_JWT_SECRET

        # Supabase Local usa HS256 with JWT_SECRET
        if supabase_env == "local":
            if alg in LOCAL_JWT_ALGS:
                logger.debug(
                    "jwt_validation_mode",
                    mode="HS256",
                    supabase_env=supabase_env,
                )

                # Em local, se falhar a primeira vez, tentamos ser mais flexiveis
                try:
                    payload = jwt.decode(
                        token,
                        jwt_secret,
                        algorithms=["HS256"],
                        audience="authenticated",
                        issuer=expected_issuer,
                        leeway=JWT_LEEWAY_SECONDS,
                    )
                except jwt.PyJWTError as e:
                    logger.warning(
                        "jwt_validation_local_strict_failed_retrying_flexible",
                        error=str(e),
                    )
                    # Tenta sem verificar issuer and audience se for local
                    payload = jwt.decode(
                        token,
                        jwt_secret,
                        algorithms=["HS256"],
                        options={"verify_aud": False, "verify_iss": False},
                        leeway=JWT_LEEWAY_SECONDS,
                    )
            elif alg in JWKS_JWT_ALGS:
                logger.debug(
                    "jwt_validation_mode",
                    mode=alg,
                    supabase_env=supabase_env,
                    kid=kid,
                )
                payload = await _decode_with_jwks(
                    token=token,
                    alg=alg,
                    kid=kid,
                    expected_issuer=expected_issuer,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: expected HS256/RS256/ES256 for SUPABASE_ENV=local",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if payload.get("iss") != expected_issuer:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: issuer mismatch for SUPABASE_ENV=local",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return TokenPayload(**payload)

        if alg not in JWKS_JWT_ALGS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: expected RS256/ES256 for SUPABASE_ENV=production",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Supabase Cloud usa RS256 with JWKS
        logger.debug(
            "jwt_validation_mode",
            mode=alg,
            supabase_env=supabase_env,
            kid=kid,
        )
        payload = await _decode_with_jwks(
            token=token,
            alg=alg,
            kid=kid,
            expected_issuer=expected_issuer,
        )

        logger.debug(
            "jwt_validation_success",
            user_id=payload.get("sub"),
            email=payload.get("email"),
        )

        return TokenPayload(**payload)

    except HTTPException:
        # Deliberate 401/403s raised above (missing key, alg/issuer mismatch)
        # must surface their specific detail, not be re-wrapped as generic.
        raise
    except jwt.PyJWTError as e:
        logger.warning(
            "jwt_validation_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except Exception as e:
        logger.error(
            "jwt_validation_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


# Alias for uso mais legivel
get_current_user = verify_supabase_jwt


async def get_current_active_user(
    user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    """
    Return user atual verificando se esta ativo.

    Pode ser expandido for verificar status do user in the banco.
    """
    # Verify token is not expired (already done by jwt.decode, but double-check)
    if user.exp:
        exp_datetime = datetime.fromtimestamp(user.exp)
        if datetime.utcnow() > exp_datetime:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


def require_aal2(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """
    Dependency que exige MFA (AAL2).

    Use em endpoints que requerem autenticacao multi-fator.
    """
    if user.aal != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication required",
        )
    return user


# =================== ENCRYPTION UTILS ===================


def check_encryption_key() -> None:
    """
    Refuse to boot with a blank or published ``ENCRYPTION_KEY`` outside local dev.

    Every per-user and per-row key (Zotero credentials, LLM connections, AI-run
    plan tokens) derives from it, so the shipped default would let anyone with
    the source decrypt them. Exits with SystemExit(1), like the pending-migration
    check, so the web service and the worker fail loudly instead of serving.
    """
    if settings.encryption_key_is_placeholder and settings.supabase_env != "local":
        logger.error(
            "placeholder_encryption_key",
            hint="set ENCRYPTION_KEY to a long random secret, or SUPABASE_ENV=local for local dev",
        )
        raise SystemExit(1)


def derive_encryption_key(user_id: str) -> bytes:
    """
    Deriva key de criptografia unica por user.

    Usado for criptografar data sensiveis como API keys.

    Args:
        user_id: user for derivar key.

    Returns:
        Bytes da key derivada.
    """
    combined = f"{settings.ENCRYPTION_KEY}{user_id}".encode()
    return hashlib.pbkdf2_hmac(
        "sha256",
        combined,
        b"review_hub_salt",
        100000,
        dklen=32,
    )

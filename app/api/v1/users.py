"""
FR-1.1.4: API token Creation
FR-1.1.5: API token Validation
FR-1.1.6: Database Schema for API Token
FR-1.1.7: API Token Expiration and Revocation
"""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.middleware.auth import verify_api_key
from app.models.api_keys import APIKeyModel
from app.services.security import generate_key, hash_key

router = APIRouter(prefix="/users", tags=["Users"])


class UserRegisterRequest(BaseModel):
    tenant_id: str = Field(..., min_length=3, max_length=64, description="Unique identifier for the tenant")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a tenant and issue a ps_alive_ API token."""
    data_dict = generate_key()
    key_id = f"key_{uuid.uuid4().hex[:16]}"
    new_api_key = APIKeyModel(
        id=key_id,
        tenant_id=user.tenant_id,
        key_hash=data_dict["key_hash"],
        key_prefix=data_dict["safe_preview"],
        is_active=True,
    )
    db.add(new_api_key)
    await db.commit()
    return {
        "tenant_id": new_api_key.tenant_id,
        "api_token": data_dict["raw_key"],
        "message": "User registered successfully",
    }


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_current_user(tenant_id: str = Depends(verify_api_key)):
    """Return the authenticated tenant_id for the provided X-API-Token / X-API-Key."""
    return {"tenant_id": tenant_id}


@router.delete("/delete", status_code=status.HTTP_202_ACCEPTED)
async def delete_user(
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Revoke/deactivate the current user's API token."""
    token = x_api_token or x_api_key
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key missing")

    hashed = hash_key(token)
    res = await db.execute(select(APIKeyModel).where(APIKeyModel.key_hash == hashed))
    record = res.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User/API token not found")

    record.is_active = False
    await db.commit()
    return {"tenant_id": record.tenant_id, "is_active": record.is_active, "message": "User deactivated successfully"}

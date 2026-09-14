from typing import List
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models.api_keys import APIKeyModel
from app.schemas.api_keys import APIKeyCreate, APIKeyResponse, APIKeyRevokeResponse, APIKeySummary
from app.services.security import generate_key
from app.middleware.auth import verify_api_key
import uuid

router = APIRouter(prefix="/api-keys", tags=["Security"])

@router.post("/", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(api_key: APIKeyCreate, db: AsyncSession = Depends(get_db)):
    # Generate a unique API key and its hash
    data_dict = generate_key()
    raw_key = data_dict["raw_key"]
    key_hash = data_dict["key_hash"]
    safe_prefix = data_dict["safe_preview"]
    id = f"key_{uuid.uuid4().hex[:16]}"

    # Create a new APIKeyModel instance
    new_api_key = APIKeyModel(
        id=id,
        tenant_id=api_key.tenant_id,
        key_hash=key_hash,
        key_prefix=safe_prefix,
        is_active=True
    )

    # Add the new API key to the database
    db.add(new_api_key)
    await db.commit()
    await db.refresh(new_api_key)

    return APIKeyResponse(
        id=new_api_key.id,
        tenant_id=new_api_key.tenant_id,
        raw_key=raw_key,
        key_prefix=new_api_key.key_prefix,
        created_at=new_api_key.created_at
    )


@router.delete("/{key_id}", response_model=APIKeyRevokeResponse, status_code=status.HTTP_200_OK)
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(verify_api_key)
):
    """
    Revoke access for an API key.
    Performs safe soft-deactivation (is_active = False) so historical audit trails remain intact.
    """
    stmt = select(APIKeyModel).where(
        APIKeyModel.id == key_id,
        APIKeyModel.tenant_id == tenant_id
    )
    res = await db.execute(stmt)
    key_record = res.scalar_one_or_none()

    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found or does not belong to your tenant"
        )

    key_record.is_active = False
    await db.commit()
    await db.refresh(key_record)

    return APIKeyRevokeResponse(
        id=key_record.id,
        tenant_id=key_record.tenant_id,
        is_active=key_record.is_active,
        message="API Key successfully revoked"
    )


@router.get("/", response_model=List[APIKeySummary], status_code=status.HTTP_200_OK)
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(verify_api_key)
):
    """
    List all API keys for the authenticated tenant.
    Never exposes raw secrets or key hashes.
    """
    stmt = select(APIKeyModel).where(APIKeyModel.tenant_id == tenant_id).order_by(APIKeyModel.created_at.desc())
    res = await db.execute(stmt)
    keys = res.scalars().all()

    return [
        APIKeySummary(
            id=k.id,
            tenant_id=k.tenant_id,
            key_prefix=k.key_prefix,
            is_active=k.is_active,
            created_at=k.created_at
        )
        for k in keys
    ]



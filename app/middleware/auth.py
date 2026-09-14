from app.database import get_db
from app.models.api_keys import APIKeyModel
from app.services.security import hash_key
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header), db: AsyncSession = Depends(get_db)) -> str:
    """
    Verify the provided API key against the stored hashed keys in the database.
    """
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key missing")
    
    hashed_key = hash_key(api_key)
    result = await db.execute(
        select(APIKeyModel).where(APIKeyModel.key_hash == hashed_key, 
                                  APIKeyModel.is_active == True)
    )
    api_key_record = result.scalar_one_or_none()

    if  api_key_record is None or not api_key_record.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

    return api_key_record.tenant_id
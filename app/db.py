import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL


Base = declarative_base()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
)

async_session = sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session():
    async with async_session() as session:
        yield session

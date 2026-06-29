import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from loguru import logger

from dotenv import load_dotenv
load_dotenv()

database_url = os.getenv("DATABASE_URL")

if not database_url:
    logger.critical("DATABASE_URL environment variable is not set.")

engine = create_engine(database_url)
logger.success(f"Database engine created")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    """Get a database session."""
    logger.trace("Creating a new database session")
    db = SessionLocal() # creates a new active session
    try:
        yield db

    finally:
        logger.trace("Closing database session")
        db.close() # close the database session after use

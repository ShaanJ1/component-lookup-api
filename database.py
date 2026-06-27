import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from dotenv import load_dotenv
load_dotenv()


database_url = os.getenv("DATABASE_URL")
engine = create_engine(database_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    """Get a database session."""
    db = SessionLocal() # creates a new active session

    try:
        yield db

    finally:
        db.close() # close the database session after use

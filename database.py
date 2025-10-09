from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True)
    status = Column(String, default="pending")
    repo_url = Column(String)
    pr_number = Column(Integer)
    results = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime, nullable=True)
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Direct connection string to Render PostgreSQL (Frankfurt Region)
SQLALCHEMY_DATABASE_URL = "postgresql://helal:ahsvW41ctetFxynt6YmKYf17j6LwJPqp@dpg-d8036s5b910c73dfsev0-a.frankfurt-postgres.render.com/nexus_2gs3"
# SQLALCHEMY_DATABASE_URL = "postgresql://postgres:123456@localhost:5432/smart_factory"

# Database engine configuration
# sslmode=require is mandatory for external connections to Render
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"sslmode": "require"}
)

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for database models
Base = declarative_base()

# Dependency to get a DB session and close it after use
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
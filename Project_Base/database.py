# from sqlalchemy import create_engine
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import sessionmaker
# import os

# SQLALCHEMY_DATABASE_URL = os.getenv(
#     "DATABASE_URL", 
#     "postgresql://helal:FdnEKO6lGZpdkdat5zkV1InNKUjszjfI@dpg-d7917a8gjchc73fb2fs0-a.frankfurt-postgres.render.com/nexus_6x0a" 
# )

# if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
#     SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# engine = create_engine(SQLALCHEMY_DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()


from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Direct connection string to Render PostgreSQL (Frankfurt Region)
SQLALCHEMY_DATABASE_URL = "postgresql://helal:FdnEKO6lGZpdkdat5zkV1InNKUjszjfI@dpg-d7917a8gjchc73fb2fs0-a.frankfurt-postgres.render.com/nexus_6x0a"

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
from sqlalchemy import text

from app.db import engine

with engine.connect() as conn:
    row = conn.execute(text("SELECT current_user, current_database(), version()")).one()
    print(row)
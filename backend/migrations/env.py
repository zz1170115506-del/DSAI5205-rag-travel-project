from alembic import context
from app.core.config import get_settings
from app.core.db import database
from app.models import Base

config = context.config
engine, _ = database(get_settings().database_url)

if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

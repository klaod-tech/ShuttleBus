import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.models import LAYERS, Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # 층별로 리비전을 나눠 만들 때만 쓴다: ALEMBIC_MAX_LAYER=1 alembic revision --autogenerate
    max_layer = os.environ.get("ALEMBIC_MAX_LAYER")
    if max_layer is None or type_ != "table":
        return True
    return LAYERS.get(name, 99) <= int(max_layer)


def database_url() -> str:
    # 시험은 sqlalchemy.url로 시험용 DB를 넘긴다
    return config.get_main_option("sqlalchemy.url") or settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

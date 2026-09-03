from src.utils.migrations import run_alembic_upgrade_head


if __name__ == '__main__':
    from src.db import engine
    import config as project_config

    run_alembic_upgrade_head(
        alembic_ini=project_config.PROJECT.ALEMBIC_INI,
        engine=engine
    )

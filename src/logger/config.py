import yaml

import config


def get_logging_config() -> dict:
    with open(config.LOGGING.LOGGING_CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


LOGGING_CONFIG = get_logging_config()

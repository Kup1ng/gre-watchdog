# gre_watchdog/common/log.py
import os, logging
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_dir: str):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    fh = RotatingFileHandler(os.path.join(log_dir, f"{name}.log"), maxBytes=5_000_000, backupCount=5)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

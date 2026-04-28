"""
Generic logger: get_logger() ile isimlendirilmiş logger alırsın.
Seviye ve format tek yerden ayarlanabilir.
"""
import logging
import sys
from typing import Optional


def get_logger(
    name: Optional[str] = None,
    level: int = logging.INFO,
    verbose: bool = True,
) -> logging.Logger:
    """
    İsimlendirilmiş bir logger döndürür. Aynı name ile tekrar çağrılırsa aynı logger verilir.

    Args:
        name: Logger adı (None ise root).
        level: logging.DEBUG, INFO, WARNING, ERROR.
        verbose: False ise WARNING ve üzeri, True ise level kullanılır.

    Örnek:
        log = get_logger("my_script")
        log.info("Başladı")
        log.error("Hata")
    """
    logger = logging.getLogger(name or "root")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    effective = level if verbose else logging.WARNING
    logger.setLevel(effective)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(effective)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

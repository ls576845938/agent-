from __future__ import annotations

import logging


def get_logger(name: str = "quant_us") -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return logging.getLogger(name)

import logging
import sys
from contextvars import ContextVar

import structlog
from app.config import settings

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_logger(name: str = __name__):
    return structlog.get_logger(name).bind(correlation_id=correlation_id_var.get())


def configure_logging():

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.log_level.upper() == "DEBUG" else logging.WARNING
    )

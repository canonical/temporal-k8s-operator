# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define logging helpers."""

import functools


def log_event_handler(logger):
    """Log with the provided logger when a event handler method is executed."""

    def decorator(method):
        @functools.wraps(method)
        def decorated(self, event):
            logger.info(f"* running {self.__class__.__name__}.{method.__name__}")
            try:
                return method(self, event)
            finally:
                logger.info(f"* completed {self.__class__.__name__}.{method.__name__}")

        return decorated

    return decorator

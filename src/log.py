# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define logging helpers."""

import functools


def log_event_handler(logger):
    """Log with the provided logger when a event handler method is executed.

    Args:
        logger: logger used to log events.

    Returns:
        Decorator wrapper.
    """

    def decorator(method):
        """Log decorator wrapper.

        Args:
            method: method wrapped by the decorator.

        Returns:
            Decorated method.
        """

        @functools.wraps(method)
        def decorated(self, event):
            """Log decorator method.

            Args:
                event: The event triggered when the relation changes.

            Returns:
                Decorated method.

            Raises:
                Exception: Re-raised from the wrapped method after it is logged.
            """
            logger.info("* running %s.%s", self.__class__.__name__, method.__name__)
            try:
                return method(self, event)
            except Exception:
                logger.exception("unhandled exception in %s.%s", self.__class__.__name__, method.__name__)
                raise
            finally:
                logger.info("* finished %s.%s", self.__class__.__name__, method.__name__)

        return decorated

    return decorator

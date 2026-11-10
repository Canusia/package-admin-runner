"""The task the django-tasks backport runner enqueues (Django < 6.0).

``django_tasks``' database worker finds a task by the import path of its
function and refuses anything that isn't a ``Task``. So unlike the Django 6.0
runner, which wraps ``execute_command`` when it first runs, the task has to
live at module level here.

Importing this module validates the task against the default ``TASKS``
backend, so only the runner and the worker import it.
"""

from __future__ import annotations

import signal
import threading

from django_tasks import task

from .tasks import SIGTERM_RECEIVED, execute_command


@task()
def execute_command_task(command_name: str, kwargs: dict, execution_pk: int) -> None:
    # A flag left from an earlier run must not stop the worker now.
    SIGTERM_RECEIVED.clear()
    try:
        # Raises again after saving a failed run, SIGTERM failures included.
        execute_command(command_name, kwargs, execution_pk)
    finally:
        if SIGTERM_RECEIVED.is_set():
            SIGTERM_RECEIVED.clear()
            _forward_sigterm()


def _forward_sigterm() -> None:
    """Hand a SIGTERM caught during the run to the worker's own handler.

    While a command runs, the runner's handler replaces ``db_worker``'s, so
    the worker never hears about the signal and would pick up the next task
    only to be killed partway through it. Calling the restored handler after
    the execution is saved lets the worker shut down as it was asked to.

    Signal handlers belong to the main thread, so a run in another thread
    (ImmediateBackend in a threaded server) passes nothing on.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    handler = signal.getsignal(signal.SIGTERM)
    if not callable(handler) or getattr(handler, "is_admin_runner_handler", False):
        return
    try:
        handler(signal.SIGTERM, None)
    except SystemExit:
        # db_worker exits at once when it was already shutting down (an
        # earlier SIGINT). It stops after this task anyway; exiting here
        # would only mark the finished task as failed.
        pass

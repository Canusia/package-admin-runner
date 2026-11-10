"""The django-tasks backport runner (Django < 6.0 with the ``django_tasks`` package)."""

import signal

import pytest
from django.core.management import call_command
from django.test import override_settings

from django_admin_runner.models import CommandExecution
from django_admin_runner.runners import get_runner
from tests.settings import HAS_DJANGO_TASKS_BACKPORT, HAS_DJANGO_TASKS_DB

pytestmark = pytest.mark.skipif(
    not HAS_DJANGO_TASKS_BACKPORT, reason="needs the django-tasks package"
)

IMMEDIATE = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        "ENQUEUE_ON_COMMIT": False,
    }
}
DATABASE = {
    "default": {
        "BACKEND": "django_tasks.backends.database.DatabaseBackend",
        "QUEUES": ["default", "admin_runner"],
    }
}
TASK_PATH = "django_admin_runner.backport_tasks.execute_command_task"


@pytest.fixture
def runner():
    from django_admin_runner.runners.django_tasks_backport import DjangoTasksBackportRunner

    return DjangoTasksBackportRunner()


@pytest.fixture
def keep_signal_handlers():
    """db_worker installs its own SIGINT/SIGTERM handlers; put pytest's back."""
    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGQUIT"):
        signals.append(signal.SIGQUIT)
    saved = {sig: signal.getsignal(sig) for sig in signals}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


def _run(runner, command_name, user=None):
    execution = CommandExecution.objects.create(command_name=command_name)
    result = runner.run(command_name, {}, user, execution)
    execution.refresh_from_db()
    return execution, result


def _db_worker():
    call_command("db_worker", "--batch", "--queue-name", "admin_runner", "--no-startup-delay")


def test_backend_name_selects_the_runner():
    with override_settings(ADMIN_RUNNER_BACKEND="django-tasks"):
        assert get_runner().backend == "django-tasks"


@pytest.mark.django_db
class TestImmediateBackend:
    @pytest.fixture(autouse=True)
    def _tasks(self, settings):
        settings.TASKS = IMMEDIATE

    def test_success(self, runner):
        execution, result = _run(runner, "simple_command")
        assert execution.status == CommandExecution.Status.SUCCESS
        assert "simple output" in execution.output_text("stdout")
        assert execution.backend == "django-tasks"
        assert result.task_id != ""
        assert result.is_async is False

    def test_failure(self, runner):
        execution, _ = _run(runner, "failing_command")
        assert execution.status == CommandExecution.Status.FAILED
        assert "intentional failure" in execution.output_text("stderr")


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(not HAS_DJANGO_TASKS_DB, reason="database backend left django-tasks in 0.12")
class TestDatabaseBackend:
    @pytest.fixture(autouse=True)
    def _tasks(self, settings):
        settings.TASKS = DATABASE
        settings.ADMIN_RUNNER_QUEUE = "admin_runner"

    def test_enqueue_stores_a_task_the_worker_can_load(self, runner):
        from django_tasks.backends.database.models import DBTaskResult

        execution, result = _run(runner, "simple_command")

        assert execution.status == CommandExecution.Status.PENDING
        assert result.is_async is True
        row = DBTaskResult.objects.get(id=execution.task_id)
        assert row.task_path == TASK_PATH
        assert row.queue_name == "admin_runner"
        # the worker loads the task by path, and refuses anything but a Task
        assert row.task.func.__name__ == "execute_command_task"

    def test_worker_runs_the_command(self, runner, keep_signal_handlers):
        execution, _ = _run(runner, "simple_command")
        _db_worker()
        execution.refresh_from_db()
        assert execution.status == CommandExecution.Status.SUCCESS
        assert "simple output" in execution.output_text("stdout")

    def test_worker_records_a_failing_command(self, runner, keep_signal_handlers):
        execution, _ = _run(runner, "failing_command")
        _db_worker()
        execution.refresh_from_db()
        assert execution.status == CommandExecution.Status.FAILED
        assert "intentional failure" in execution.output_text("stderr")

    def test_sigterm_mid_run_fails_the_run_and_stops_the_worker(self, runner, keep_signal_handlers):
        stopped, _ = _run(runner, "sigterm_command")
        waiting, _ = _run(runner, "simple_command")
        _db_worker()
        stopped.refresh_from_db()
        waiting.refresh_from_db()
        assert stopped.status == CommandExecution.Status.FAILED
        assert "SIGTERM" in stopped.output_text("stderr")
        # the worker shut down instead of taking the next task
        assert waiting.status == CommandExecution.Status.PENDING

    def test_queue_outside_the_backend_fails_the_run(self, runner, settings):
        settings.ADMIN_RUNNER_QUEUE = "nope"
        execution, result = _run(runner, "simple_command")
        assert execution.status == CommandExecution.Status.FAILED
        assert "Failed to enqueue" in execution.output_text("stderr")
        assert result.is_async is False


class TestSigtermForwarding:
    """A SIGTERM during a run must still reach db_worker's own handler."""

    def _call_task(self, monkeypatch, *, sigterm, stale=False):
        from django_admin_runner import backport_tasks, tasks

        def fake_execute(command_name, kwargs, execution_pk):
            # execute_command clears the flag only once it claims the run
            if sigterm:
                tasks.SIGTERM_RECEIVED.set()

        monkeypatch.setattr(backport_tasks, "execute_command", fake_execute)
        if stale:
            tasks.SIGTERM_RECEIVED.set()
        received = []
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: received.append(signum))
        try:
            backport_tasks.execute_command_task.call("simple_command", {}, 1)
        finally:
            signal.signal(signal.SIGTERM, previous)
            tasks.SIGTERM_RECEIVED.clear()
        return received

    def test_sigterm_during_the_run_is_passed_on(self, monkeypatch):
        assert self._call_task(monkeypatch, sigterm=True) == [signal.SIGTERM]

    def test_sigterm_that_failed_the_run_reaches_the_worker(self, monkeypatch):
        from django_admin_runner import backport_tasks, tasks

        def fake_execute(command_name, kwargs, execution_pk):
            tasks.SIGTERM_RECEIVED.set()
            raise tasks.WorkerStoppedError("SIGTERM")

        monkeypatch.setattr(backport_tasks, "execute_command", fake_execute)
        received = []
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: received.append(signum))
        try:
            with pytest.raises(tasks.WorkerStoppedError):
                backport_tasks.execute_command_task.call("simple_command", {}, 1)
        finally:
            signal.signal(signal.SIGTERM, previous)
        assert received == [signal.SIGTERM]

    def test_no_sigterm_nothing_is_passed_on(self, monkeypatch):
        assert self._call_task(monkeypatch, sigterm=False) == []

    def test_flag_left_by_an_earlier_run_is_ignored(self, monkeypatch):
        assert self._call_task(monkeypatch, sigterm=False, stale=True) == []

    def test_worker_already_exiting_does_not_exit_mid_task(self, monkeypatch):
        from django_admin_runner import backport_tasks, tasks

        def exiting_handler(signum, frame):
            raise SystemExit(1)

        monkeypatch.setattr(
            backport_tasks, "execute_command", lambda *a: tasks.SIGTERM_RECEIVED.set()
        )
        previous = signal.signal(signal.SIGTERM, exiting_handler)
        try:
            backport_tasks.execute_command_task.call("simple_command", {}, 1)
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_run_outside_the_main_thread_passes_nothing_on(self, monkeypatch):
        import threading

        from django_admin_runner import backport_tasks, tasks

        monkeypatch.setattr(
            backport_tasks, "execute_command", lambda *a: tasks.SIGTERM_RECEIVED.set()
        )
        received = []
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: received.append(signum))
        try:
            thread = threading.Thread(
                target=backport_tasks.execute_command_task.call,
                args=("simple_command", {}, 1),
            )
            thread.start()
            thread.join()
        finally:
            signal.signal(signal.SIGTERM, previous)
            tasks.SIGTERM_RECEIVED.clear()
        assert received == []

    def test_runner_handler_records_the_signal(self):
        from django_admin_runner.tasks import (
            SIGTERM_RECEIVED,
            WorkerStoppedError,
            _install_sigterm_handler,
            _restore_sigterm_handler,
        )

        installed = _install_sigterm_handler()
        try:
            assert not SIGTERM_RECEIVED.is_set()
            handler = signal.getsignal(signal.SIGTERM)
            with pytest.raises(WorkerStoppedError):
                handler(signal.SIGTERM, None)
            assert SIGTERM_RECEIVED.is_set()
        finally:
            _restore_sigterm_handler(installed)
            SIGTERM_RECEIVED.clear()

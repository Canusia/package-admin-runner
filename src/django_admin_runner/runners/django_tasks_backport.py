from __future__ import annotations

from django.urls import reverse

from . import BaseCommandRunner, RunResult
from .django_tasks import _is_immediate_backend


class DjangoTasksBackportRunner(BaseCommandRunner):
    """Enqueues commands with the ``django-tasks`` backport (Django 5.2).

    Same behaviour as :class:`DjangoTaskRunner`, for projects on Django
    below 6.0 that use the ``django_tasks`` package. Commands go to the
    ``ADMIN_RUNNER_QUEUE`` queue (default ``"default"``), which must be in
    the backend's ``QUEUES``. Stop works through the stop flag only:
    ``db_worker`` runs tasks in its own process, so there is no force stop.
    """

    backend = "django-tasks"

    def run(self, command_name, kwargs, triggered_by, execution) -> RunResult:
        from django.conf import settings

        execution.backend = self.backend
        execution.save(update_fields=["backend"])

        redirect_url = reverse(
            "admin:django_admin_runner_commandexecution_change",
            args=[execution.pk],
        )

        try:
            from django_admin_runner.backport_tasks import execute_command_task

            task = execute_command_task
            queue_name = getattr(settings, "ADMIN_RUNNER_QUEUE", None)
            if queue_name:
                task = task.using(queue_name=queue_name)
            result = task.enqueue(command_name, kwargs, execution.pk)
        except Exception as exc:
            from django_admin_runner.models import CommandExecution
            from django_admin_runner.tasks import _append_output

            execution.status = CommandExecution.Status.FAILED
            _append_output(execution, "stderr", f"Failed to enqueue task: {exc}")
            execution.save(update_fields=["status"])
            return RunResult(
                execution=execution,
                redirect_url=redirect_url,
                is_async=False,
                backend=self.backend,
                task_id="",
            )

        task_id = str(result.id) if getattr(result, "id", None) is not None else ""
        execution.task_id = task_id
        execution.save(update_fields=["task_id"])
        execution.refresh_from_db()

        return RunResult(
            execution=execution,
            redirect_url=redirect_url,
            is_async=not _is_immediate_backend(),
            backend=self.backend,
            task_id=task_id,
        )

# Runners

A runner decides *how* a management command is executed. Configure it with:

```python
# settings.py
ADMIN_RUNNER_BACKEND = "django"  # default
```

## Built-in runners

### `"django"` — DjangoTaskRunner (default)

Uses Django 6.0's built-in `django.tasks` system. When `ImmediateBackend` is
configured, commands run synchronously in the request cycle. With other backends
(e.g. `DatabaseBackend`) they run asynchronously in a worker.

```python
TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
    }
}
# ADMIN_RUNNER_BACKEND not required — "django" is the default
```

### `"django-tasks"` — DjangoTasksBackportRunner (Django 5.2)

*Added in the Canusia fork.* For Django below 6.0, which has no `django.tasks`,
using the [`django-tasks`](https://pypi.org/project/django-tasks/) backport
package. The `"django"` default falls back to this runner when `django.tasks`
can't be imported.

```bash
pip install "django-admin-runner[django-tasks]"
```

```python
INSTALLED_APPS += ["django_tasks", "django_tasks.backends.database"]
TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.database.DatabaseBackend",
        "QUEUES": ["default", "admin_runner"],
    }
}
ADMIN_RUNNER_BACKEND = "django-tasks"
ADMIN_RUNNER_QUEUE = "admin_runner"  # optional; must be in QUEUES
```

Run a worker for the queue with
`python manage.py db_worker --queue-name admin_runner`.

- The task is `django_admin_runner.backport_tasks.execute_command_task`. The
  database worker loads tasks by import path, so it is defined at module level.
- A queue that isn't in `QUEUES` fails the run with "Failed to enqueue task".
- Use django-tasks below 0.12: 0.12 moved the database backend into a
  separate package.
- Importing the task checks it against the default backend, so when `QUEUES`
  is set it must include `"default"`.
- `ADMIN_RUNNER_QUEUE` applies only to this runner. The Django 6.0 `"django"`
  runner always uses the default queue.
- Stop works through the stop flag; there is no force stop.
- If the worker gets SIGTERM during a run, the run is marked failed and the
  signal is then passed to `db_worker`, so the worker shuts down instead of
  taking the next task.

### `"sync"` — SyncCommandRunner

Runs commands inline with no task backend at all. Simple and reliable for
development or low-traffic deployments.

```python
ADMIN_RUNNER_BACKEND = "sync"
```

### `"celery"` — CeleryCommandRunner

Enqueues commands as Celery tasks. Requires `celery` installed.

```python
ADMIN_RUNNER_BACKEND = "celery"
CELERY_BROKER_URL = "redis://localhost:6379/0"
```

### `"django-q2"` — DjangoQ2CommandRunner

Enqueues commands as django-q2 tasks. Uses Django's ORM as its message broker,
so no external services (Redis, Docker) are needed. Requires `django-q2` installed.

The only runner with full schedule support (cron / interval / one-off,
see [Scheduling](scheduling.md)) and PID-targeted force stop.

```python
ADMIN_RUNNER_BACKEND = "django-q2"

Q_CLUSTER = {
    "name": "DJANGORM",
    "orm": "default",  # uses Django's database as the broker
}
```

## RunResult

Every `runner.run()` returns a `RunResult`:

```python
@dataclass
class RunResult:
    execution: CommandExecution
    redirect_url: str
    is_async: bool
    backend: str
    task_id: str = ""
```

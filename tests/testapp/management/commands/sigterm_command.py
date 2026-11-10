import os
import signal
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sends SIGTERM to its own process, like a pod shutdown mid-run."

    def handle(self, *args, **options):
        self.stdout.write("before sigterm")
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(1)  # the handler raises before this returns
        self.stdout.write("after sigterm")

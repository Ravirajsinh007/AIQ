from django.core.management.base import BaseCommand

from apps.blueprints.workflow import process_due_paper_releases


class Command(BaseCommand):
    help = 'Release approved generated papers whose scheduled release time has arrived.'

    def handle(self, *args, **options):
        released = process_due_paper_releases()
        self.stdout.write(self.style.SUCCESS(f'Released {released} scheduled paper(s).'))

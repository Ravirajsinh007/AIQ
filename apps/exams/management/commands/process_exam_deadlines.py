from django.core.management.base import BaseCommand

from apps.exams.services import process_expired_attempts


class Command(BaseCommand):
    help = 'Auto-submit in-progress exam attempts whose server-side deadline has passed.'

    def handle(self, *args, **options):
        count = process_expired_attempts()
        self.stdout.write(self.style.SUCCESS(f'Auto-submitted {count} expired exam attempt(s).'))

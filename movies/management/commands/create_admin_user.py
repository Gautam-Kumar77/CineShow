from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Idempotently creates an admin superuser for the analytics dashboard.'

    def handle(self, *args, **options):
        username = 'admin'
        password = 'Admin@CineShow2026'
        email = 'admin@cineshow.com'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'is_staff': True,
                'is_superuser': True,
            }
        )

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Successfully created admin user '{username}' with password '{password}'."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated admin user '{username}' password to '{password}'."))

from django.apps import AppConfig

class MoviesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'movies'

    def ready(self):
        # Import and start background email worker thread
        from .email_queue import start_worker
        start_worker()

        # Import and start background seat lock cleanup worker thread
        from .seat_lock_manager import start_lock_cleanup_worker
        start_lock_cleanup_worker()



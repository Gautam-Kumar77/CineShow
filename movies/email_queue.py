import time
import logging
import threading
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.db import close_old_connections
from .models import EmailTask

logger = logging.getLogger(__name__)

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 10  # seconds between retries in the background

_worker_thread = None
_lock = threading.Lock()
_should_run = True

def start_worker():
    global _worker_thread
    with _lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="CineShowEmailWorker")
            _worker_thread.start()
            logger.info("CineShow Email Worker Thread started.")

def stop_worker():
    global _should_run
    _should_run = False

def _worker_loop():
    logger.info("Starting email worker loop...")
    while _should_run:
        try:
            close_old_connections()
            # Fetch pending or failed tasks that have retry_count < MAX_RETRIES
            tasks = EmailTask.objects.filter(
                status__in=['PENDING', 'FAILED'],
                retry_count__lt=MAX_RETRIES
            ).order_by('created_at')[:10]

            if not tasks:
                time.sleep(3)
                continue

            for task in tasks:
                if not _should_run:
                    break
                process_task(task)
                
            time.sleep(2)
        except Exception as e:
            logger.exception("Error in email worker loop")
            time.sleep(5)
    logger.info("Email worker loop stopped.")

def process_task(task):
    task.retry_count += 1
    task.save()
    try:
        # Render email content using Django templates
        html_message = render_to_string(task.template_name, task.context_data)
        plain_message = strip_tags(html_message)

        # Send mail
        send_mail(
            subject=task.subject,
            message=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@cineshow.com'),
            recipient_list=[task.recipient],
            html_message=html_message,
            fail_silently=False,
        )
        # Success!
        task.status = 'SENT'
        task.last_error = None
        task.save()
        logger.info(f"Successfully sent email task {task.id} to {task.recipient}")
    except Exception as e:
        logger.exception(f"Failed to send email task {task.id} (Attempt {task.retry_count})")
        task.status = 'FAILED'
        task.last_error = str(e)
        task.save()

def enqueue_email(booking, recipient, subject, template_name, context_data):
    task = EmailTask.objects.create(
        booking=booking,
        recipient=recipient,
        subject=subject,
        template_name=template_name,
        context_data=context_data,
        status='PENDING'
    )
    # Start worker if not already running, and trigger processing
    start_worker()
    return task

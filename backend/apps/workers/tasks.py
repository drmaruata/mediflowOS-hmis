"""Workers — Celery tasks."""
from celery import shared_task


@shared_task(bind=True, max_retries=3)
def compute_indicators(self, tenant_id, period_start, period_end):
    """Nightly indicator computation for a tenant."""
    # Placeholder — will be implemented with the indicator engine
    pass


@shared_task(bind=True, max_retries=3)
def sync_abdm_callback(self, callback_id):
    """Process ABDM callback asynchronously."""
    pass


@shared_task(bind=True, max_retries=3)
def send_notification(self, tenant_id, payload):
    """Send a notification via the notification engine."""
    pass

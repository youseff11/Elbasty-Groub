"""
Management command لإرسال إيميلات تذكير مواعيد الدفع الآجل.
يُشغَّل يومياً عبر cron job:
  0 8 * * * python manage.py send_payment_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from store.models import PaymentSchedule


class Command(BaseCommand):
    help = 'إرسال إيميلات تذكير للدفعات الآجلة التي موعدها بعد 3 أيام'

    def handle(self, *args, **options):
        today = timezone.now().date()
        target_date = today + timezone.timedelta(days=3)

        # الدفعات التي موعدها بعد 3 أيام بالظبط ولم يُرسَل لها تذكير
        schedules = PaymentSchedule.objects.filter(
            due_date=target_date,
            reminder_sent=False,
            status__in=['pending', 'partial']
        ).select_related('movement__product', 'invoice')

        admin_email = getattr(settings, 'ADMIN_REMINDER_EMAIL', settings.EMAIL_HOST_USER)

        count = 0
        for schedule in schedules:
            schedule.send_reminder_email(admin_email)
            count += 1

        self.stdout.write(
            self.style.SUCCESS(f'✅ تم إرسال {count} تذكير بنجاح')
        )

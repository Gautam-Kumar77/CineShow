from django.test import TestCase, Client
from django.utils import timezone
from django.core import mail
from django.urls import reverse
from unittest.mock import patch
import json
from movies.models import Movie, Theater, Show, Booking, EmailTask
from movies.email_queue import process_task, enqueue_email


class BookingEmailTestCase(TestCase):
    def setUp(self):
        # Create sample movie, theater, show
        self.movie = Movie.objects.create(
            title="Inception",
            release_date=timezone.now().date(),
            rating=8.8
        )
        self.theater = Theater.objects.create(
            name="Grand Cinema",
            location="Downtown"
        )
        self.show = Show.objects.create(
            movie=self.movie,
            theater=self.theater,
            show_time=timezone.now() + timezone.timedelta(hours=2),
            price=10.00
        )
        self.client = Client()

    def test_booking_api_creates_booking_and_queues_email(self):
        # Clear outbox
        mail.outbox = []
        
        # Make a POST request to booking API
        url = reverse('booking_api')
        payload = {
            'show_id': self.show.id,
            'email': 'customer@example.com',
            'seats': 'A1, A2'
        }
        response = self.client.post(
            url, 
            data=json.dumps(payload), 
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        # Verify Booking is created in DB
        self.assertTrue(Booking.objects.filter(email='customer@example.com').exists())
        booking = Booking.objects.get(email='customer@example.com')
        self.assertEqual(booking.seat_numbers, 'A1, A2')
        self.assertEqual(booking.total_amount, 20.00) # 10.00 * 2 seats
        
        # Verify EmailTask is created in DB
        self.assertTrue(EmailTask.objects.filter(booking=booking).exists())
        task = EmailTask.objects.get(booking=booking)
        self.assertEqual(task.status, 'PENDING')
        self.assertEqual(task.recipient, 'customer@example.com')
        
        # Run process_task directly to simulate worker processing
        process_task(task)
        
        # Verify task state changes to SENT
        task.refresh_from_db()
        self.assertEqual(task.status, 'SENT')
        self.assertEqual(task.retry_count, 1)
        self.assertNil = task.last_error
        
        # Verify email is sent and received in django test mail outbox
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertEqual(sent_email.to, ['customer@example.com'])
        self.assertIn("CineShow Ticket Confirmation - Inception", sent_email.subject)
        self.assertIn("A1, A2", sent_email.body)

    def test_email_retry_logic_on_failure(self):
        # Create an email task
        booking = Booking.objects.create(
            show=self.show,
            email='retry@example.com',
            seat_numbers='B1',
            payment_id='PAY-TEST-RETRY',
            total_amount=10.00
        )
        task = EmailTask.objects.create(
            booking=booking,
            recipient='retry@example.com',
            subject='Test retry',
            template_name='movies/emails/ticket_confirmation.html',
            context_data={'movie_title': 'Inception'}
        )
        
        # Mock send_mail to raise an exception
        with patch('movies.email_queue.send_mail', side_effect=Exception("SMTP Connection Timeout")):
            process_task(task)
            
        # Verify status is FAILED and retry_count is 1
        task.refresh_from_db()
        self.assertEqual(task.status, 'FAILED')
        self.assertEqual(task.retry_count, 1)
        self.assertIn("SMTP Connection Timeout", task.last_error)

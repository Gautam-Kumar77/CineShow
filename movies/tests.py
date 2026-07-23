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
        self.assertIsNone(task.last_error)
        
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


class TrailerEmbeddingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.movie_with_trailer = Movie.objects.create(
            title="Inception",
            release_date="2010-07-16",
            rating=8.8,
            trailer_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.movie_without_trailer = Movie.objects.create(
            title="Interstellar",
            release_date="2014-11-07",
            rating=8.6,
            trailer_url=""
        )

    def test_youtube_id_extraction(self):
        from movies.models import extract_youtube_id
        # Valid URLs
        self.assertEqual(extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_id("https://youtube.com/embed/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(extract_youtube_id("https://youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        
        # Invalid URLs
        self.assertIsNone(extract_youtube_id("https://google.com/watch?v=dQw4w9WgXcQ"))
        self.assertIsNone(extract_youtube_id("malicious_script_injection_here"))

    def test_movie_validation(self):
        from django.core.exceptions import ValidationError
        # Valid trailer url doesn't raise error
        self.movie_with_trailer.full_clean()
        
        # Invalid trailer url raises ValidationError
        movie = Movie(
            title="Bad Trailer Link",
            release_date="2020-01-01",
            rating=5.0,
            trailer_url="https://notyoutube.com/watch?v=123"
        )
        with self.assertRaises(ValidationError):
            movie.full_clean()

    def test_movie_detail_view(self):
        # Movie with trailer
        response = self.client.get(reverse('movie_detail', args=[self.movie_with_trailer.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['has_trailer'], True)
        self.assertEqual(response.context['video_id'], "dQw4w9WgXcQ")
        self.assertContains(response, "dQw4w9WgXcQ")
        
        # Movie without trailer
        response = self.client.get(reverse('movie_detail', args=[self.movie_without_trailer.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['has_trailer'], False)
        self.assertContains(response, "Official trailer is not available")

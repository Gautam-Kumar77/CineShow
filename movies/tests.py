from django.test import TestCase, TransactionTestCase, Client
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
        
        # Simulate completing payment via mock payment gateway
        checkout_url = data['checkout_url']
        mock_response = self.client.post(checkout_url)
        self.assertEqual(mock_response.status_code, 302) # Redirect to /payment/success/

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


from concurrent.futures import ThreadPoolExecutor
from movies.models import SeatLock
from movies.seat_lock_manager import lock_seats, release_seats, get_seats_status, cleanup_expired_locks, SeatConflictError

class SeatReservationConcurrencyTestCase(TransactionTestCase):
    def setUp(self):
        self.movie = Movie.objects.create(
            title="Tenet",
            release_date=timezone.now().date(),
            rating=7.5
        )
        self.theater = Theater.objects.create(
            name="IMAX Laser",
            location="Central Mall"
        )
        self.show = Show.objects.create(
            movie=self.movie,
            theater=self.theater,
            show_time=timezone.now() + timezone.timedelta(hours=3),
            price=15.00
        )
        self.client = Client()

    def test_atomic_seat_locking_and_status(self):
        session_1 = "session_user_1"
        session_2 = "session_user_2"

        # User 1 locks seat A1 and A2
        result = lock_seats(self.show.id, ["A1", "A2"], session_1, timeout_seconds=120)
        self.assertEqual(result['seats'], ["A1", "A2"])
        self.assertEqual(result['timeout_seconds'], 120)

        # Query seat status for User 1
        seats_u1 = get_seats_status(self.show.id, session_id=session_1)
        a1_u1 = next(s for s in seats_u1 if s['seat_number'] == 'A1')
        self.assertEqual(a1_u1['status'], 'locked_by_me')

        # Query seat status for User 2
        seats_u2 = get_seats_status(self.show.id, session_id=session_2)
        a1_u2 = next(s for s in seats_u2 if s['seat_number'] == 'A1')
        self.assertEqual(a1_u2['status'], 'locked_by_other')
        self.assertGreater(a1_u2['lock_info']['seconds_remaining'], 0)

        # User 2 attempts to lock seat A1 -> raises SeatConflictError
        with self.assertRaises(SeatConflictError) as ctx:
            lock_seats(self.show.id, ["A1"], session_2)
        self.assertIn("A1", ctx.exception.conflicting_seats)

    def test_concurrent_seat_reservation_race_condition(self):
        """
        Simulates 10 concurrent threads attempting to lock seat 'B5' at the exact same millisecond.
        Verifies that database row-level locking ensures EXACTLY 1 thread succeeds and 9 threads fail cleanly.
        """
        target_seat = ["B5"]
        num_threads = 10
        success_list = []
        failure_list = []

        def attempt_lock(thread_index):
            session_id = f"concurrent_session_{thread_index}"
            try:
                lock_seats(self.show.id, target_seat, session_id)
                success_list.append(session_id)
            except SeatConflictError as e:
                failure_list.append(session_id)
            except Exception as e:
                failure_list.append(f"error_{e}")

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(attempt_lock, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        # Assert exactly 1 thread succeeded and 9 threads failed with conflict
        self.assertEqual(len(success_list), 1)
        self.assertEqual(len(failure_list), 9)

        # Verify active lock in DB belongs to the winner
        winning_session = success_list[0]
        lock = SeatLock.objects.get(show=self.show, seat_number='B5', status='LOCKED')
        self.assertEqual(lock.session_id, winning_session)

    def test_auto_lock_expiration_and_cleanup(self):
        session_id = "expiring_session"
        
        # Lock seat A3 with past expiry time (-10 seconds)
        now = timezone.now()
        past_expiry = now - timezone.timedelta(seconds=10)
        SeatLock.objects.create(
            show=self.show,
            seat_number="A3",
            session_id=session_id,
            expires_at=past_expiry,
            status='LOCKED'
        )

        # Run background cleanup method first
        cleaned_count = cleanup_expired_locks()
        self.assertGreaterEqual(cleaned_count, 1)

        # Verify seat is treated as available by status check
        seats = get_seats_status(self.show.id, session_id="other_user")
        a3_seat = next(s for s in seats if s['seat_number'] == 'A3')
        self.assertEqual(a3_seat['status'], 'available')

        # Verify lock status changed to EXPIRED in database
        lock = SeatLock.objects.get(show=self.show, seat_number="A3")
        self.assertEqual(lock.status, 'EXPIRED')

    def test_release_seats_api(self):
        session_id = "release_test_session"
        lock_seats(self.show.id, ["C1", "C2"], session_id)

        url = reverse('release_seats_api', args=[self.show.id])
        payload = {
            'seats': ["C1", "C2"],
            'session_id': session_id
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['released_count'], 2)

        # Verify seats are now available
        seats = get_seats_status(self.show.id, session_id=session_id)
        c1 = next(s for s in seats if s['seat_number'] == 'C1')
        self.assertEqual(c1['status'], 'available')

    def test_booking_converts_seat_locks(self):
        session_id = "booking_lock_session"
        lock_seats(self.show.id, ["D1"], session_id)

        # Create booking and complete mock payment
        booking_url = reverse('booking_api')
        payload = {
            'show_id': self.show.id,
            'email': 'lockinguser@example.com',
            'seats': 'D1',
            'session_id': session_id
        }
        resp = self.client.post(booking_url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        # Complete mock payment
        self.client.post(data['checkout_url'])

        # Verify SeatLock converted to CONVERTED
        lock = SeatLock.objects.get(show=self.show, seat_number='D1')
        self.assertEqual(lock.status, 'CONVERTED')

        # Verify seat status is now 'booked'
        seats = get_seats_status(self.show.id)
        d1 = next(s for s in seats if s['seat_number'] == 'D1')
        self.assertEqual(d1['status'], 'booked')


from django.contrib.auth.models import User
from movies.analytics import get_admin_analytics_data, CACHE_KEY
from django.core.cache import cache

class AdminAnalyticsTestCase(TestCase):
    def setUp(self):
        self.regular_user = User.objects.create_user(username='regular', password='password123')
        self.admin_user = User.objects.create_superuser(username='admin_test', password='Admin@CineShow2026', email='admin@test.com')
        self.client = Client()

        self.movie = Movie.objects.create(title="Avatar", release_date=timezone.now().date(), rating=8.0)
        self.theater = Theater.objects.create(name="Cinepolis", location="Mall")
        self.show = Show.objects.create(movie=self.movie, theater=self.theater, show_time=timezone.now(), price=20.00)
        
        Booking.objects.create(show=self.show, email='u1@test.com', seat_numbers='A1, A2', total_amount=40.00, status='SUCCESS')
        Booking.objects.create(show=self.show, email='u2@test.com', seat_numbers='A3', total_amount=20.00, status='SUCCESS')
        Booking.objects.create(show=self.show, email='u3@test.com', seat_numbers='A4', total_amount=20.00, status='FAILED')

    def test_unauthorized_access_protection(self):
        # Unauthenticated GET dashboard -> 302 redirect to login
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin_login'), response.url)

        # Unauthenticated API request -> 403 Forbidden
        api_response = self.client.get(reverse('admin_analytics_api'))
        self.assertEqual(api_response.status_code, 403)

        # Regular non-staff user API request -> 403 Forbidden
        self.client.login(username='regular', password='password123')
        api_response_reg = self.client.get(reverse('admin_analytics_api'))
        self.assertEqual(api_response_reg.status_code, 403)

    def test_admin_authentication_and_dashboard_access(self):
        # Admin login
        login_resp = self.client.post(reverse('admin_login'), {'username': 'admin_test', 'password': 'Admin@CineShow2026'})
        self.assertEqual(login_resp.status_code, 302)
        self.assertIn(reverse('admin_dashboard'), login_resp.url)

        # Dashboard access
        dashboard_resp = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(dashboard_resp.status_code, 200)
        self.assertContains(dashboard_resp, "Real-Time Analytics Dashboard")

        # API access
        api_resp = self.client.get(reverse('admin_analytics_api'))
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.json()['data']
        self.assertEqual(data['revenue']['total'], 60.00)
        self.assertEqual(data['bookings_breakdown']['total'], 3)
        self.assertEqual(data['bookings_breakdown']['success'], 2)
        self.assertEqual(data['bookings_breakdown']['failed'], 1)

    def test_analytics_aggregation_and_caching(self):
        cache.delete(CACHE_KEY)
        
        # Cold run (from DB)
        res1 = get_admin_analytics_data(bypass_cache=True)
        self.assertFalse(res1['from_cache'])
        self.assertEqual(res1['revenue']['total'], 60.00)

        # Warm run (from cache)
        res2 = get_admin_analytics_data(bypass_cache=False)
        self.assertTrue(res2['from_cache'])
        self.assertEqual(res2['revenue']['total'], 60.00)

        # Bypass cache force refresh
        res3 = get_admin_analytics_data(bypass_cache=True)
        self.assertFalse(res3['from_cache'])



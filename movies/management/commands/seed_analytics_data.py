import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from movies.models import Movie, Theater, Show, Booking

class Command(BaseCommand):
    help = 'Seeds the database with 50,000+ bookings to benchmark analytics aggregation queries.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=50000,
            help='Number of bookings to seed (default: 50000)'
        )

    def handle(self, *args, **options):
        count = options['count']
        self.stdout.write(f"Starting analytics data seeding ({count:,} records)...")

        # Ensure we have shows available
        shows = list(Show.objects.all())
        if not shows:
            self.stdout.write("No shows found. Seeding initial shows...")
            from movies.views import populate_initial_data
            populate_initial_data()
            shows = list(Show.objects.all())

        if not shows:
            self.stderr.write("Failed to retrieve or create shows.")
            return

        statuses = ['SUCCESS'] * 85 + ['FAILED'] * 10 + ['PENDING'] * 5
        seat_rows = ['A', 'B', 'C', 'D']
        sample_emails = [f"user_{i}@example.com" for i in range(1, 500)]

        now = timezone.now()
        batch_size = 10000
        total_created = 0

        self.stdout.write(f"Generating {count:,} booking records in batches of {batch_size:,}...")

        for batch_start in range(0, count, batch_size):
            current_batch_count = min(batch_size, count - batch_start)
            bookings_to_create = []

            for i in range(current_batch_count):
                show = random.choice(shows)
                status = random.choice(statuses)
                email = random.choice(sample_emails)

                # Random seat count between 1 and 4
                num_seats = random.randint(1, 4)
                assigned_seats = [f"{random.choice(seat_rows)}{random.randint(1, 8)}" for _ in range(num_seats)]
                unique_seats = list(set(assigned_seats))
                seat_numbers = ", ".join(unique_seats)

                total_amount = float(show.price) * len(unique_seats)

                # Spread timestamps over the past 30 days and across all 24 hours of the day
                days_ago = random.randint(0, 30)
                hours_offset = random.randint(0, 23)
                minutes_offset = random.randint(0, 59)
                seconds_offset = random.randint(0, 59)

                created_at = now - timedelta(
                    days=days_ago,
                    hours=hours_offset,
                    minutes=minutes_offset,
                    seconds=seconds_offset
                )

                payment_id = f"pi_seed_{batch_start + i}_{random.randint(1000, 9999)}" if status == 'SUCCESS' else None

                booking = Booking(
                    show=show,
                    email=email,
                    seat_numbers=seat_numbers,
                    status=status,
                    payment_id=payment_id,
                    stripe_checkout_session_id=f"sess_seed_{batch_start + i}",
                    total_amount=total_amount,
                )
                # Override created_at auto_now_add via memory attribute
                booking.created_at = created_at
                bookings_to_create.append(booking)

            # Bulk create in DB
            created_objects = Booking.objects.bulk_create(bookings_to_create, batch_size=batch_size)
            
            # Update created_at timestamps in bulk using raw query / bulk update if needed
            # In Django bulk_create with auto_now_add, created_at gets set to NOW by default in DB.
            # To update created_at for realistic time-series analytics, update created_at explicitly:
            ids_and_times = [(b.id, b.created_at) for b in created_objects]
            
            # Perform bulk update for created_at
            for obj, time_val in zip(created_objects, [b.created_at for b in bookings_to_create]):
                obj.created_at = time_val
            Booking.objects.bulk_update(created_objects, ['created_at'], batch_size=batch_size)

            total_created += len(created_objects)
            self.stdout.write(f"Inserted {total_created:,} / {count:,} bookings...")

        self.stdout.write(self.style.SUCCESS(f"Database successfully seeded with {total_created:,} analytics bookings!"))

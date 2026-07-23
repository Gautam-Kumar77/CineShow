import re
from django.core.exceptions import ValidationError
from django.db import models

def extract_youtube_id(url):
    if not url:
        return None
    # Supports www.youtube.com, m.youtube.com, youtube.com, youtu.be, embed, v, shorts, and query params
    pattern = r'(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|v/|shorts/)|youtu\.be/)([\w-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

def validate_youtube_url(value):
    if value:
        if not extract_youtube_id(value):
            raise ValidationError("Please enter a valid YouTube URL.")

class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Language(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Movie(models.Model):
    title = models.CharField(max_length=255, db_index=True)
    release_date = models.DateField(db_index=True)
    rating = models.FloatField(db_index=True)
    trailer_url = models.URLField(max_length=500, blank=True, null=True, validators=[validate_youtube_url])

    genres = models.ManyToManyField(Genre)
    languages = models.ManyToManyField(Language)

    def __str__(self):
        return self.title

class Theater(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name} ({self.location})"

class Show(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='shows')
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='shows')
    show_time = models.DateTimeField()
    price = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.movie.title} at {self.theater.name} - {self.show_time.strftime('%Y-%m-%d %I:%M %p')}"

class Booking(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='bookings')
    email = models.EmailField(db_index=True)
    seat_numbers = models.CharField(max_length=255) # e.g. "A1, A2, A3"
    payment_id = models.CharField(max_length=100, unique=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Booking {self.id} for {self.email} - {self.show.movie.title}"

class EmailTask(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='email_tasks', null=True, blank=True)
    recipient = models.EmailField(db_index=True)
    subject = models.CharField(max_length=255)
    template_name = models.CharField(max_length=255)
    context_data = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    retry_count = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Email to {self.recipient} - {self.status} (Retries: {self.retry_count})"


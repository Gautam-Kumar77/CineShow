import time
import logging
from datetime import timedelta
from django.core.cache import cache
from django.db.models import Sum, Count, Q, F, FloatField, ExpressionWrapper
from django.db.models.functions import ExtractHour, TruncDay
from django.utils import timezone
from .models import Movie, Theater, Show, Booking

logger = logging.getLogger(__name__)

CACHE_KEY = 'cineshow_admin_analytics_cache_v1'
CACHE_TTL = 60  # 60 seconds in-memory cache TTL

def get_admin_analytics_data(bypass_cache=False):
    """
    Retrieves real-time aggregated analytics optimized for large datasets (50,000+ bookings).
    Uses database-level aggregation functions (Sum, Count, ExtractHour) and in-memory caching.
    """
    if not bypass_cache:
        cached_data = cache.get(CACHE_KEY)
        if cached_data:
            cached_data['from_cache'] = True
            return cached_data

    start_time = time.time()
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    # 1. Database-Level Revenue Aggregations
    revenue_aggregates = Booking.objects.aggregate(
        total_revenue=Sum('total_amount', filter=Q(status='SUCCESS')),
        today_revenue=Sum('total_amount', filter=Q(status='SUCCESS', created_at__gte=today_start)),
        week_revenue=Sum('total_amount', filter=Q(status='SUCCESS', created_at__gte=week_start)),
        month_revenue=Sum('total_amount', filter=Q(status='SUCCESS', created_at__gte=month_start)),
        total_bookings=Count('id'),
        success_bookings=Count('id', filter=Q(status='SUCCESS')),
        failed_bookings=Count('id', filter=Q(status='FAILED')),
        pending_bookings=Count('id', filter=Q(status='PENDING')),
    )

    total_revenue = float(revenue_aggregates['total_revenue'] or 0.0)
    today_revenue = float(revenue_aggregates['today_revenue'] or 0.0)
    week_revenue = float(revenue_aggregates['week_revenue'] or 0.0)
    month_revenue = float(revenue_aggregates['month_revenue'] or 0.0)

    total_bookings = revenue_aggregates['total_bookings'] or 0
    success_bookings = revenue_aggregates['success_bookings'] or 0
    failed_bookings = revenue_aggregates['failed_bookings'] or 0
    pending_bookings = revenue_aggregates['pending_bookings'] or 0

    cancellation_rate = round((failed_bookings / total_bookings) * 100, 2) if total_bookings > 0 else 0.0
    success_rate = round((success_bookings / total_bookings) * 100, 2) if total_bookings > 0 else 0.0

    # 2. Most Popular Movies (Ranked by successful bookings & revenue)
    popular_movies_qs = Movie.objects.annotate(
        booking_count=Count('shows__bookings', filter=Q(shows__bookings__status='SUCCESS')),
        total_movie_revenue=Sum('shows__bookings__total_amount', filter=Q(shows__bookings__status='SUCCESS'))
    ).filter(booking_count__gt=0).order_by('-booking_count')[:5]

    popular_movies = [
        {
            'id': m.id,
            'title': m.title,
            'rating': m.rating,
            'booking_count': m.booking_count,
            'total_revenue': float(m.total_movie_revenue or 0.0)
        }
        for m in popular_movies_qs
    ]

    # 3. Busiest Theaters (Seat Occupancy Rate & Bookings)
    # Total capacity = number of shows * 32 seats (A1-D8)
    theaters_qs = Theater.objects.annotate(
        shows_count=Count('shows', distinct=True),
        success_bookings=Count('shows__bookings', filter=Q(shows__bookings__status='SUCCESS'), distinct=True),
        theater_revenue=Sum('shows__bookings__total_amount', filter=Q(shows__bookings__status='SUCCESS'))
    ).filter(shows_count__gt=0).order_by('-success_bookings')

    theaters_data = []
    for t in theaters_qs:
        capacity = t.shows_count * 32
        occupancy_rate = round((t.success_bookings / capacity) * 100, 1) if capacity > 0 else 0.0
        theaters_data.append({
            'id': t.id,
            'name': t.name,
            'location': t.location,
            'shows_count': t.shows_count,
            'capacity': capacity,
            'success_bookings': t.success_bookings,
            'occupancy_rate': min(100.0, occupancy_rate),
            'total_revenue': float(t.theater_revenue or 0.0)
        })

    # 4. Peak Booking Hours (0 to 23 Hours Distribution)
    hourly_qs = Booking.objects.filter(
        status='SUCCESS'
    ).annotate(
        hour=ExtractHour('created_at')
    ).values('hour').annotate(
        count=Count('id'),
        revenue=Sum('total_amount')
    ).order_by('hour')

    hourly_map = {h: {'count': 0, 'revenue': 0.0} for h in range(24)}
    for row in hourly_qs:
        h = row['hour']
        if h is not None and 0 <= h < 24:
            hourly_map[h] = {
                'count': row['count'],
                'revenue': float(row['revenue'] or 0.0)
            }

    peak_hours_data = [
        {
            'hour': h,
            'label': f"{h:02d}:00 - {h:02d}:59",
            'count': hourly_map[h]['count'],
            'revenue': hourly_map[h]['revenue']
        }
        for h in range(24)
    ]

    # Find peak hour
    peak_hour_item = max(peak_hours_data, key=lambda x: x['count']) if peak_hours_data else {'label': 'N/A', 'count': 0}

    execution_time_ms = round((time.time() - start_time) * 1000, 2)

    result = {
        'from_cache': False,
        'execution_time_ms': execution_time_ms,
        'cached_at': now.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'revenue': {
            'today': today_revenue,
            'week': week_revenue,
            'month': month_revenue,
            'total': total_revenue,
        },
        'bookings_breakdown': {
            'total': total_bookings,
            'success': success_bookings,
            'failed': failed_bookings,
            'pending': pending_bookings,
            'success_rate': success_rate,
            'cancellation_rate': cancellation_rate,
        },
        'popular_movies': popular_movies,
        'theaters': theaters_data,
        'peak_hours': peak_hours_data,
        'peak_hour_info': peak_hour_item,
    }

    # Store in memory cache
    cache.set(CACHE_KEY, result, CACHE_TTL)
    return result

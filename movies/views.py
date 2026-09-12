import time
import json
import stripe
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import datetime, timedelta
from django.contrib.auth import authenticate, login, logout
from .models import Genre, Language, Movie, Theater, Show, Booking, EmailTask, StripeEvent, SeatLock
from .seat_lock_manager import get_seats_status, lock_seats, release_seats, convert_locks_to_booking, SeatConflictError
from .analytics import get_admin_analytics_data

stripe.api_key = settings.STRIPE_SECRET_KEY

def populate_initial_data():
    if Theater.objects.exists() and Show.objects.exists():
        return
    
    # Create some theaters if they don't exist
    t1, _ = Theater.objects.get_or_create(name="PVR IMAX", location="Forum Mall, Koramangala")
    t2, _ = Theater.objects.get_or_create(name="Cinepolis Premium", location="Royal Meenakshi Mall")
    t3, _ = Theater.objects.get_or_create(name="Inox Gold Class", location="Mantri Square Mall")

    # Create shows for all movies
    movies = Movie.objects.all()
    now = timezone.now()
    
    for movie in movies:
        # Show 1: Today 3 PM
        show_time_1 = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if show_time_1 < now:
            show_time_1 += timedelta(days=1)
        Show.objects.get_or_create(movie=movie, theater=t1, show_time=show_time_1, price=12.50)

        # Show 2: Today 7 PM
        show_time_2 = now.replace(hour=19, minute=0, second=0, microsecond=0)
        if show_time_2 < now:
            show_time_2 += timedelta(days=1)
        Show.objects.get_or_create(movie=movie, theater=t2, show_time=show_time_2, price=15.00)

        # Show 3: Tomorrow 9:30 PM
        show_time_3 = (now + timedelta(days=1)).replace(hour=21, minute=30, second=0, microsecond=0)
        Show.objects.get_or_create(movie=movie, theater=t3, show_time=show_time_3, price=18.50)

def movie_list(request):
    # Populate initial theaters and shows
    populate_initial_data()

    # 1. Retrieve query parameters
    selected_genres = request.GET.getlist('genre')
    selected_languages = request.GET.getlist('language')
    sort_by = request.GET.get('sort', 'title')

    # 2. Base queryset for movie listing
    movies = Movie.objects.all()

    # 3. Apply filters
    if selected_genres:
        movies = movies.filter(genres__name__in=selected_genres)
    if selected_languages:
        movies = movies.filter(languages__name__in=selected_languages)

    # 4. Apply distinct to avoid duplicate rows due to ManyToMany joins
    movies = movies.distinct()

    # 5. Sorting
    valid_sorts = {
        'title': 'title',
        '-title': '-title',
        'release_date': 'release_date',
        '-release_date': '-release_date',
        'rating': 'rating',
        '-rating': '-rating',
    }
    sort_field = valid_sorts.get(sort_by, 'title')
    movies = movies.order_by(sort_field)

    # 6. Prefetch related fields to solve N+1 query problem
    movies = movies.prefetch_related('genres', 'languages')

    # 7. Pagination (12 movies per page)
    paginator = Paginator(movies, 12)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # 8. Dynamic Filter Counts using Q() and Count()
    # Genre counts
    genre_filter_movies = Movie.objects.all()
    if selected_languages:
        genre_filter_movies = genre_filter_movies.filter(languages__name__in=selected_languages)
    
    genres_with_counts = Genre.objects.annotate(
        movie_count=Count('movie', filter=Q(movie__in=genre_filter_movies))
    ).order_by('name')

    # Language counts
    lang_filter_movies = Movie.objects.all()
    if selected_genres:
        lang_filter_movies = lang_filter_movies.filter(genres__name__in=selected_genres)

    languages_with_counts = Language.objects.annotate(
        movie_count=Count('movie', filter=Q(movie__in=lang_filter_movies))
    ).order_by('name')

    # 9. Preserve existing query parameters while pagination links are clicked
    query_params = request.GET.copy()
    if 'page' in query_params:
        query_params.pop('page')
    url_params = query_params.urlencode()

    context = {
        'page_obj': page_obj,
        'genres': genres_with_counts,
        'languages': languages_with_counts,
        'selected_genres': selected_genres,
        'selected_languages': selected_languages,
        'sort_by': sort_by,
        'url_params': url_params,
        'total_movies': paginator.count,
    }
    return render(request, 'movies/movie_list.html', context)

def get_shows_api(request, movie_id):
    populate_initial_data()
    shows = Show.objects.filter(movie_id=movie_id).select_related('theater').order_by('show_time')
    shows_data = []
    for s in shows:
        shows_data.append({
            'id': s.id,
            'theater_name': s.theater.name,
            'theater_location': s.theater.location,
            'show_time': s.show_time.strftime('%I:%M %p (%a, %b %d)'),
            'price': float(s.price)
        })
    return JsonResponse({'shows': shows_data})

def get_seats_status_api(request, show_id):
    session_id = request.GET.get('session_id', '')
    try:
        seats_data = get_seats_status(show_id, session_id=session_id)
        return JsonResponse({'status': 'success', 'seats': seats_data})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def lock_seats_api(request, show_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    try:
        data = json.loads(request.body)
        seats = data.get('seats', [])
        session_id = data.get('session_id')
        if not seats or not session_id:
            return JsonResponse({'status': 'error', 'message': 'Seats and session_id are required'}, status=400)
        
        result = lock_seats(show_id, seats, session_id)
        return JsonResponse({'status': 'success', 'data': result})
    except SeatConflictError as e:
        return JsonResponse({
            'status': 'conflict',
            'message': str(e),
            'conflicting_seats': e.conflicting_seats
        }, status=409)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def release_seats_api(request, show_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    try:
        data = json.loads(request.body)
        seats = data.get('seats', [])
        session_id = data.get('session_id')
        released_count = release_seats(show_id, seats, session_id)
        return JsonResponse({'status': 'success', 'released_count': released_count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def booking_api(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        show_id = data.get('show_id')
        email = data.get('email')
        seats = data.get('seats')
        session_id = data.get('session_id')
        
        if not show_id or not email or not seats:
            return JsonResponse({'status': 'error', 'message': 'Missing required fields'}, status=400)
            
        show = Show.objects.get(id=show_id)
        seat_list = [s.strip() for s in seats.split(',') if s.strip()]
        num_seats = len(seat_list)
        total_amount = show.price * num_seats

        # Concurrency safety: Atomically verify or acquire seat lock
        if session_id:
            try:
                lock_seats(show_id, seat_list, session_id)
            except SeatConflictError as e:
                return JsonResponse({
                    'status': 'conflict',
                    'message': str(e),
                    'conflicting_seats': e.conflicting_seats
                }, status=409)
        
        # Create pending booking
        booking = Booking.objects.create(
            show=show,
            email=email,
            seat_numbers=seats,
            total_amount=total_amount,
            status='PENDING'
        )
        
        try:
            stripe_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
            if stripe_key and stripe_key != 'sk_test_dummy_key' and not stripe_key.startswith('sk_test_dummy'):
                # Create Stripe Checkout Session
                checkout_session = stripe.checkout.Session.create(
                    line_items=[
                        {
                            'price_data': {
                                'currency': 'inr',
                                'unit_amount': int(show.price * 100),
                                'product_data': {
                                    'name': f"{show.movie.title} Ticket(s)",
                                    'description': f"{show.theater.name} - {show.show_time.strftime('%b %d, %I:%M %p')}",
                                },
                            },
                            'quantity': num_seats,
                        },
                    ],
                    mode='payment',
                    client_reference_id=str(booking.id),
                    customer_email=email,
                    success_url=settings.DOMAIN_URL + '/payment/success/',
                    cancel_url=settings.DOMAIN_URL + '/payment/cancel/',
                    metadata={
                        'booking_id': booking.id,
                    }
                )
                
                # Save session id to booking
                booking.stripe_checkout_session_id = checkout_session.id
                booking.save()
                checkout_url = checkout_session.url
            else:
                # Fallback to interactive mock checkout when using dummy API key
                booking.stripe_checkout_session_id = f"mock_session_{booking.id}"
                booking.save()
                checkout_url = f"/mock-payment/{booking.id}/"
        except Exception as e:
            # Fallback to mock checkout if Stripe API call fails for any reason
            booking.stripe_checkout_session_id = f"mock_session_{booking.id}"
            booking.save()
            checkout_url = f"/mock-payment/{booking.id}/"
        
        return JsonResponse({
            'status': 'success', 
            'checkout_url': checkout_url,
            'message': 'Redirecting to payment gateway...'
        })
    except Show.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Show not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
def stripe_webhook_api(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        return HttpResponse(status=400)

    if StripeEvent.objects.filter(event_id=event.id).exists():
        return HttpResponse(status=200)

    StripeEvent.objects.create(event_id=event.id, event_type=event.type)

    if event.type == 'checkout.session.completed':
        session = event.data.object
        booking_id = session.client_reference_id
        
        try:
            booking = Booking.objects.get(id=booking_id)
            if booking.status != 'SUCCESS':
                booking.status = 'SUCCESS'
                booking.payment_id = session.payment_intent or session.id
                booking.save()
                
                # Convert seat locks to CONVERTED
                seat_list = [s.strip() for s in booking.seat_numbers.split(',') if s.strip()]
                SeatLock.objects.filter(
                    show=booking.show,
                    seat_number__in=[s.upper() for s in seat_list],
                    status='LOCKED'
                ).update(status='CONVERTED')

                # Enqueue Email
                from .email_queue import enqueue_email
                context_data = {
                    'movie_title': booking.show.movie.title,
                    'theater_name': booking.show.theater.name,
                    'show_time': booking.show.show_time.strftime("%A, %b %d at %I:%M %p"),
                    'seat_numbers': booking.seat_numbers,
                    'payment_id': booking.payment_id,
                    'theater_location': booking.show.theater.location,
                    'total_amount': f"{booking.total_amount:.2f}"
                }
                
                enqueue_email(
                    booking=booking,
                    recipient=booking.email,
                    subject=f"CineShow Ticket Confirmation - {booking.show.movie.title}",
                    template_name="movies/emails/ticket_confirmation.html",
                    context_data=context_data
                )
        except Booking.DoesNotExist:
            pass

    elif event.type in ['checkout.session.expired', 'checkout.session.async_payment_failed']:
        session = event.data.object
        booking_id = session.client_reference_id
        try:
            booking = Booking.objects.get(id=booking_id)
            if booking.status == 'PENDING':
                booking.status = 'FAILED'
                booking.save()
        except Booking.DoesNotExist:
            pass

    return HttpResponse(status=200)

def payment_success(request):
    return render(request, 'movies/payment_success.html')

def payment_cancel(request):
    return render(request, 'movies/payment_cancel.html')

@csrf_exempt
def mock_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if request.method == 'POST':
        # Simulate webhook success
        if booking.status != 'SUCCESS':
            booking.status = 'SUCCESS'
            booking.payment_id = f"pi_mock_{booking.id}"
            booking.save()

            # Convert seat locks to CONVERTED
            seat_list = [s.strip() for s in booking.seat_numbers.split(',') if s.strip()]
            SeatLock.objects.filter(
                show=booking.show,
                seat_number__in=[s.upper() for s in seat_list],
                status='LOCKED'
            ).update(status='CONVERTED')
            
            from .email_queue import enqueue_email
            context_data = {
                'movie_title': booking.show.movie.title,
                'theater_name': booking.show.theater.name,
                'show_time': booking.show.show_time.strftime("%A, %b %d at %I:%M %p"),
                'seat_numbers': booking.seat_numbers,
                'payment_id': booking.payment_id,
                'theater_location': booking.show.theater.location,
                'total_amount': f"{booking.total_amount:.2f}"
            }
            enqueue_email(
                booking=booking,
                recipient=booking.email,
                subject=f"CineShow Ticket Confirmation - {booking.show.movie.title}",
                template_name="movies/emails/ticket_confirmation.html",
                context_data=context_data
            )
        return redirect('/payment/success/')
        
    return render(request, 'movies/mock_payment.html', {'booking': booking})

def email_dashboard(request):
    # Stats
    stats = EmailTask.objects.aggregate(
        total=Count('id'),
        sent=Count('id', filter=Q(status='SENT')),
        pending=Count('id', filter=Q(status='PENDING')),
        failed=Count('id', filter=Q(status='FAILED'))
    )
    
    # List of tasks
    tasks = EmailTask.objects.all().order_by('-created_at')
    
    context = {
        'stats': stats,
        'tasks': tasks
    }
    return render(request, 'movies/dashboard.html', context)

@csrf_exempt
def retry_email_api(request, task_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    
    task = get_object_or_404(EmailTask, id=task_id)
    task.status = 'PENDING'
    task.retry_count = 0
    task.last_error = None
    task.save()
    
    from .email_queue import start_worker
    start_worker()
    
    return JsonResponse({'status': 'success', 'message': 'Task rescheduled successfully'})

def movie_detail(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    
    from .models import extract_youtube_id
    video_id = extract_youtube_id(movie.trailer_url)
    
    context = {
        'movie': movie,
        'video_id': video_id,
        'has_trailer': bool(video_id),
    }
    return render(request, 'movies/movie_detail.html', context)


def admin_login_view(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')

    error_message = None
    if request.method == 'POST':
        username_input = request.POST.get('username', '').strip()
        password_input = request.POST.get('password', '').strip()

        user = authenticate(request, username=username_input, password=password_input)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('admin_dashboard')
        else:
            error_message = "Invalid admin credentials or insufficient privileges."

    return render(request, 'movies/admin_login.html', {'error_message': error_message})


def admin_logout_view(request):
    logout(request)
    return redirect('admin_login')


def admin_dashboard_view(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('admin_login')

    analytics_data = get_admin_analytics_data()
    return render(request, 'movies/admin_dashboard.html', {'analytics': analytics_data})


def admin_analytics_api(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized: Admin access required'}, status=403)

    bypass_cache = request.GET.get('refresh', 'false').lower() == 'true'
    data = get_admin_analytics_data(bypass_cache=bypass_cache)
    return JsonResponse({'status': 'success', 'data': data})



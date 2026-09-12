from django.urls import path
from . import views

urlpatterns = [
    path('', views.movie_list, name='movie_list'),
    path('movies/<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('api/movies/<int:movie_id>/shows/', views.get_shows_api, name='get_shows_api'),
    path('api/shows/<int:show_id>/seats/', views.get_seats_status_api, name='get_seats_status_api'),
    path('api/shows/<int:show_id>/lock-seats/', views.lock_seats_api, name='lock_seats_api'),
    path('api/shows/<int:show_id>/release-seats/', views.release_seats_api, name='release_seats_api'),
    path('api/bookings/', views.booking_api, name='booking_api'),
    path('api/webhook/stripe/', views.stripe_webhook_api, name='stripe_webhook_api'),
    path('mock-payment/<int:booking_id>/', views.mock_payment, name='mock_payment'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('email-dashboard/', views.email_dashboard, name='email_dashboard'),
    path('api/email-tasks/<int:task_id>/retry/', views.retry_email_api, name='retry_email_api'),
    path('admin-analytics/login/', views.admin_login_view, name='admin_login'),
    path('admin-analytics/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin-analytics/', views.admin_dashboard_view, name='admin_dashboard'),
    path('api/admin-analytics/data/', views.admin_analytics_api, name='admin_analytics_api'),
]


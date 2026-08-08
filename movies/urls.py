from django.urls import path
from . import views

urlpatterns = [
    path('', views.movie_list, name='movie_list'),
    path('movies/<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('api/movies/<int:movie_id>/shows/', views.get_shows_api, name='get_shows_api'),
    path('api/bookings/', views.booking_api, name='booking_api'),
    path('api/webhook/stripe/', views.stripe_webhook_api, name='stripe_webhook_api'),
    path('mock-payment/<int:booking_id>/', views.mock_payment, name='mock_payment'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('email-dashboard/', views.email_dashboard, name='email_dashboard'),
    path('api/email-tasks/<int:task_id>/retry/', views.retry_email_api, name='retry_email_api'),
]


from django.urls import path
from . import views

urlpatterns = [
    path('', views.movie_list, name='movie_list'),
    path('api/movies/<int:movie_id>/shows/', views.get_shows_api, name='get_shows_api'),
    path('api/bookings/', views.booking_api, name='booking_api'),
    path('email-dashboard/', views.email_dashboard, name='email_dashboard'),
    path('api/email-tasks/<int:task_id>/retry/', views.retry_email_api, name='retry_email_api'),
]


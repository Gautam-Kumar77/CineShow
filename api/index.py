import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CineShow.settings')

from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

_django_app = get_wsgi_application()
_db_initialized = False

def init_db_once():
    global _db_initialized
    if _db_initialized:
        return
    _db_initialized = True
    try:
        call_command('migrate', interactive=False)
        from movies.models import Movie, Genre, Language
        if not Movie.objects.exists():
            genres_list = ['Action', 'Comedy', 'Drama', 'Sci-Fi', 'Romance', 'Thriller', 'Horror', 'Adventure']
            languages_list = ['English', 'Hindi', 'Spanish', 'French', 'Japanese', 'Korean']
            
            Genre.objects.bulk_create([Genre(name=g) for g in genres_list], ignore_conflicts=True)
            Language.objects.bulk_create([Language(name=l) for l in languages_list], ignore_conflicts=True)
            
            genres = list(Genre.objects.all())
            languages = list(Language.objects.all())
            
            sample_movies = [
                ("Inception", "2010-07-16", 8.8, "https://www.youtube.com/watch?v=YoHD9XEInc0"),
                ("Interstellar", "2014-11-07", 8.7, "https://www.youtube.com/watch?v=zSWdZVtXT7E"),
                ("The Dark Knight", "2008-07-18", 9.0, "https://www.youtube.com/watch?v=EXeTwQWrcwY"),
                ("Avatar: The Way of Water", "2022-12-16", 7.6, "https://www.youtube.com/watch?v=d9MyW72ELq0"),
                ("Oppenheimer", "2023-07-21", 8.9, "https://www.youtube.com/watch?v=uYPbbksJxIg"),
                ("Dune: Part Two", "2024-03-01", 8.6, "https://www.youtube.com/watch?v=Way9Dexny3w"),
                ("Spider-Man: Across the Spider-Verse", "2023-06-02", 8.7, "https://www.youtube.com/watch?v=cqGjhVJWtEg"),
                ("Avengers: Endgame", "2019-04-26", 8.4, "https://www.youtube.com/watch?v=TcMBFSGVi1c"),
                ("Parasite", "2019-05-30", 8.5, "https://www.youtube.com/watch?v=5xH0j4f1_U4"),
                ("Gladiator II", "2024-11-22", 7.8, "https://www.youtube.com/watch?v=4mgBp3jC2gU"),
                ("Cyberpunk Horizon", "2025-06-15", 8.3, "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
                ("The Quantum Rift", "2026-01-10", 8.1, "https://www.youtube.com/watch?v=tgbNymZ7vqY")
            ]
            
            for title, rdate, rrating, rtrailer in sample_movies:
                m = Movie.objects.create(
                    title=title,
                    release_date=rdate,
                    rating=rrating,
                    trailer_url=rtrailer
                )
                m.genres.set(genres[:2])
                m.languages.set(languages[:2])
            
            from movies.views import populate_initial_data
            populate_initial_data()

            from django.contrib.auth.models import User
            if not User.objects.filter(username='admin').exists():
                User.objects.create_superuser('admin', 'admin@cineshow.com', 'Admin@CineShow2026')
    except Exception as e:
        print("Vercel startup init notice:", e)

def app(environ, start_response):
    init_db_once()
    return _django_app(environ, start_response)


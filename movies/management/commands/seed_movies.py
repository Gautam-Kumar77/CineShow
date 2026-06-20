import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from movies.models import Genre, Language, Movie

class Command(BaseCommand):
    help = 'Seeds the database with genres, languages, and 5000 movies.'

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        # Clear existing data to allow re-seeding
        Movie.objects.all().delete()
        Genre.objects.all().delete()
        Language.objects.all().delete()

        # Define basic list of genres and languages
        genres_list = ['Action', 'Comedy', 'Drama', 'Sci-Fi', 'Romance', 'Thriller', 'Horror', 'Documentary', 'Animation', 'Adventure']
        languages_list = ['English', 'Hindi', 'Spanish', 'French', 'German', 'Japanese', 'Korean', 'Telugu', 'Tamil', 'Malayalam']

        genres = [Genre(name=name) for name in genres_list]
        languages = [Language(name=name) for name in languages_list]

        # Bulk create lookup categories
        Genre.objects.bulk_create(genres)
        Language.objects.bulk_create(languages)

        # Retrieve from DB to access automatically generated IDs
        genres = list(Genre.objects.all())
        languages = list(Language.objects.all())

        self.stdout.write(f"Created {len(genres)} genres and {len(languages)} languages.")

        # Create movies in memory first
        adjectives = ["The Last", "Epic", "Dark", "Golden", "Silent", "Lost", "Wild", "Secret", "Eternal", "Cosmic", "Midnight", "Broken", "Rising", "Flying", "Hidden"]
        nouns = ["Knight", "Journey", "Warrior", "Legacy", "Destiny", "Empire", "Oceans", "Kingdom", "Quest", "Chronicles", "Ghost", "Hunter", "Shadow", "Agent", "Planet"]

        movies_to_create = []
        start_date = date(2000, 1, 1)

        for i in range(1, 5001):
            title = f"{random.choice(adjectives)} {random.choice(nouns)} {i}"
            # Random date between year 2000 and 2026
            release_date = start_date + timedelta(days=random.randint(0, 9500))
            # Rating between 1.0 and 10.0
            rating = round(random.uniform(1.0, 10.0), 1)
            
            movies_to_create.append(Movie(
                title=title,
                release_date=release_date,
                rating=rating
            ))

        self.stdout.write("Bulk inserting movies (5,000 records)...")
        created_movies = Movie.objects.bulk_create(movies_to_create)
        self.stdout.write(f"Successfully inserted {len(created_movies)} movies.")

        # Create intermediate Many-to-Many records in memory
        self.stdout.write("Generating Many-to-Many relationships...")
        movie_genres = []
        movie_languages = []

        for movie in created_movies:
            # Assign 1 to 3 random genres
            num_genres = random.randint(1, 3)
            assigned_genres = random.sample(genres, num_genres)
            for g in assigned_genres:
                movie_genres.append(Movie.genres.through(movie_id=movie.id, genre_id=g.id))

            # Assign 1 to 2 random languages
            num_langs = random.randint(1, 2)
            assigned_langs = random.sample(languages, num_langs)
            for l in assigned_langs:
                movie_languages.append(Movie.languages.through(movie_id=movie.id, language_id=l.id))

        self.stdout.write("Bulk inserting movie-genre relations...")
        Movie.genres.through.objects.bulk_create(movie_genres, batch_size=5000)

        self.stdout.write("Bulk inserting movie-language relations...")
        Movie.languages.through.objects.bulk_create(movie_languages, batch_size=5000)

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))

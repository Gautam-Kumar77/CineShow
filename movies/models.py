from django.db import models

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

    genres = models.ManyToManyField(Genre)
    languages = models.ManyToManyField(Language)

    def __str__(self):
        return self.title

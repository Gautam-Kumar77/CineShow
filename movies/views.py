from django.shortcuts import render
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Count, Q
from .models import Genre, Language, Movie

def movie_list(request):
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
    # Django will load the related genres and languages in 2 quick queries for only the paginated subset of movies.
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
    # Using "Faceted Search" logic:
    # - Genre counts should only reflect selected languages (independent of genre selections)
    # - Language counts should only reflect selected genres (independent of language selections)
    # This prevents option counts from dropping to zero when selected.
    
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

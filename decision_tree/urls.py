from django.urls import path
from . import views

urlpatterns = [
    path('quiz/', views.event_quiz_view, name='event_quiz'),
]

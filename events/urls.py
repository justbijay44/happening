from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),
    path('event/<int:event_id>/going/', views.mark_going, name='mark_going'),
    path('event/<int:event_id>/volunteer/', views.volunteer_for_event, name='volunteer_for_event'),
    path('my-events/', views.my_events, name='my_events'),
    path('event/<int:event_id>/rate/', views.rate_event, name='rate_event'),
]

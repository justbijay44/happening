from django.urls import path
from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('event/approval/', views.event_approval, name='event_approval'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),
    path('event/<int:event_id>/going/', views.mark_going, name='mark_going'),
    path('event/all', views.all_events, name='all_events'),
    path('event/past', views.all_past_events, name='all_past_events'),

    path('event/<int:event_id>/volunteer/', views.volunteer_for_event, name='volunteer_for_event'),
    path('my-events/', views.my_events, name='my_events'),

    path('event/<int:event_id>/rate/', views.rate_event, name='rate_event'),

    path('volunteer-management/', views.volunteer_management, name='volunteer_management'),
    path('manage-volunteers/<int:volunteer_id>/', views.manage_volunteers, name='manage_volunteers'),   
    path('chat/', views.chat_dashboard, name='chat_dashboard'),
    path('todo/<int:event_id>/', views.todo_view, name='todo'),

]
 
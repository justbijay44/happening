from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.db.models import Avg
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required, user_passes_test

from .models import (Event, EventView, EventParticipation, Volunteer,
                     Venue, Rating, GroupChat,GroupChatMember, Message, Task, ApprovalHistory)

from .forms import EventProposalForm, VolunteerForm
from .utils import allocate_venue, suggest_task_assignments
from django.core.mail import send_mail
from django.conf import settings
from datetime import datetime
import json
import calendar
import random
import os
import pandas as pd
import logging

from django.http import HttpResponseRedirect
from decision_tree.models import EventPredictionCount

# Helper function for notification
def send_approval_notification(event):
    if event.status == 'approved':
        subject = f"Event Approved: {event.title}"
        message = (
            f"Your event '{event.title}' has been approved.\n"
            f"Date: {event.date.strftime('%Y-%m-%d %H:%M')}\n"
            f"Expected Attendees: {event.expected_attendees}\n"
            f"View details: http://127.0.0.1:8000/event/{event.id}/"  # Adjust URL as needed
        )
        try:
            send_mail(
                subject,
                message,
                'forgotit044@gmail.com',  # Replace with your email
                [event.proposed_by.email],
                fail_silently=True,
            )
        except Exception:
            pass  # Silent fail for simplicity

def send_rejection_notification(event):
    if event.status == 'rejected':
        subject = f"Event Rejected: {event.title}"
        message = (
            f"Your event proposal '{event.title}' has been rejected.\n"
            f"Reason: {event.rejection_reason or 'No reason provided.'}\n"
            f"Please revise and resubmit if needed."
        )
        try:
            send_mail(
                subject,
                message,
                'forgotit044@gmail.com',  # Replace with your email
                [event.proposed_by.email],
                fail_silently=True,
            )
        except Exception:
            pass  # Silent fail for simplicity

def home(request):
    total_events = Event.objects.filter(status='approved').count()

    # 2. Earliest upcoming event (use end_date)
    next_event = Event.objects.filter(
        status='approved',
        end_date__gte=timezone.now()
    ).order_by('end_date').first()

    # 3. Countdown using end_date
    countdown = None
    if next_event:
        event_dt = next_event.end_date  # Already timezone-aware
        diff = event_dt - timezone.now()

        if diff.total_seconds() > 0:
            days = diff.days
            hrs, rem = divmod(diff.seconds, 3600)
            mins, _ = divmod(rem, 60)

            if days:
                countdown = f"{days}d {hrs}h"
            else:
                countdown = f"{hrs:02d}:{mins:02d}"
        else:
            countdown = "NOW"

    upcoming_events = (
        Event.objects.filter(status='approved', end_date__gte=timezone.now()) |
        Event.objects.filter(status='approved', end_date__isnull=True, date__gte=timezone.now())
    ).order_by('date').distinct()[:3]

    past_events = (
        Event.objects.filter(status='approved', end_date__lt=timezone.now()) |
        Event.objects.filter(status='approved', end_date__isnull=True, date__lt=timezone.now())
    ).order_by('-date').distinct()[:3]

    recommended_events = None

    if request.user.is_authenticated:
        # Try collaborative recommendations
        try:
            with open('collaborative_recommendations.json', 'r') as f:
                collaborative_recs = json.load(f)
            recommended_ids = collaborative_recs.get(str(request.user.id), [])
            if recommended_ids:
                recommended_events = Event.objects.filter(
                    id__in=recommended_ids,
                    status='approved',
                    date__gte=timezone.now()
                ).order_by('date')[:3]
        except (FileNotFoundError, json.JSONDecodeError):
            recommended_events = None

        # Fallback to content-based recommendations
        if not recommended_events or not recommended_events.exists():
            try:
                with open('recommendations.json', 'r') as f:
                    recommendations = json.load(f)
                recommended_ids = recommendations.get(str(request.user.id), [])
                if recommended_ids:
                    recommended_events = Event.objects.filter(
                        id__in=recommended_ids,
                        status='approved',
                        date__gte=timezone.now()
                    ).order_by('date')[:3]
            except (FileNotFoundError, json.JSONDecodeError):
                recommended_events = None

        # Fallback to event_type matching
        if not recommended_events or not recommended_events.exists():
            viewed_events = Event.objects.filter(views__user=request.user)
            if viewed_events.exists():
                event_types = set(viewed_events.values_list('event_type', flat=True))
                recommended_events = Event.objects.filter(
                    event_type__in=event_types,
                    status='approved',
                    date__gte=timezone.now()
                ).exclude(proposed_by=request.user).order_by('date')[:3]

        # Final fallback to highlighted events
        if not recommended_events or not recommended_events.exists():
            recommended_events = Event.objects.filter(
                status='approved',
                date__gte=timezone.now(),
                is_highlight=True
            ).order_by('date')[:3]

    # Form handling
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('account_login')
        
        form = EventProposalForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.proposed_by = request.user
            event.status = 'pending'
            if request.user.is_superuser:
                event.status = 'approved'
            event.save()
            if event.status == 'approved' and allocate_venue(event):
                messages.success(request, f"Venue allocated for {event.title}.")
            else:
                messages.info(request, f"Event {event.title} submitted for approval.") if not request.user.is_superuser else messages.warning(f"No suitable venue available for {event.title}.")
            return redirect('home')
    else:
        form = EventProposalForm()

    prediction_counts = EventPredictionCount.objects.all()
    context = {
        'total_events': total_events,
        'next_event': next_event,
        'countdown': countdown,
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'recommended_events': recommended_events,
        'form': form,
        'prediction_counts': prediction_counts,
    }
    return render(request, 'events/index.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def event_approval(request):
    pending_events = Event.objects.filter(status='pending')

    if request.method == 'POST':
        event_id = request.POST.get('event_id')
        action = request.POST.get('action')
        event = get_object_or_404(Event, id=event_id)

        # Step 1: Check if this is the final submission (with reason)
        if 'final_submit' in request.POST:
            if action == 'approve':
                approval_reason = request.POST.get('approval_reason', '')
                if not approval_reason:
                    messages.error(request, "Please provide a reason for approving the event.")
                    return redirect('event_approval')
                event.status = 'approved'
                ApprovalHistory.objects.create(event=event, action_by=request.user, action='approve', reason=approval_reason)
                messages.success(request, f"Event '{event.title}' approved.")
                send_approval_notification(event)
            elif action == 'reject':
                rejection_reason = request.POST.get('rejection_reason', '')
                if not rejection_reason:
                    messages.error(request, "Please provide a reason for rejecting the event.")
                    return redirect('event_approval')
                event.status = 'rejected'
                event.rejection_reason = rejection_reason
                ApprovalHistory.objects.create(event=event, action_by=request.user, action='reject', reason=rejection_reason)
                messages.success(request, f"Event '{event.title}' rejected.")
                send_rejection_notification(event)
            
            event.save()
            return redirect('event_approval')

    # Step 2: Pass the selected event and action to the template for reason input
    selected_event_id = request.POST.get('event_id') if request.method == 'POST' else None
    selected_action = request.POST.get('action') if request.method == 'POST' and 'final_submit' not in request.POST else None

    context = {
        'pending_events': pending_events,
        'selected_event_id': selected_event_id,
        'selected_action': selected_action,
    }
    return render(request, 'events/event_approval.html', context)

def all_events(request):
    # Base query for upcoming events
    upcoming_events = (
        Event.objects.filter(status='approved', end_date__gte=timezone.now()) |
        Event.objects.filter(status='approved', end_date__isnull=True, date__gte=timezone.now())
    )
    # Get filter parameters from the request
    event_type = request.GET.get('event_type', '')
    venue_id = request.GET.get('venue', '')
    date_range = request.GET.get('date_range', '')

    # Apply filters
    if event_type and event_type != 'Event Type':
        upcoming_events = upcoming_events.filter(event_type=event_type)

    if venue_id and venue_id != '':
        upcoming_events = upcoming_events.filter(venue_id=venue_id)
    
    if date_range:
        today = timezone.now().date()
        if date_range == 'today':
            upcoming_events = upcoming_events.filter(date__date=today)
        elif date_range == 'this_week':
            end_of_week = today + timedelta(days=7 - today.weekday())
            upcoming_events = upcoming_events.filter(date__date__range=[today, end_of_week])
        elif date_range == 'this_month':
            end_of_month = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            upcoming_events = upcoming_events.filter(date__date__range=[today, end_of_month])
    
    # Order by date and execute query
    upcoming_events = upcoming_events.order_by('date').distinct()

    # Get unique event types and venues for the dropdowns
    event_types = Event.objects.values_list('event_type', flat=True).distinct()
    venues = Venue.objects.values_list('id', 'name')

    context = {
        'upcoming_events': upcoming_events,
        'event_types': event_types,
        'venues': venues,
        'selected_event_type': event_type,
        'selected_venue_id': venue_id,
        'selected_date_range': date_range,
    }
    return render(request, 'events/all_events.html', context)

def all_past_events(request):
    past_events = (
        Event.objects.filter(status='approved', end_date__lt=timezone.now()) |
        Event.objects.filter(status='approved', end_date__isnull=True, date__lt=timezone.now())
    )
    # Get filter parameters from the request
    event_type = request.GET.get('event_type', '')
    venue_id = request.GET.get('venue', '')
    date_range = request.GET.get('date_range', '')

    # Apply filters
    if event_type and event_type != 'Event Type':
        past_events = past_events.filter(event_type=event_type)

    if venue_id and venue_id != '':
        past_events = past_events.filter(venue_id=venue_id)

    if date_range:
        today = timezone.now().date()
        if date_range == 'past_week':
            start_of_week = today - timedelta(days=today.weekday() + 7)
            past_events = past_events.filter(date__date__range=[start_of_week, today])
        elif date_range == 'past_month':
            start_of_month = today.replace(day=1) - timedelta(days=1)
            start_of_month = start_of_month.replace(day=1)
            past_events = past_events.filter(date__date__range=[start_of_month, today])

    # Order by date (most recent first) and execute query
    past_events = past_events.order_by('-date').distinct()

    # Get unique event types and venues for the dropdowns
    event_types = Event.objects.values_list('event_type', flat=True).distinct()
    venues = Venue.objects.values_list('id', 'name')

    context = {
        'past_events': past_events,
        'event_types': event_types,
        'venues': venues,
        'selected_event_type': event_type,
        'selected_venue_id': venue_id,
        'selected_date_range': date_range,
    }
    return render(request, 'events/all_past_events.html', context)

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, status='approved')
    going_count = EventParticipation.objects.filter(event=event, status='going').count()
    
    user_is_going = False
    existing_volunteer = None
    user_has_rated = False

    end_date = event.end_date if event.end_date else event.date
    event_has_ended = end_date < timezone.now()

    if request.user.is_authenticated:
        EventView.objects.get_or_create(event=event, user=request.user)

        try:
            participation = EventParticipation.objects.get(event=event, user=request.user)
            user_is_going = participation.status == 'going'
        except EventParticipation.DoesNotExist:
            user_is_going = False
    
        existing_volunteer = Volunteer.objects.filter(event=event, user=request.user).first()

        user_has_rated = Rating.objects.filter(event=event, user=request.user).exists()

    average_rating = Rating.objects.filter(event=event).aggregate(Avg('score'))['score__avg']
    if average_rating is not None:
        average_rating = round(average_rating, 2)

    can_access_group_chat = (
        hasattr(event, 'group_chat') and  # Check if group_chat exists
        (existing_volunteer and existing_volunteer.is_approved or request.user == event.proposed_by)
    )
    context = {
        'event': event,
        'going_count': going_count,
        'user_is_going': user_is_going,
        'existing_volunteer': existing_volunteer,
        'event_has_ended': event_has_ended,
        'average_rating': average_rating,
        'user_has_rated': user_has_rated,
        'chat_url': f'/group-chat/{event_id}/',
        'can_access_group_chat': can_access_group_chat,
    }
    return render(request, 'events/event_detail.html', context)

def mark_going(request, event_id):
    if not request.user.is_authenticated:
        return redirect('account_login')
    
    event = get_object_or_404(Event, id=event_id, status='approved')
    participation, created = EventParticipation.objects.get_or_create(
        event=event,
        user=request.user
    )
    if created or participation.status != 'going':
        participation.status='going'
        participation.save()
        messages.success(request, f"You are now marked as going to {event.title}!")
    else:
        participation.status = 'not_going'
        participation.save()
        messages.success(request, f"You are now marked as not going to {event.title}!")

    return redirect('event_detail', event_id=event_id)

def volunteer_for_event(request, event_id):
    if not request.user.is_authenticated:
        messages.error(request, "You must be logged in to volunteer.")
        return redirect('account_login')

    event = get_object_or_404(Event, id=event_id, status='approved')
    existing_volunteer = Volunteer.objects.filter(event=event, user=request.user).first()

    if request.method == 'POST':
        if existing_volunteer:
            messages.info(request, f"You have already volunteered for {event.title}.")
            return redirect('event_detail', event_id=event_id)
        
        form = VolunteerForm(request.POST)
        if form.is_valid():
            volunteer = Volunteer.objects.create(
                event=event,
                user=request.user,
                hobbies_interests=form.cleaned_data['hobbies_interests'] or '',
                is_approved=False
            )
            if volunteer:
                messages.success(request, f"Your volunteer application for {event.title} has been submitted!")
                return redirect('event_detail', event_id=event_id)
            else:
                messages.error(request, "Failed to submit volunteer application. Please try again.")
                return redirect('volunteer_for_event', event_id=event_id)
    else:
        form = VolunteerForm(instance=existing_volunteer)
        if existing_volunteer:
            form.fields['hobbies_interests'].widget.attrs['readonly'] = 'readonly'
            form.fields['hobbies_interests'].widget.attrs['disabled'] = 'disabled'

    context = {
        'event': event,
        'form': form,
        'existing_volunteer': existing_volunteer,
    }
    return render(request, 'events/volunteer_form.html', context)

def my_events(request):
    if not request.user.is_authenticated:
        return redirect('account_login')
    
    participations = EventParticipation.objects.filter(
        user=request.user,
        status='going',
    ).select_related('event')

    volunteering = Volunteer.objects.filter(
        user=request.user,
    ).select_related('event')

    context = {
        'participations': participations,
        'volunteering': volunteering,
    }
    return render(request, 'events/my_events.html', context)

def rate_event(request, event_id):
    if not request.user.is_authenticated:
        return redirect('account_login')
    
    event = get_object_or_404(Event, id=event_id, status='approved')
    # Check if event has ended
    end_time = event.end_date or event.date
    if end_time >= timezone.now():
        messages.error(request, "You can only rate events that have ended.")
        return redirect('event_detail', event_id=event_id)
    
    if request.method == 'POST':
        score = request.POST.get('score')
        if score and score in ['1', '2', '3', '4', '5']:
            try:
                Rating.objects.update_or_create(
                    event=event,
                    user=request.user,
                    defaults={'score': int(score)}
                )
                messages.success(request, f"Thank you for rating {event.title}!")
            except ValidationError as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Please select a valid rating.")
        return redirect('event_detail', event_id=event_id)
    return redirect('event_detail', event_id=event_id)

def volunteer_management(request):
    if not request.user.is_authenticated:
        messages.error(request, "You must be logged in to access volunteer management.")
        return redirect('account_login')

    # Check if the user is a host of any approved events
    hosted_events = Event.objects.filter(proposed_by=request.user, status='approved')
    if not hosted_events.exists():
        messages.error(request, "You are not a host of any approved events.")
        return redirect('home')

    # Filter out events that have started or are over
    current_time = timezone.now()
    active_events = [event for event in hosted_events if event.date > current_time]

    # Prepare volunteer data as a list of tuples
    event_volunteers = []
    for event in active_events:
        volunteers = Volunteer.objects.filter(event=event).select_related('user')
        event_volunteers.append((event, volunteers))

    context = {
        'hosted_events': active_events,
        'event_volunteers': event_volunteers,
    }

    return render(request, 'events/volunteer_management.html', context)

def manage_volunteers(request, volunteer_id):
    if not request.user.is_authenticated:
        return redirect('account_login')

    volunteer = get_object_or_404(Volunteer, id=volunteer_id)
    event = volunteer.event

    # Ensure the user is the host of the event
    if event.proposed_by != request.user or event.status != 'approved':
        messages.error(request, "You do not have permission to manage volunteers for this event.")
        return redirect('volunteer_management')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            volunteer.is_approved = True
            volunteer.save()
            messages.success(request, f"Volunteer {volunteer.user.username} approved for {event.title}.")
        elif action == 'reject':
            volunteer.delete()
            messages.success(request, f"Volunteer {volunteer.user.username} rejected for {event.title}.")
        return redirect('volunteer_management')

    return redirect('volunteer_management')

def chat_dashboard(request):
    group_chats = GroupChatMember.objects.filter(user=request.user).select_related('group_chat__event')
    selected_chat_id = request.GET.get('chat_id')
    selected_chat = None
    messages_list = []

    if selected_chat_id:
        selected_chat = get_object_or_404(GroupChat, id=selected_chat_id)
        if not selected_chat.memberships.filter(user=request.user).exists():
            messages.error(request, "You are not a member of this group chat.")
            return redirect('chat_dashboard')
        
        if selected_chat.event.status != 'approved':
            messages.error(request, "This event is not approved for chat.")
            return redirect('chat_dashboard')
        messages_list = selected_chat.messages.all().order_by('created_at')

    context = {
        'group_chats': group_chats,
        'selected_chat': selected_chat,
        'messages': messages_list,
        'ws_url': f'ws://127.0.0.1:8000/ws/group-chat/{selected_chat_id}/' if selected_chat_id else None,
    }
    return render(request, 'events/chat_dashboard.html', context)

def todo_view(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if event.status != 'approved':
        messages.error(request, "This event is not approved for tasks.")
        return redirect('home')

    is_participant = Volunteer.objects.filter(event=event, user=request.user, is_approved=True).exists() or event.proposed_by == request.user
    if not is_participant:
        messages.error(request, "You are not a participant in this event.")
        return redirect('home')

    volunteers = Volunteer.objects.filter(event=event, is_approved=True)
    tasks = Task.objects.filter(event=event)

    is_host = (event.proposed_by == request.user)

    if request.method == 'POST' and is_host and 'create_task' in request.POST:
        description = request.POST.get('description')
        Task.objects.create(event=event, description=description)
        messages.success(request, "Task created successfully.")
        return redirect('todo', event_id=event_id)

    # Assign Volunteer (Host Only)
    if request.method == 'POST' and is_host and 'assign_volunteer' in request.POST:
        task_id = request.POST.get('task_id')
        volunteer_id = request.POST.get('volunteer_id')
        task = get_object_or_404(Task, id=task_id, event=event)
        volunteer = get_object_or_404(Volunteer, id=volunteer_id, event=event)
        task.volunteer = volunteer
        task.save()
        messages.success(request, "Volunteer assigned successfully.")
        return redirect('todo', event_id=event_id)

    # Edit Task (Host Only)
    if request.method == 'POST' and is_host and 'edit_task' in request.POST:
        task_id = request.POST.get('task_id')
        description = request.POST.get('description')
        task = get_object_or_404(Task, id=task_id, event=event)
        task.description = description
        task.save()
        messages.success(request, "Task updated successfully.")
        return redirect('todo', event_id=event_id)

    # Delete Task (Host Only)
    if request.method == 'POST' and is_host and 'delete_task' in request.POST:
        task_id = request.POST.get('task_id')
        task = get_object_or_404(Task, id=task_id, event=event)
        task.delete()
        messages.success(request, "Task deleted successfully.")
        return redirect('todo', event_id=event_id)

    # Update Task Status (Volunteer Only)
    if request.method == 'POST' and 'update_status' in request.POST:
        task_id = request.POST.get('task_id')
        task = get_object_or_404(Task, id=task_id, event=event)
        if task.volunteer and task.volunteer.user == request.user:
            task.status = not task.status
            task.save()
            messages.success(request, "Task status updated.")
        else:
            messages.error(request, "You can only update your own tasks.")
        return redirect('todo', event_id=event_id)

    # Task Assignment Suggestions (Host Only)
    task_suggestions = {}
    if is_host:
        task_suggestions = suggest_task_assignments(volunteers, tasks, event)

    context = {
        'event': event,
        'volunteers': volunteers,
        'tasks': tasks,
        'is_host': is_host,
        'is_participant': is_participant,
        'task_suggestions': task_suggestions,
    }
    return render(request, 'events/todo.html', context)



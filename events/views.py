from django.shortcuts import render, redirect, get_object_or_404
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

from .myutils.ml_recommendations import predict_recommendations, save_user_preference
from .myutils.question_tree import question_tree, get_recommendations, get_fallback_recommendations

import json
import calendar
import random
import os
import pandas as pd
import logging

from django.http import HttpResponseRedirect

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

    # Recommendations for event proposal (from quiz or default ML)
    event_recommendations = request.session.get('event_recommendations', None)
    if not event_recommendations:
        # Default ML prediction if no quiz data
        default_input = {
            'Year': 1,  # Default year
            'Department': 'Computer',  # Default department
            'Vibe': 'Creative',  # Default vibe
            'Likes_Competition': 0,  # Default to non-competitive
            'Prefers_Group': 1,  # Default to group-friendly
            'Budget_Pref': 'Budget',  # Default budget
            'Interest_Area': 'Arts'  # Default interest
        }
        event_recommendations = predict_recommendations(default_input)

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

    context = {
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'recommended_events': recommended_events,
        'event_recommendations': event_recommendations,
        'form': form,
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


logger = logging.getLogger(__name__)

def event_quiz(request):
    """Handle the interactive quiz for event recommendations"""
    
    # Reset quiz only on initial GET request to /quiz/
    if request.method == 'GET' and not request.session.get('quiz_answers') and request.path_info == '/quiz/':
        request.session.flush()
        request.session['quiz_answers'] = {}
        request.session['current_question'] = 'year'
        logger.info("Quiz session reset - starting fresh")

    # Get current state
    answers = request.session.get('quiz_answers', {})
    current_question = request.session.get('current_question', 'year')
    
    logger.info(f"Current question: {current_question}, Answers so far: {answers}")

    if request.method == 'POST':
        try:
            # Handle final event selection
            if 'selection' in request.POST:
                selected_event = request.POST.get('selection')
                logger.info(f"User selected event: {selected_event}")
                
                if selected_event and answers:
                    # Get user input for ML model
                    user_input = get_recommendations(answers)
                    
                    # Save user preference to CSV
                    try:
                        save_user_preference(user_input, selected_event)
                        messages.success(request, "Thank you! Your preference has been saved and will help improve our recommendations.")
                    except Exception as e:
                        logger.error(f"Error saving preference: {str(e)}")
                        messages.error(request, "There was an issue saving your preference, but your selection was recorded.")
                    
                    # Clear session
                    if 'quiz_answers' in request.session:
                        del request.session['quiz_answers']
                    if 'current_question' in request.session:
                        del request.session['current_question']
                    if 'event_recommendations' in request.session:
                        del request.session['event_recommendations']
                    
                    return render(request, 'events/thank_you.html', {
                        'selected_event': selected_event
                    })

            # Handle quiz navigation
            current_node = question_tree.get(current_question, {})
            submitted_value = request.POST.get(current_question)
            
            logger.info(f"Processing question: {current_question}, Submitted value: {submitted_value}")
            
            if submitted_value is not None:
                # Validate the submitted value
                options = current_node.get('options', [])
                
                # Convert submitted value to appropriate type
                if options and isinstance(options[0], int):
                    try:
                        submitted_value = int(submitted_value)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert {submitted_value} to int")
                        return redirect('event_quiz')
                
                # Check if value is valid
                if str(submitted_value) in [str(opt) for opt in options]:
                    # Save the answer
                    answers[current_question] = submitted_value
                    request.session['quiz_answers'] = answers
                    
                    logger.info(f"Saved answer: {current_question} = {submitted_value}")
                    
                    # Determine next question
                    next_key = None
                    next_config = current_node.get('next')
                    
                    if isinstance(next_config, dict):
                        # Next question depends on answer
                        next_key = next_config.get(str(submitted_value)) or next_config.get(submitted_value)
                    elif isinstance(next_config, str):
                        # Fixed next question
                        next_key = next_config
                    # If next_config is None, we're at the end
                    
                    logger.info(f"Next key: {next_key}")
                    
                    if next_key:
                        # Move to next question
                        request.session['current_question'] = next_key
                        request.session.modified = True
                        return redirect('event_quiz')
                    else:
                        # End of quiz - generate recommendations
                        logger.info("End of quiz reached, generating recommendations")
                        
                        try:
                            # Get user input for ML model
                            user_input = get_recommendations(answers)
                            logger.info(f"User input for ML: {user_input}")
                            
                            # Get ML recommendations
                            ml_recommendations = predict_recommendations(user_input, num_recommendations=5)
                            logger.info(f"ML recommendations: {ml_recommendations}")
                            
                            # Get fallback recommendations
                            fallback_recommendations = get_fallback_recommendations(
                                user_input.get('Interest_Area', 'Tech'),
                                user_input.get('Vibe', 'Educational'),
                                user_input.get('Likes_Competition', 0)
                            )
                            
                            # Combine and deduplicate
                            all_recommendations = list(dict.fromkeys(ml_recommendations + fallback_recommendations))[:3]
                            logger.info(f"Final recommendations: {all_recommendations}")
                            
                            request.session['event_recommendations'] = all_recommendations
                            
                            return render(request, 'events/quiz_select.html', {
                                'recommendations': all_recommendations,
                                'user_answers': answers
                            })
                            
                        except Exception as e:
                            logger.error(f"Error generating recommendations: {str(e)}")
                            fallback_recs = ['Art Exhibition', 'Tech Workshop', 'Open Mic']
                            return render(request, 'events/quiz_select.html', {
                                'recommendations': fallback_recs,
                                'user_answers': answers
                            })
                else:
                    logger.warning(f"Invalid value {submitted_value} for question {current_question}")
                    messages.error(request, "Please select a valid option.")
            else:
                logger.warning(f"No value submitted for question {current_question}")
                messages.error(request, "Please select an option before proceeding.")
                
        except Exception as e:
            logger.error(f"Error processing quiz POST: {str(e)}")
            messages.error(request, "An error occurred. Please try again.")
        
        return redirect('event_quiz')

    # GET request - show current question
    try:
        current_node = question_tree.get(current_question, {})
        
        if not current_node:
            logger.error(f"No question found for key: {current_question}")
            # Reset quiz
            request.session['current_question'] = 'year'
            request.session['quiz_answers'] = {}
            return redirect('event_quiz')
        
        # Calculate progress
        all_questions = list(question_tree.keys())
        try:
            progress_index = all_questions.index(current_question) + 1
            total_questions = len(all_questions)
            progress = f"Question {progress_index} of {total_questions}"
        except ValueError:
            progress = "Question 1 of 6"
        
        context = {
            'question': current_node,
            'current_question': current_question,
            'progress': progress,
            'answered': answers
        }
        
        return render(request, 'events/quiz.html', context)
        
    except Exception as e:
        logger.error(f"Error displaying quiz: {str(e)}")
        messages.error(request, "An error occurred loading the quiz.")
        return redirect('home')


def quiz_result(request):
    """Show quiz results"""
    recommendations = request.session.get('event_recommendations', [])
    
    if not recommendations:
        # Generate default recommendations
        default_input = {
            'Year': 1,
            'Department': 'Bachelor in Computer Engineering (BCT)',
            'Vibe': 'Educational',
            'Likes_Competition': 0,
            'Prefers_Group': 1,
            'Budget_Pref': 'Budget',
            'Interest_Area': 'Tech'
        }
        
        try:
            recommendations = predict_recommendations(default_input)
        except Exception as e:
            logger.error(f"Error generating default recommendations: {str(e)}")
            recommendations = ['Art Exhibition', 'Tech Workshop', 'Open Mic']
    
    context = {
        'recommendations': recommendations
    }
    
    return render(request, 'events/quiz_result.html', context)
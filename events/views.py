from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.db.models import Avg
from django.core.exceptions import ValidationError
from .models import Event, EventView, EventParticipation, Volunteer, Rating, GroupMessage
from .forms import EventProposalForm, VolunteerForm
from .utils import allocate_venue
import json

def home(request):
    upcoming_events = (
    Event.objects.filter(is_approved=True, end_date__gte=timezone.now()) |
    Event.objects.filter(is_approved=True, end_date__isnull=True, date__gte=timezone.now())
        ).order_by('date').distinct()

    past_events = (
    Event.objects.filter(is_approved=True, end_date__lt=timezone.now()) |
    Event.objects.filter(is_approved=True, end_date__isnull=True, date__lt=timezone.now())
        ).order_by('-date').distinct()

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
                    is_approved=True,
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
                        is_approved=True,
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
                    is_approved=True,
                    date__gte=timezone.now()
                ).exclude(proposed_by=request.user).order_by('date')[:3]

        # Final fallback to highlighted events
        if not recommended_events or not recommended_events.exists():
            recommended_events = Event.objects.filter(
                is_approved=True,
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
            if request.user.is_superuser:
                event.is_approved = True
            event.save()
            if event.is_approved:
                if allocate_venue(event):
                    messages.success(request, f"Venue allocated for {event.title}.")
                else:
                    messages.warning(request, f"No suitable venue available for {event.title}.")
            else:
                messages.info(request, f"Event {event.title} submitted for approval.")
            return redirect('home')
    else:
        form = EventProposalForm()

    context = {
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'recommended_events': recommended_events,
        'form': form,
    }
    return render(request, 'events/index.html', context)

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, is_approved=True)
    going_count = EventParticipation.objects.filter(event=event, status='going').count()
    
    user_is_going = False
    existing_volunteer = None

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

    context = {
        'event': event,
        'going_count': going_count,
        'user_is_going': user_is_going,
        'existing_volunteer': existing_volunteer,
        'event_has_ended': event_has_ended,
        'average_rating': average_rating,
        'user_has_rated': user_has_rated,
    }
    return render(request, 'events/event_detail.html', context)

def mark_going(request, event_id):
    if not request.user.is_authenticated:
        return redirect('account_login')
    
    event = get_object_or_404(Event, id=event_id, is_approved=True)
    participation, created = EventParticipation.objects.get_or_create(
        event=event,
        user=request.user
    )
    if created:
        participation.status='going'
        participation.save()
        messages.success(request, f"You are now marked as going to {event.title}!")
    else:
        #Toggle status
        if participation.status == 'going':
            participation.status = 'not_going'
            participation.save()
            messages.success(request, f"You are now marked as not going to {event.title}!")
        else:
            participation.status = 'going'
            participation.save()
            messages.success(request, f"You are now marked as going to {event.title}!")

        return redirect('event_detail', event_id=event_id)

    if not created and participation.status == 'not_going':
        participation.status = 'going'
        participation.save()
        messages.success(request, f"You are now marked as going to {event.title}!")
    elif participation.status == 'going':
        messages.info(request, f"You are already marked as going to {event.title}.")
    else:
        messages.success(request, f"You are now going to {event.title}!")

    return redirect('event_detail', event_id=event_id)

def volunteer_for_event(request, event_id):
    if not request.user.is_authenticated:
        messages.error(request, "You must be logged in to volunteer.")
        return redirect('account_login')

    event = get_object_or_404(Event, id=event_id, is_approved=True)
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
    
    event = get_object_or_404(Event, id=event_id, is_approved=True)
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
    hosted_events = Event.objects.filter(proposed_by=request.user, is_approved=True)
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
    if event.proposed_by != request.user or not event.is_approved:
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

def group_chat(request, event_id):
    if not request.user.is_authenticated:
        return redirect('account_login')

    event = get_object_or_404(Event, id=event_id, is_approved=True)

    # Check if user is authorized to access chat
    is_participant = EventParticipation.objects.filter(event=event, user=request.user, status='going').exists()
    is_volunteer = Volunteer.objects.filter(event=event, user=request.user, is_approved=True).exists()
    is_host = event.proposed_by == request.user

    if not (is_host or is_participant or is_volunteer):
        messages.error(request, "You do not have permission to access this chat.")
        return redirect('home')
    
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            GroupMessage.objects.create(event=event, user=request.user, content=content)
            messages.success(request, "Message sent successfully!")
        return redirect('group_chat', event_id=event_id)

    messages = GroupMessage.objects.filter(event=event).select_related('user').order_by('created_at')
    return render(request, 'events/group_chat.html', context={'event': event, 'messages': messages})
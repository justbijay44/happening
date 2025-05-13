from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Event, EventView, EventParticipation, Volunteer, Rating
from .forms import EventProposalForm
from .utils import allocate_venue
import json

def home(request):
    upcoming_events = Event.objects.filter(is_approved=True, date__gte=timezone.now()).order_by('date')

    past_events = Event.objects.filter(is_approved=True, end_date__lt=timezone.now()) | Event.objects.filter(is_approved=True,
            end_date__isnull=True, date__lt=timezone.now())

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
    user_volunteer = None

    if request.user.is_authenticated:
        EventView.objects.get_or_create(event=event, user=request.user)

        try:
            participation = EventParticipation.objects.get(event=event, user=request.user)
            user_is_going = participation.status == 'going'
        except EventParticipation.DoesNotExist:
            user_is_going = False
    
        user_volunteer = Volunteer.objects.filter(event=event, user=request.user).first()

    context = {
        'event': event,
        'going_count': going_count,
        'user_is_going': user_is_going,
        'user_volunteer': user_volunteer,
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
        return redirect('account_login')
    
    event = get_object_or_404(Event, id=event_id, is_approved=True)

    if request.method == 'POST':
        role = request.POST.get('role')
        if role:
            volunteer, created = Volunteer.objects.get_or_create(
                event=event,
                user=request.user,
                defaults={'role': role, 'is_approved': False}
            )

            if created:
                volunteer.role = role
                volunteer.save()
                messages.success(request, f"Your volunteer role has been updated for {event.title}!")
            else:
                messages.success(request, f"Thank you for volunteering for {event.title}! Your request is pending approval.")

            return redirect('event_detail', event_id=event_id)
        else:
            messages.error(request, "Please select a role.")
    
    exisiting_volunteer = Volunteer.objects.filter(event=event, user=request.user).first()
    context = {
        'event': event,
        'existing_volunteer': exisiting_volunteer,
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
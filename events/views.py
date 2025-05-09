from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .models import Event, EventView
from .forms import EventProposalForm

def home(request):
    upcoming_events = Event.objects.filter(is_approved=True, date__gte=timezone.now()).order_by('date')
    recommended_events = None

    if request.user.is_authenticated:
        proposed_events = Event.objects.filter(proposed_by=request.user)
        viewed_events = Event.objects.filter(views__user=request.user)

        event_types = set()
        if proposed_events.exists():
            event_types.update(proposed_events.values_list('event_type', flat=True))
        if viewed_events.exists():
            event_types.update(viewed_events.values_list('event_type', flat=True))

        if event_types:
            recommended_events = Event.objects.filter(
                is_approved=True,
                date__gte=timezone.now(),
                event_type__in=event_types
            ).exclude(id__in=proposed_events.values('id')).order_by('date')[:3]
        else:
            recommended_events = Event.objects.filter(
                is_approved=True,
                date__gte=timezone.now(),
                is_highlight=True
            ).order_by('date')[:3]

        if not recommended_events.exists():
            recommended_events = Event.objects.filter(
                is_approved=True,
                date__gte=timezone.now()
            ).order_by('-date')[:3]

    # Form handling
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('account_login')
        
        form = EventProposalForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.proposed_by = request.user
            event.save()
            return redirect('home')
    else:
        form = EventProposalForm()

    context = {
        'upcoming_events': upcoming_events,
        'recommended_events': recommended_events,
        'form': form,
    }
    return render(request, 'events/index.html', context)

def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, is_approved=True)
    if request.user.is_authenticated:
        EventView.objects.get_or_create(event=event, user=request.user)
    return render(request, 'events/event_detail.html', {'event': event})
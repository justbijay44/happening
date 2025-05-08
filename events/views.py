from django.shortcuts import render, redirect
from django.utils import timezone
from .models import Event
from .forms import EventProposalForm

def home(request):
    upcoming_events = Event.objects.filter(date__gte=timezone.now()).order_by('date')

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
        'form': form,
    }
    return render(request, 'events/index.html', context)

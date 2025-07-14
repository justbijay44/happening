# events/management/commands/compute_recommendations.py
from celery import shared_task
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from ...models import Event, EventView, EventParticipation
from scipy.spatial.distance import cosine
import numpy as np
import json

@shared_task
def compute_recommendations():
    events = Event.objects.filter(status='approved', date__gte=timezone.now())
    if not events.exists():
        print("No approved upcoming events found.")
        return

    events_list = list(events)
    event_types = set(events.values_list('event_type', flat=True))
    type_to_idx = {event_type: idx for idx, event_type in enumerate(event_types)}

    event_matrix = np.zeros((len(events_list), len(type_to_idx)))
    for idx, event in enumerate(events_list):
        event_matrix[idx, type_to_idx[event.event_type]] = 1

    users = User.objects.filter(is_active=True)
    user_matrix = np.zeros((users.count(), len(type_to_idx)))

    recommendations = {}

    for user_idx, user in enumerate(users):
        proposed_events = Event.objects.filter(proposed_by=user, status='approved').distinct()
        viewed_events = Event.objects.filter(views__user=user).distinct()
        participated_events = Event.objects.filter(participations__user=user, participations__status='approved').distinct()
        all_events = (proposed_events | viewed_events | participated_events).distinct()

        type_counts = {}
        for event in all_events:
            type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1

        for event_type, count in type_counts.items():
            if event_type in type_to_idx:
                user_matrix[user_idx, type_to_idx[event_type]] = count

        user_vector = user_matrix[user_idx]
        if np.sum(user_vector) == 0:
            recs = events.filter(is_highlight=True).order_by('date')[:3]
        else:
            similarities = [1 - cosine(user_vector, event_vec) for event_vec in event_matrix]
            top_indices = np.argsort(similarities)[::-1]
            excluded_ids = set(all_events.values_list('id', flat=True))
            recommended_events = []
            for i in top_indices:
                if events_list[i].id not in excluded_ids:
                    event_type_match = events_list[i].event_type in type_counts
                    if event_type_match or (len(type_counts) > 1 and similarities[i] > 0.5):
                        recommended_events.append(events_list[i])
                        if len(recommended_events) >= 3:
                            break
            recs = recommended_events[:3] or events.filter(is_highlight=True).order_by('date')[:3]

        recommendations[user.id] = [event.id for event in recs]
        print(f"Recommended for {user.username}: {', '.join([e.title for e in recs])}")

    cache.set('event_recommendations', recommendations, timeout=86400)
    with open('recommendations.json', 'w') as f:
        json.dump(recommendations, f)
    print("Recommendations saved to recommendations.json and cached")

class Command(BaseCommand):
    help = 'Triggers the asynchronous computation of event recommendations'

    def handle(self, *args, **options):
        compute_recommendations.delay()
        self.stdout.write("Recommendation computation triggered asynchronously.")
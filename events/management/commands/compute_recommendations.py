import numpy as np
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from ...models import Event, EventView
from scipy.spatial.distance import cosine
import json

class Command(BaseCommand):
    help = 'Computes event recommendations using cosine similarity'

    def handle(self, *args, **options):
        events = Event.objects.filter(is_approved=True, date__gte=timezone.now())
        if not events.exists():
            self.stdout.write("No approved upcoming events found.")
            return

        events_list = list(events)

        event_types = set(events.values_list('event_type', flat=True))
        type_to_idx = {event_type: idx for idx, event_type in enumerate(event_types)}

        event_matrix = np.zeros((len(events_list), len(type_to_idx)))
        for idx, event in enumerate(events_list):
            event_matrix[idx, type_to_idx[event.event_type]] = 1

        users = User.objects.filter(is_active=True)
        user_matrix = np.zeros((users.count(), len(type_to_idx)))

        for user_idx, user in enumerate(users):
            proposed_events = Event.objects.filter(proposed_by=user)
            viewed_events = Event.objects.filter(views__user=user)
            all_events = proposed_events | viewed_events

            type_counts = {}
            for event in all_events:
                type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1

            for event_type, count in type_counts.items():
                if event_type in type_to_idx:
                    user_matrix[user_idx, type_to_idx[event_type]] = count

        recommendations = {}
        for user_idx, user in enumerate(users):
            user_vector = user_matrix[user_idx]
            if np.sum(user_vector) == 0:
                recs = events.filter(is_highlight=True).order_by('date')[:3]
            else:
                similarities = [1 - cosine(user_vector, event_vec) for event_vec in event_matrix]
                top_indices = np.argsort(similarities)[::-1][:5]
                recommended_events = [
                    events_list[i] for i in top_indices
                    if events_list[i].id not in proposed_events.values_list('id', flat=True)
                ][:3]
                if not recommended_events:
                    recs = events.filter(is_highlight=True).order_by('date')[:3]
                else:
                    recs = recommended_events

            recommendations[user.id] = [event.id for event in recs]
            self.stdout.write(f"Recommended for {user.username}: {', '.join([e.title for e in recs])}")

        with open('recommendations.json', 'w') as f:
            json.dump(recommendations, f)
        self.stdout.write("Recommendations saved to recommendations.json")
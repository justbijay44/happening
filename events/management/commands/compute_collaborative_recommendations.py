import numpy as np
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from ...models import Event, Rating
from scipy.spatial.distance import cosine
import json

class Command(BaseCommand):
    help = 'Computes collaborative event recommendations using cosine similarity'

    def handle(self, *args, **options):
        events = Event.objects.filter(is_approved=True, date__gte=timezone.now())
        if not events.exists():
            self.stdout.write("No approved upcoming events found.")
            return

        events_list = list(events)
        users = User.objects.filter(is_active=True)
        if not users.exists():
            self.stdout.write("No active users found.")
            return

        # Create user-event rating matrix
        user_ids = list(users.values_list('id', flat=True))
        event_ids = list(events.values_list('id', flat=True))
        user_idx = {uid: i for i, uid in enumerate(user_ids)}
        event_idx = {eid: i for i, eid in enumerate(event_ids)}

        rating_matrix = np.zeros((len(user_ids), len(event_ids)))
        ratings = Rating.objects.filter(event__in=events)
        for rating in ratings:
            if rating.user.id in user_idx and rating.event.id in event_idx:
                rating_matrix[user_idx[rating.user.id], event_idx[rating.event.id]] = rating.score

        recommendations = {}
        for user in users:
            user_vector = rating_matrix[user_idx[user.id]]
            if np.sum(user_vector) == 0:
                # Fallback to highlighted events
                recs = events.filter(is_highlight=True).order_by('date')[:3]
            else:
                # Compute similarities with other users
                similarities = []
                for i in range(len(user_ids)):
                    if i != user_idx[user.id]:
                        sim = 1 - cosine(user_vector, rating_matrix[i])
                        similarities.append((i, sim))
                similarities.sort(key=lambda x: x[1], reverse=True)

                # Recommend events rated highly by similar users
                recommended_event_ids = set()
                for other_user_idx, sim in similarities[:5]:  # Top 5 similar users
                    if sim < 0.1:  # Similarity threshold
                        break
                    for e_idx, score in enumerate(rating_matrix[other_user_idx]):
                        if score >= 4 and user_vector[e_idx] == 0:  # Unrated, high score
                            recommended_event_ids.add(event_ids[e_idx])
                            if len(recommended_event_ids) >= 3:
                                break
                    if len(recommended_event_ids) >= 3:
                        break

                recommended_events = [e for e in events_list if e.id in recommended_event_ids][:3]
                if not recommended_events:
                    recs = events.filter(is_highlight=True).order_by('date')[:3]
                else:
                    recs = recommended_events

            recommendations[user.id] = [event.id for event in recs]
            self.stdout.write(f"Recommended for {user.username}: {', '.join([e.title for e in recs])}")

        with open('collaborative_recommendations.json', 'w') as f:
            json.dump(recommendations, f)
        self.stdout.write("Collaborative recommendations saved to collaborative_recommendations.json")
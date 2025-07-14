from django.utils import timezone
from datetime import timedelta
import spacy
import numpy as np
import logging
import random
from textblob import TextBlob
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neural_network import MLPClassifier
from django.core.cache import cache
from chatbot.models import FAQ
from events.models import Event, EventParticipation
import re
import os
import json

nlp = spacy.load('en_core_web_sm')
logging.basicConfig(filename='HAPPENING/chatbot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

with open(os.path.join(os.path.dirname(__file__), '..', 'response.json'), 'r', encoding='utf-8') as file:
    intents = json.load(file)['intents']

def preprocess(text):
    text = text.lower()
    text = re.sub(r'[^a-zA-Z\s]', '', text)
    blob = TextBlob(text)
    text = str(blob.correct())
    doc = nlp(text)
    lemmatized = [token.lemma_ for token in doc if not token.is_stop and not token.is_punct]
    return ' '.join(lemmatized) if lemmatized else text

def initialize_model():
    cache_key = 'chatbot_model'
    model_data = cache.get(cache_key)
    if not model_data:
        if not intents:
            logging.warning("No intents found in response.json. Using fallback responses.")
            return {'vectorizer': None, 'model': None, 'code_to_tag': {}, 'responses': {'fallback': ["I’m not sure, but check /events/ for details!"]}}
        patterns = []
        tags = []

        for intent in intents:
            for pattern in intent['patterns']:
                patterns.append(preprocess(pattern))
                tags.append(intent['tag'])

        responses = {intent['tag']: intent['responses'] for intent in intents}
        
        vectorizer = TfidfVectorizer()
        x = vectorizer.fit_transform(patterns)
        unique_tags = list(set(tags))
        tag_to_code = {tag: i for i, tag in enumerate(unique_tags)}
        code_to_tag = {i: tag for tag, i in tag_to_code.items()}
        y = np.array([tag_to_code[tag] for tag in tags])
        
        model = MLPClassifier(hidden_layer_sizes=(50, 50), max_iter=1000, random_state=42, alpha=0.01)
        model.fit(x, y)
        
        model_data = {'vectorizer': vectorizer, 'model': model, 'code_to_tag': code_to_tag, 'responses': responses}
        cache.set(cache_key, model_data, timeout=86400)
    return model_data

def get_response(user_input, context=None, user=None):
    if context is None:
        context = {}
    if not user_input or len(user_input.strip()) == 0:
        return "How can I assist you with college events today?", context
    if len(user_input) > 200:
        return "That's a bit long! Please keep it shorter.", context

    model_data = initialize_model()
    vectorizer, model, code_to_tag, responses = model_data['vectorizer'], model_data['model'], model_data['code_to_tag'], model_data['responses']
    if not vectorizer or not model:
        return random.choice(responses.get('fallback', ["Something went wrong. Try again!"])), context

    try:
        sentiment = TextBlob(user_input).sentiment.polarity
        preprocessed_input = preprocess(user_input)
        input_vector = vectorizer.transform([preprocessed_input])
        prediction_probs = model.predict_proba(input_vector)[0]
        predicted_code = model.predict(input_vector)[0]
        predicted_tag = code_to_tag.get(predicted_code, None)
        confidence = prediction_probs[predicted_code]

        logging.info(f"Input: {user_input}, Preprocessed: {preprocessed_input}, Predicted Tag: {predicted_tag}, Confidence: {confidence:.2f}")
        logging.info(f"Top predictions: {[(code_to_tag[i], prob) for i, prob in enumerate(prediction_probs)]}")

        if confidence < 0.5:
            if sentiment < -0.3:
                response = "I sense frustration. Could you rephrase your question about college events?"
            else:
                response = "I'm not sure I understand. Try asking differently about events!"
            context["last_intent"] = "fallback"
            return response, context

        if predicted_tag:
            if predicted_tag == "event_list":
                try:
                    start_date = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date + timedelta(days=7)
                    logging.info(f"Checking events from {start_date} to {end_date}")
                    events = Event.objects.filter(date__range=[start_date, end_date])
                    logging.info(f"Found {events.count()} events with date range")
                    events_extended = events.union(Event.objects.filter(end_date__gte=start_date, date__lte=end_date))
                    logging.info(f"Found {events_extended.count()} events with extended range")
                    if events_extended.exists():
                        event_list = "\n".join([
                            f"{e.title} on {e.date.astimezone(timezone.get_current_timezone()).strftime('%b %d, %Y %I:%M %p') if e.date else 'TBA'} "
                            f"to {e.end_date.astimezone(timezone.get_current_timezone()).strftime('%I:%M %p') if e.end_date else 'TBA'} "
                            f"at {e.venue.name if e.venue and e.venue.name else 'TBA'}" for e in events_extended
                        ])
                        response = f"Events this week:\n{event_list}. Check /events/ for more!"
                    else:
                        response = "No events scheduled this week."
                except Exception as e:
                    logging.error(f"Error in event_list: {str(e)}", exc_info=True)
                    response = "Something went wrong. Try again!"
            elif predicted_tag == "event_today":
                today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                events = Event.objects.filter(date__gte=today, date__lt=today + timedelta(days=1))
                if events:
                    event_list = "\n".join([f"{e.title} at {e.date.strftime('%I:%M %p')} at {e.venue.name if e.venue and e.venue.name else 'TBA'}" for e in events])
                    response = f"Today's events ({today.strftime('%b %d, %Y')}):\n{event_list}. Check /events/ for more!"
                else:
                    response = f"No events scheduled for today, {today.strftime('%b %d, %Y')}."
            elif predicted_tag == "event_register":
                response = "Visit /events/register/ to sign up for an event!"
            elif predicted_tag == "event_venue":
                event_name = re.search(r'for\s(.+)', user_input.lower())
                if event_name:
                    try:
                        event = Event.objects.get(title__icontains=event_name.group(1))
                        venue = event.venue
                        response = f"The venue for {event.title} is {venue.name} at {venue.location}. Google Maps: {venue.google_map_link if venue.google_map_link else 'Not available'}"
                    except Event.DoesNotExist:
                        response = "Please specify a valid event title or check /events/ for the list!"
                else:
                    response = "Please specify the event (e.g., 'where is the venue for TechFest')."
            elif predicted_tag == "volunteer_signup":
                response = "Visit /events/volunteer/ to sign up as a volunteer for college events!"
            elif predicted_tag == "participation_status":
                response = "Log in and check your participation status at /events/my-participation/!"
            elif predicted_tag == "event_details":
                event_name = re.search(r'(?:about|details on|what about)\s(.+)', user_input.lower())
                if event_name:
                    event_match = event_name.group(1).strip()

                    if event_match:
                        try:
                            event = Event.objects.get(title__icontains=event_match.strip())
                            details = (
                                f"Title: {event.title}\n"
                                f"Date: {event.date.astimezone(timezone.get_current_timezone()).strftime('%b %d, %Y %I:%M %p') if event.date else 'TBA'} "
                                f"to {event.end_date.astimezone(timezone.get_current_timezone()).strftime('%I:%M %p') if event.end_date else 'TBA'}\n"
                                f"Venue: {event.venue.name if event.venue and event.venue.name else 'TBA'} at {event.venue.location if event.venue else 'N/A'}\n"
                                f"Description: {event.description or 'No description available'}\n"
                                f"Expected Attendees: {event.expected_attendees}\n"
                                f"Register at: /events/register/{event.id}/" if event.status == 'approved' else 'Registration not yet open'
                            )
                            response = responses[predicted_tag][0].format(event=event.title, details=details)
                        except Event.DoesNotExist:
                            response = f"No details found for '{event_match}'. Check /events/ for a list!"
                    else:
                        response = "Please specify an event (e.g., 'tell me about Jersey Design Compi')."
                else:
                    response = "Please specify an event (e.g., 'tell me about Jersey Design Compi')."
            elif predicted_tag == "event_recommendations":
                if user and user.is_authenticated:
                    recommendations = cache.get('event_recommendations')
                    if recommendations and user.id in recommendations:
                        event_ids = recommendations[user.id]
                        recommended_events = Event.objects.filter(id__in=event_ids)
                        if recommended_events.exists():
                            rec_list = "\n".join([f"- {e.title} on {e.date.astimezone(timezone.get_current_timezone()).strftime('%b %d, %Y')}" for e in recommended_events])
                            response = responses[predicted_tag][0].format(recommendations=rec_list)
                        else:
                            response = "No recommendations available. Check /events/ for all events!"
                    else:
                        response = "No recommendations computed yet. Try again later or check /events/!"
                else:
                    response = "Please log in to get personalized recommendations. Check /events/ for all events!"
            else:
                response = random.choice(responses[predicted_tag])

            if sentiment < -0.3:
                response += " Let me know more if I can help further!"
            elif sentiment > 0.3:
                response += " Glad you’re excited! Anything else?"
            context["last_intent"] = predicted_tag
        else:
            response = "I don’t understand. Try asking about events, venues, or registration!"
            context["last_intent"] = "fallback"

        return response, context
    except Exception as e:
        logging.error(f"Error in get_response: {str(e)}", exc_info=True)
        return "Something went wrong. Try again!", context
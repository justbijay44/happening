import spacy
import tensorflow as tf
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
import os
import json
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from sklearn.feature_extraction.text import TfidfVectorizer
from django.utils import timezone
from datetime import timedelta
from events.models import Event, Venue
import numpy as np
import re
from difflib import SequenceMatcher

# Initialize NLP components
try:
    nlp = spacy.load('en_core_web_sm')
except:
    nlp = None

try:
    nltk.download('stopwords', quiet=True)
    nltk.download('punkt', quiet=True)
    stop_words = set(stopwords.words('english'))
except:
    stop_words = set()

# File paths
base_dir = os.path.dirname(os.path.abspath(__file__))
response_path = os.path.join(base_dir, 'response.json')

# Load intents data
try:
    with open(response_path, 'r') as file:
        intents_data = json.load(file)['intents']
except:
    intents_data = []

# Create tag mappings
unique_tags = list(set(intent['tag'] for intent in intents_data))
tag_to_idx = {tag: idx for idx, tag in enumerate(unique_tags)}
idx_to_tag = {idx: tag for tag, idx in tag_to_idx.items()}

def load_model_and_tokenizer():
    """Load the trained model and tokenizer"""
    model_path = os.path.join(base_dir, 'chatbot_model.h5')
    tokenizer_path = os.path.join(base_dir, 'chatbot_tokenizer.json')
    
    if not (os.path.exists(model_path) and os.path.exists(tokenizer_path)):
        return None, None, None
    
    try:
        model = tf.keras.models.load_model(model_path)
        with open(tokenizer_path, 'r') as f:
            tokenizer_json = json.load(f)
        tokenizer = tf.keras.preprocessing.text.tokenizer_from_json(tokenizer_json)
        return model, tokenizer, 25  # Updated to match training
    except:
        return None, None, None

def preprocess_text(text):
    """Simple text preprocessing"""
    if not text:
        return ""
    
    # Convert to lowercase and clean
    text = text.lower().strip()
    
    # Remove extra whitespace and special characters
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    # Simple tokenization if spacy fails
    if nlp:
        try:
            doc = nlp(text)
            tokens = [token.lemma_ for token in doc 
                     if not token.is_stop and not token.is_punct and token.text.strip()]
            return " ".join(tokens)
        except:
            pass
    
    # Fallback to simple processing
    words = text.split()
    return " ".join([word for word in words if word not in stop_words and len(word) > 2])

def extract_event_name(user_input):
    """Extract potential event name from user input"""
    # Common question words to remove
    question_words = ['what', 'when', 'where', 'how', 'who', 'details', 'about', 
                     'tell', 'me', 'info', 'information', 'venue', 'location', 'for', 'of', 'the', 'a', 'an']
    
    # Clean the input
    cleaned = user_input.lower().strip()
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    words = cleaned.split()
    
    # Remove question words and short words
    potential_names = [word for word in words if word not in question_words and len(word) > 2]
    
    return " ".join(potential_names) if potential_names else None

def simple_pattern_matching(user_input):
    """Simple but effective pattern matching"""
    user_lower = user_input.lower().strip()
    
    # Define clear keywords for each intent
    intent_keywords = {
        'event_today': ['today', 'now', 'current', 'right now'],
        'event_this_week': ['week', 'this week', 'weekly', '7 days'],
        'event_upcoming_week': ['next week', 'upcoming', 'future', 'coming', 'next'],
        'event_details': ['details', 'about', 'info', 'information', 'describe', 'tell me about', 'more about'],
        'event_venue': ['venue', 'where', 'location', 'place', 'address'],
        'fallback': ['hello', 'hi', 'hey', 'help', 'what can you do']
    }
    
    # Score each intent
    best_intent = 'fallback'
    best_score = 0
    
    for intent, keywords in intent_keywords.items():
        score = 0
        for keyword in keywords:
            if keyword in user_lower:
                score += len(keyword)  # Longer matches get higher scores
        
        if score > best_score:
            best_score = score
            best_intent = intent
    
    return best_intent if best_score > 0 else 'fallback'

def predict_intent(user_input, model, tokenizer, max_length):
    """Predict intent using the trained model"""
    preprocessed_input = preprocess_text(user_input)
    if not preprocessed_input:
        return None, 0.0
    
    try:
        sequence = tokenizer.texts_to_sequences([preprocessed_input])
        if not sequence or not sequence[0]:
            return None, 0.0
            
        padded_sequence = pad_sequences(sequence, maxlen=max_length, padding='post')
        prediction_probs = model.predict(padded_sequence, verbose=0)[0]
        predicted_idx = np.argmax(prediction_probs)
        confidence = prediction_probs[predicted_idx]
        
        return idx_to_tag.get(predicted_idx, None), confidence
    except:
        return None, 0.0

def get_dynamic_response(user_input, html_output=False):
    """Main function to get chatbot response with optional HTML formatting"""
    if not user_input or not user_input.strip():
        return "Please ask me something about events!"
    
    # Clean input
    user_input = user_input.strip()
    
    # Try multiple methods to determine intent
    intent = None
    confidence = 0.0
    
    # Method 1: Try model prediction
    model, tokenizer, max_length = load_model_and_tokenizer()
    if model and tokenizer:
        intent, confidence = predict_intent(user_input, model, tokenizer, max_length)
    
    # Method 2: If model confidence is low, use simple pattern matching
    if not intent or confidence < 0.6:
        intent = simple_pattern_matching(user_input)
        confidence = 0.8  # Set high confidence for our pattern matching
    
    # Get current time for date filtering
    now = timezone.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        # Handle different intents
        if intent == "event_today":
            events = Event.objects.filter(
                status='approved', 
                date__date=today.date()
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    if html_output:
                        map_link = f" (Map: <a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if event.venue and event.venue.google_map_link else ""
                    else:
                        map_link = f" (Map: {event.venue.google_map_link[:30]}...)" if event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%I:%M %p')}{venue_info}{map_link}")
                return f"Here are today's events:\n\n" + "\n".join(event_list)
            else:
                return "No events scheduled for today. Check back later for updates!"

        elif intent == "event_this_week":
            end_of_week = today + timedelta(days=7)
            events = Event.objects.filter(
                status='approved',
                date__range=[today, end_of_week]
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    if html_output:
                        map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Venue Link</a>)" if event.venue and event.venue.google_map_link else ""
                    else:
                        map_link = f" (Map: {event.venue.google_map_link[:30]}...)" if event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                return f"Events this week:\n\n" + "\n".join(event_list)
            else:
                return "No events scheduled for this week. Stay tuned for upcoming events!"

        elif intent == "event_upcoming_week":
            next_week_start = today + timedelta(days=7)
            next_week_end = today + timedelta(days=14)
            events = Event.objects.filter(
                status='approved',
                date__range=[next_week_start, next_week_end]
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    if html_output:
                        map_link = f" (Map: <a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if event.venue and event.venue.google_map_link else ""
                    else:
                        map_link = f" (Map: {event.venue.google_map_link[:30]}...)" if event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                return f"Events next week:\n\n" + "\n".join(event_list)
            else:
                return "No events scheduled for next week yet. Check back soon!"

        elif intent == "event_details":
            event_name = extract_event_name(user_input)
            if not event_name:
                return "Please specify which event you'd like details about. For example: 'details about Event 7/25' or 'tell me about Test Event'."
            
            events = Event.objects.filter(
                status='approved',
                date__gte=now
            ).select_related('venue').order_by('date')
            
            matching_event = None
            for event in events:
                if event_name.lower() in event.title.lower() or any(word.lower() in event.title.lower() for word in event_name.split() if len(word) > 2):
                    matching_event = event
                    break
            
            if matching_event:
                venue_info = f"Venue: {matching_event.venue.name}" if matching_event.venue else "Venue: TBA"
                if html_output:
                    map_info = f"\nMap: <a href='{matching_event.venue.google_map_link}' target='_blank'>Map</a>" if matching_event.venue and event.venue.google_map_link else ""
                else:
                    map_info = f"\nMap: {matching_event.venue.google_map_link[:30]}..." if matching_event.venue and matching_event.venue.google_map_link else ""
                description = matching_event.description if matching_event.description else "No description available."
                
                return f"📅 **{matching_event.title}**\n\n" \
                       f"📆 Date: {matching_event.date.strftime('%A, %B %d, %Y at %I:%M %p')}\n" \
                       f"📍 {venue_info}{map_info}\n" \
                       f"📝 Description: {description}"
            else:
                if events.exists():
                    event_names = [e.title for e in events[:3]]
                    return f"Sorry, I couldn't find details for '{event_name}'. Available events include: {', '.join(event_names)}. Try asking about one of these!"
                else:
                    return "No upcoming events found."

        elif intent == "event_venue":
            event_name = extract_event_name(user_input)
            if not event_name:
                return "Please specify which event's venue you'd like to know about. For example: 'venue of Event 7/25' or 'where is Test Event'."
            
            events = Event.objects.filter(
                status='approved',
                date__gte=now
            ).select_related('venue').order_by('date')
            
            matching_event = None
            for event in events:
                if event_name.lower() in event.title.lower() or any(word.lower() in event.title.lower() for word in event_name.split() if len(word) > 2):
                    matching_event = event
                    break
            
            if matching_event:
                if matching_event.venue:
                    if html_output:
                        map_info = f"\nMap: <a href='{matching_event.venue.google_map_link}' target='_blank'>Map</a>" if matching_event.venue.google_map_link else ""
                    else:
                        map_info = f"\nMap: {matching_event.venue.google_map_link[:30]}..." if matching_event.venue.google_map_link else ""
                    return f"📍 **{matching_event.title}** will be held at:\n\n" \
                           f"🏢 {matching_event.venue.name}{map_info}"
                else:
                    return f"The venue for **{matching_event.title}** hasn't been announced yet. Please check back later!"
            else:
                if events.exists():
                    event_names = [e.title for e in events[:3]]
                    return f"Sorry, I couldn't find venue info for '{event_name}'. Available events include: {', '.join(event_names)}. Try asking about one of these!"
                else:
                    return "No upcoming events found."

        else:  # fallback
            return "Hello! Ready to explore events?"

    except Exception as e:
        print(f"Error in get_dynamic_response: {e}")
        return "Sorry, I encountered an error while processing your request. Please try again!"
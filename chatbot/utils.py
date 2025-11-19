import spacy
import tensorflow as tf
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
import os
import json
import nltk
from nltk.corpus import stopwords
from django.utils import timezone
from datetime import timedelta
from events.models import Event, Venue
import numpy as np
import re
import random

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

base_dir = os.path.dirname(os.path.abspath(__file__))
response_path = os.path.join(base_dir, 'response.json')

try:
    with open(response_path, 'r') as file:
        intents_data = json.load(file)['intents']
except:
    intents_data = []

unique_tags = list(set(intent['tag'] for intent in intents_data))
tag_to_idx = {tag: idx for idx, tag in enumerate(unique_tags)}
idx_to_tag = {idx: tag for tag, idx in tag_to_idx.items()}

# Conversation context
conversation_context = {}

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
        return model, tokenizer, 15
    except:
        return None, None, None

def preprocess_text(text):
    """Simple text preprocessing"""
    if not text:
        return ""
    
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    if nlp:
        try:
            doc = nlp(text)
            tokens = [token.lemma_ for token in doc 
                     if not token.is_punct and token.text.strip()]
            return " ".join(tokens)
        except:
            pass
    
    words = text.split()
    return " ".join([word for word in words if len(word) > 1])

def extract_date_info(user_input):

    user_lower = user_input.lower()
    now = timezone.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Tomorrow
    if 'tomorrow' in user_lower or 'tmrw' in user_lower:
        return 'event_tomorrow', today + timedelta(days=1)
    
    days = {
        'monday': 0, 'mon': 0,
        'tuesday': 1, 'tue': 1,
        'wednesday': 2, 'wed': 2,
        'thursday': 3, 'thu': 3,
        'friday': 4, 'fri': 4,
        'saturday': 5, 'sat': 5,
        'sunday': 6, 'sun': 6,
    }
    
    for day_name, day_num in days.items():
        if day_name in user_lower:
            current_day = today.weekday()
            
            if 'next' in user_lower:
                days_ahead = (7 - current_day) + day_num
            # Otherwise find the next occurrence
            elif day_num >= current_day:
                days_ahead = day_num - current_day
            else:
                days_ahead = (7 - current_day) + day_num
            
            target_date = today + timedelta(days=days_ahead)
            return 'event_specific_day', target_date
    
    # Match: "16 nov", "nov 16", "16th november"
    months = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    
    for month_name, month_num in months.items():
        if month_name in user_lower:
            # Try to find a number near the month name
            numbers = re.findall(r'\d+', user_lower)
            if numbers:
                try:
                    day = int(numbers[0])
                    if 1 <= day <= 31:
                        year = now.year
                        try:
                            target_date = today.replace(year=year, month=month_num, day=day)
                      
                            if target_date < today:
                         
                                if (today - target_date).days < 7:
                                    return 'event_past', target_date
                          
                                target_date = target_date.replace(year=year + 1)
                            return 'event_specific_date', target_date
                        except ValueError:
                            pass  
                except ValueError:
                    pass
    
    if 'weekend' in user_lower:
        current_day = today.weekday()
        days_to_sat = (5 - current_day) if current_day < 5 else 0
        saturday = today + timedelta(days=days_to_sat)
        return 'event_weekend', saturday
    
    return None, None

def extract_event_name(user_input, context=None):
    """Extract event name with context awareness - IMPROVED"""
    user_lower = user_input.lower().strip()
    
    if context and context.get('last_event'):
        references = ['this event', 'that event', 'this one', 'that one', 'it', 'the event', 'this', 'that']
        if any(ref in user_lower for ref in references):
            # Make sure it's not part of a larger phrase
            if not any(phrase in user_lower for phrase in ['this week', 'that week', 'this time']):
                return context['last_event']
    
    skip_words = ['what', 'when', 'where', 'how', 'who', 'details', 'about', 
                  'tell', 'me', 'info', 'venue', 'location', 'for', 'of', 
                  'the', 'a', 'an', 'give', 'can', 'you', 'is', 'there', 'any',
                  'date', 'time', 'happening', 'event', 'this', 'that']
    
    words = user_input.lower().replace('?', '').split()
    event_words = [w for w in words if w not in skip_words and len(w) > 2]
    
    return " ".join(event_words) if event_words else None

def simple_pattern_matching(user_input, context=None):
    """IMPROVED pattern matching with better intent detection"""
    user_lower = user_input.lower().strip()
    
    # Check dates first
    date_intent, date_obj = extract_date_info(user_input)
    if date_intent:
        return date_intent
    
    if context and context.get('last_event'):
        date_time_keywords = ['when', 'date', 'time', 'what time', 'what date', 'when is']
        if any(keyword in user_lower for keyword in date_time_keywords):
            if any(ref in user_lower for ref in ['this', 'that', 'it', 'the event']):
                return 'event_details'
        
        if any(word in user_lower for word in ['detail', 'info', 'about', 'tell', 'describe']):
            if any(ref in user_lower for ref in ['this', 'that', 'it']):
                return 'event_details'
        
        if any(word in user_lower for word in ['where', 'venue', 'location', 'place']):
            if any(ref in user_lower for ref in ['this', 'that', 'it']):
                return 'event_venue'
    
    greeting_words = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']
    if any(user_lower == w or user_lower.startswith(w + ' ') for w in greeting_words):
        if len(user_lower.split()) <= 3:
            return 'greeting'
    
    # Goodbye
    if any(w in user_lower for w in ['bye', 'goodbye', 'thanks', 'thank you', "that's all", 'thats all']):
        return 'goodbye'
    
    if 'today' in user_lower:
        return 'event_today'
    
    all_events_patterns = [
        'all events', 'list all', 'show all', 'list events',
        'all upcoming', 'show me all', 'list upcoming', 'every event',
        'complete list', 'full list', 'all available', 'available events'
    ]
    if any(pattern in user_lower for pattern in all_events_patterns):
        return 'event_all'
    
    this_week_patterns = [
        'this week', 'events this week', 'what about this week',
        'week events', 'events for this week', 'show this week',
        'this weeks', 'whats this week', 'what happening this week',
        'any events this week', 'are there events this week'
    ]
    if any(pattern in user_lower for pattern in this_week_patterns):
        return 'event_this_week'
    
    next_week_patterns = [
        'next week', 'events next week', 'next weeks',
        'coming week', 'following week', 'events for next week',
        'show next week', 'whats next week', 'what about next week'
    ]
    if any(pattern in user_lower for pattern in next_week_patterns):
        return 'event_upcoming_week'
    
    if 'upcoming' in user_lower:

        list_words = ['list', 'all', 'show', 'complete', 'full']
        if any(word in user_lower for word in list_words):
            return 'event_all'
        else:
            return 'event_upcoming_week'
    
    detail_keywords = ['detail', 'info', 'about', 'describe', 'tell me about', 
                      'information', 'more about', 'what is', 'when is', 'date of', 
                      'time of', 'what time', 'what date']
    if any(keyword in user_lower for keyword in detail_keywords):
       
        if not any(w in user_lower for w in ['today', 'tomorrow', 'this week', 'next week']):
            return 'event_details'
    
    # Event venue
    venue_keywords = ['where', 'venue', 'location', 'place', 'address']
    if any(keyword in user_lower for keyword in venue_keywords):
      
        if not any(w in user_lower for w in ['today', 'tomorrow', 'this week', 'next week']):
            return 'event_venue'
    
    return 'fallback'

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
        predicted_tag = idx_to_tag.get(predicted_idx, None)
        return predicted_tag, confidence
    except Exception as e:
        print(f"Error in predict_intent: {e}")
        return None, 0.0

def get_events_for_date(target_date, html_output=False):
    """Helper to get and format events for a specific date"""
    events = Event.objects.filter(
        status='approved',
        date__date=target_date.date()
    ).select_related('venue').order_by('date')
    
    if not events.exists():
        return None
    
    event_list = []
    for event in events:
        venue_info = f" at {event.venue.name}" if event.venue else ""
        if html_output and event.venue and event.venue.google_map_link:
            map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Map</a>)"
        else:
            map_link = ""
        event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
    
    return event_list, [e.title for e in events]

def get_dynamic_response(user_input, html_output=False, session_id='default'):
    """Main response function - FIXED with better intent detection"""
    if not user_input or not user_input.strip():
        return "Please ask me something about events!"
    
    user_input = user_input.strip()
    
    if session_id not in conversation_context:
        conversation_context[session_id] = {'last_event': None, 'last_events_shown': []}
    
    context = conversation_context[session_id]
    
    # Get intent 
    intent = None
    confidence = 0.0
    
    # Check date extraction first
    date_intent, date_obj = extract_date_info(user_input)
    if date_intent:
        intent = date_intent
        confidence = 0.95
    else:
        # Try pattern matching (primary method)
        pattern_intent = simple_pattern_matching(user_input, context)
        if pattern_intent != 'fallback':
            intent = pattern_intent
            confidence = 0.90
        else:
            model, tokenizer, max_length = load_model_and_tokenizer()
            if model and tokenizer:
                model_intent, model_conf = predict_intent(user_input, model, tokenizer, max_length)
                if model_conf > 0.4:  
                    intent = model_intent
                    confidence = model_conf
                else:
                    intent = 'fallback'
                    confidence = 0.5
            else:
                intent = 'fallback'
                confidence = 0.5
    
    print(f"Intent: {intent}, Confidence: {confidence}, Input: '{user_input}'")
    
    now = timezone.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        # Greetings
        if intent == "greeting":
            for intent_data in intents_data:
                if intent_data['tag'] == 'greeting':
                    return random.choice(intent_data['responses'])
        
        # Goodbye
        elif intent == "goodbye":
            context['last_event'] = None
            context['last_events_shown'] = []
            for intent_data in intents_data:
                if intent_data['tag'] == 'goodbye':
                    return random.choice(intent_data['responses'])
        
        # Today
        elif intent == "event_today":
            result = get_events_for_date(today, html_output)
            if result:
                event_list, titles = result
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return "Here are today's events:\n\n" + "\n".join(event_list)
            return "No events scheduled for today."
        
        # Tomorrow
        elif intent == "event_tomorrow":
            tomorrow = today + timedelta(days=1)
            result = get_events_for_date(tomorrow, html_output)
            if result:
                event_list, titles = result
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return f"Events tomorrow ({tomorrow.strftime('%b %d')}):\n\n" + "\n".join(event_list)
            return f"No events tomorrow ({tomorrow.strftime('%b %d')})."
        
        # Specific date (like "16 nov")
        elif intent == "event_specific_date" and date_obj:
            result = get_events_for_date(date_obj, html_output)
            if result:
                event_list, titles = result
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return f"Events on {date_obj.strftime('%A, %b %d')}:\n\n" + "\n".join(event_list)
            return f"No events on {date_obj.strftime('%b %d')}."
        
        # Specific day (like "monday")
        elif intent == "event_specific_day" and date_obj:
            result = get_events_for_date(date_obj, html_output)
            if result:
                event_list, titles = result
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                day_name = date_obj.strftime('%A')
                return f"Events on {day_name} ({date_obj.strftime('%b %d')}):\n\n" + "\n".join(event_list)
            return f"No events on {date_obj.strftime('%A, %b %d')}."
        
        # Past date
        elif intent == "event_past" and date_obj:
            return f"That date ({date_obj.strftime('%b %d')}) has passed. Try asking about upcoming events!"
        
        # Weekend
        elif intent == "event_weekend" and date_obj:
            saturday = date_obj
            sunday = saturday + timedelta(days=1)
            events = Event.objects.filter(
                status='approved',
                date__date__gte=saturday.date(),
                date__date__lte=sunday.date()
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                titles = []
                for event in events:
                    titles.append(event.title)
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if html_output and event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return f"Weekend events:\n\n" + "\n".join(event_list)
            return "No events this weekend."
        
        # THIS WEEK
        elif intent == "event_this_week":
            end_of_week = today + timedelta(days=6)
            events = Event.objects.filter(
                status='approved',
                date__gte=today,
                date__lte=end_of_week
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                titles = [e.title for e in events]
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if html_output and event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return "Events this week:\n\n" + "\n".join(event_list)
            return "No events this week."
        
        # NEXT WEEK
        elif intent == "event_upcoming_week":
            next_week_start = today + timedelta(days=7)
            next_week_end = today + timedelta(days=13)
            events = Event.objects.filter(
                status='approved',
                date__gte=next_week_start,
                date__lte=next_week_end
            ).select_related('venue').order_by('date')
            
            if events.exists():
                event_list = []
                titles = [e.title for e in events]
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if html_output and event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return f"Events next week ({next_week_start.strftime('%b %d')} - {next_week_end.strftime('%b %d')}):\n\n" + "\n".join(event_list)
            return "No events next week."
        
        # ALL EVENTS
        elif intent == "event_all":
            events = Event.objects.filter(
                status='approved',
                date__gte=now
            ).select_related('venue').order_by('date')[:30]
            
            if events.exists():
                event_list = []
                titles = [e.title for e in events]
                for event in events:
                    venue_info = f" at {event.venue.name}" if event.venue else ""
                    map_link = f" (<a href='{event.venue.google_map_link}' target='_blank'>Map</a>)" if html_output and event.venue and event.venue.google_map_link else ""
                    event_list.append(f"• {event.title} - {event.date.strftime('%b %d, %I:%M %p')}{venue_info}{map_link}")
                
                context['last_event'] = titles[0] if titles else None
                context['last_events_shown'] = titles
                return f"All upcoming events ({len(events)} total):\n\n" + "\n".join(event_list)
            return "No upcoming events."
        
        # Event details
        elif intent == "event_details":
            event_name = extract_event_name(user_input, context)
            if not event_name:
                if context['last_events_shown']:
                    return f"Which event? Recent events: {', '.join(context['last_events_shown'][:3])}"
                return "Please specify which event. Try: 'details about [event name]'"
            
            events = Event.objects.filter(
                status='approved',
                date__gte=now
            ).select_related('venue').order_by('date')
            
            # Find matching event
            matching_event = None
            for event in events:
                if event_name.lower() in event.title.lower() or any(word in event.title.lower() for word in event_name.split() if len(word) > 3):
                    matching_event = event
                    break
            
            if matching_event:
                context['last_event'] = matching_event.title
                venue = f"Venue: {matching_event.venue.name}" if matching_event.venue else "Venue: TBA"
                map_link = f"\n<a href='{matching_event.venue.google_map_link}' target='_blank'>View Map</a>" if html_output and matching_event.venue and matching_event.venue.google_map_link else ""
                desc = matching_event.description if matching_event.description else "No description."
                
                return f"📅 {matching_event.title}\n\n" \
                       f"📆 {matching_event.date.strftime('%A, %b %d, %Y at %I:%M %p')}\n" \
                       f"📍 {venue}{map_link}\n" \
                       f"📝 {desc}"
            return f"Couldn't find '{event_name}'. Try asking 'events this week' to see what's available."
        
        # Event venue
        elif intent == "event_venue":
            event_name = extract_event_name(user_input, context)
            if not event_name:
                if context['last_events_shown']:
                    return f"Which event's venue? Recent: {', '.join(context['last_events_shown'][:3])}"
                return "Please specify which event. Try: 'where is [event name]?'"
            
            events = Event.objects.filter(
                status='approved',
                date__gte=now
            ).select_related('venue').order_by('date')
            
            matching_event = None
            for event in events:
                if event_name.lower() in event.title.lower() or any(word in event.title.lower() for word in event_name.split() if len(word) > 3):
                    matching_event = event
                    break
            
            if matching_event:
                context['last_event'] = matching_event.title
                if matching_event.venue:
                    map_link = f"\n<a href='{matching_event.venue.google_map_link}' target='_blank'>View Map</a>" if html_output and matching_event.venue.google_map_link else ""
                    return f"📍 {matching_event.title} is at:\n🏢 {matching_event.venue.name}{map_link}"
                return f"Venue for {matching_event.title} hasn't been announced yet."
            return f"Couldn't find '{event_name}'."
        
        # Fallback
        else:
            for intent_data in intents_data:
                if intent_data['tag'] == 'fallback':
                    return random.choice(intent_data['responses'])
    
    except Exception as e:
        print(f"Error: {e}")
        return "Sorry, something went wrong. Please try again!"
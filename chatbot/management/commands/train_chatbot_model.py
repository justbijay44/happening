from django.core.management.base import BaseCommand
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Embedding, LSTM, Dense, Dropout
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras.utils import to_categorical
import os
import json
import spacy
import numpy as np
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    nlp = spacy.load('en_core_web_sm')
except:
    nlp = None

class Command(BaseCommand):
    help = 'Trains and saves a simple but effective chatbot model'

    def preprocess_text(self, text):
        """Simple text preprocessing"""
        if not text:
            return ""
        
        text = text.lower().strip()
        
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        
        words = text.split()
        words = [word for word in words if len(word) > 1]
        
        return " ".join(words)

    def augment_patterns(self, patterns, tags):
        augmented_patterns = []
        augmented_tags = []
        
        for pattern, tag in zip(patterns, tags):
            processed = self.preprocess_text(pattern)
            if processed:
                augmented_patterns.append(processed)
                augmented_tags.append(tag)
        
        simple_variations = {
            'event_today': [
                'events happening today', 'what today', 'today event',
                'events today please', 'show today events', 'any event today',
                'todays events', 'events for today'
            ],
            'event_this_week': [
                'this week event', 'events this week please', 'week events',
                'show this week events', 'events for this week',
                'this weeks events', 'weekly events'
            ],
            'event_upcoming_week': [
                'next week event', 'upcoming event', 'events next week',
                'show next week events', 'events for next week',
                'next weeks events', 'coming events'
            ],
            'event_all': [
                'show me everything', 'display all events', 'full schedule',
                'complete event schedule', 'all event list', 'entire event list'
            ],
            'event_details': [
                'event info', 'more info', 'event information', 'about event',
                'tell about event', 'describe event', 'event description',
                'details about', 'info about', 'tell me about'
            ],
            'event_venue': [
                'event location', 'where event', 'location of event',
                'place of event', 'event place', 'find location',
                'venue of', 'where is', 'location'
            ],
            'fallback': [
                'hello there', 'hi bot', 'hey there', 'good day',
                'help me', 'what you do', 'assist', 'support',
                'hello', 'hi', 'hey'
            ]
        }
        
        for tag, extra_patterns in simple_variations.items():
            for pattern in extra_patterns:
                processed = self.preprocess_text(pattern)
                if processed:
                    augmented_patterns.append(processed)
                    augmented_tags.append(tag)
        
        return augmented_patterns, augmented_tags

    def handle(self, *args, **options):
        # File paths
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.dirname(base_dir)
        response_path = os.path.join(base_dir, 'response.json')
        model_path = os.path.join(base_dir, 'chatbot_model.h5')
        tokenizer_path = os.path.join(base_dir, 'chatbot_tokenizer.json')

        try:
            with open(response_path, 'r') as file:
                intents = json.load(file)['intents']
            logger.info(f"Loaded {len(intents)} intents from {response_path}")
        except FileNotFoundError:
            logger.error(f"response.json not found at {response_path}")
            return
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in {response_path}")
            return

        patterns = []
        tags = []
        for intent in intents:
            for pattern in intent['patterns']:
                patterns.append(pattern)
                tags.append(intent['tag'])

        if not patterns:
            logger.error("No patterns found in response.json")
            return

        patterns, tags = self.augment_patterns(patterns, tags)
        logger.info(f"Training with {len(patterns)} patterns after augmentation")

        tokenizer = Tokenizer(num_words=500, oov_token="<OOV>")  
        tokenizer.fit_on_texts(patterns)
        
        max_length = 15  
        sequences = tokenizer.texts_to_sequences(patterns)
        padded_sequences = pad_sequences(sequences, maxlen=max_length, padding='post')

        unique_tags = list(set(tags))
        logger.info(f"Found {len(unique_tags)} unique intents: {unique_tags}")
        
        tag_to_idx = {tag: idx for idx, tag in enumerate(unique_tags)}
        y = np.array([tag_to_idx[tag] for tag in tags])
        
        y_categorical = to_categorical(y, num_classes=len(unique_tags))

        try:
            vocab_size = len(tokenizer.word_index) + 1
            embedding_dim = 32  
            lstm_units = 32    
            # lstm here gives tag where pattern is
            model = Sequential([
                Embedding(vocab_size, embedding_dim, input_length=max_length),
                LSTM(lstm_units, dropout=0.2, recurrent_dropout=0.2),
                Dense(16, activation='relu'), 
                Dropout(0.3),
                Dense(len(unique_tags), activation='softmax')
            ])

            model.compile(
                loss='categorical_crossentropy',
                optimizer='adam',
                metrics=['accuracy']
            )

            model.build(input_shape=(None, max_length))
            
            logger.info("Model architecture:")
            model.summary()
            logger.info(f"\n📊 Model Parameters:")
            logger.info(f"   - Vocabulary size: {vocab_size}")
            logger.info(f"   - Embedding dimension: {embedding_dim}")
            logger.info(f"   - LSTM units: {lstm_units}")
            logger.info(f"   - Output classes: {len(unique_tags)}")
            logger.info(f"   - Max sequence length: {max_length}")
            logger.info(f"   - Total training samples: {len(padded_sequences)}\n")

            callbacks = [
                EarlyStopping(
                    monitor='val_accuracy',
                    patience=15,
                    restore_best_weights=True,
                    verbose=1
                )
            ]

            logger.info("Starting model training...")
            history = model.fit(
                padded_sequences, y_categorical,
                epochs=150,  
                batch_size=4, 
                validation_split=0.25,
                callbacks=callbacks,
                verbose=1
            )

            final_loss, final_accuracy = model.evaluate(padded_sequences, y_categorical, verbose=0)
            logger.info(f"\n✅ Final training accuracy: {final_accuracy:.4f}")
            logger.info(f"✅ Final training loss: {final_loss:.4f}")
            
            # Show validation accuracy
            best_val_acc = max(history.history['val_accuracy'])
            logger.info(f"✅ Best validation accuracy: {best_val_acc:.4f}")

            logger.info(f"\nSaving model to {model_path}")
            model.save(model_path)
            
            logger.info(f"Saving tokenizer to {tokenizer_path}")
            tokenizer_config = tokenizer.to_json()
            with open(tokenizer_path, 'w') as f:
                f.write(tokenizer_config)

            tag_mapping_path = os.path.join(base_dir, 'tag_mappings.json')
            with open(tag_mapping_path, 'w') as f:
                json.dump({
                    'tag_to_idx': tag_to_idx,
                    'idx_to_tag': {str(k): v for k, v in {idx: tag for tag, idx in tag_to_idx.items()}.items()},
                    'unique_tags': unique_tags,
                    'max_length': max_length  
                }, f, indent=2)

            self.stdout.write(
                self.style.SUCCESS(
                    f'\n{"="*60}\n'
                    f'✅ Model training completed successfully!\n'
                    f'{"="*60}\n'
                    f'📊 Training Results:\n'
                    f'   - Final training accuracy: {final_accuracy:.4f}\n'
                    f'   - Best validation accuracy: {best_val_acc:.4f}\n'
                    f'   - Training samples: {len(padded_sequences)}\n'
                    f'   - Unique intents: {len(unique_tags)}\n'
                    f'\n💾 Saved Files:\n'
                    f'   - Model: {model_path}\n'
                    f'   - Tokenizer: {tokenizer_path}\n'
                    f'   - Tag mappings: {tag_mapping_path}\n'
                    f'{"="*60}\n'
                )
            )

        except Exception as e:
            logger.error(f"Training failed: {str(e)}")
            self.stdout.write(self.style.ERROR(f'❌ Training failed: {str(e)}'))
            return
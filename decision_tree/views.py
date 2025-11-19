import os
import pickle
from django.shortcuts import render
from .models import EventPredictionCount
from django.conf import settings

MODEL_DIR = os.path.join(settings.BASE_DIR, 'dept_models')

def load_model_and_encoders(department):
    model_path = os.path.join(MODEL_DIR, f'clf_{department}.pkl')
    encoders_path = os.path.join(MODEL_DIR, f'encoders_{department}.pkl')

    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    with open(encoders_path, 'rb') as f:
        encoders = pickle.load(f)

    return model, encoders

def event_quiz_view(request):
    questions = [
        ('department', 'Which department are you from?', ['BCA', 'BCE', 'BCT', 'BEI', 'BEL']),
        ('event_type', 'Choose Event Type:', ['Guest Lecture', 'Hackathon', 'Seminar', 'Social', 'Workshop']),
        ('time_preference', 'Preferred Time:', ['Morning', 'Afternoon', 'Evening']),
        ('format', 'Preferred Format:', ['Hybrid','In-Person', 'Virtual']),
        ('interest', 'Your Interest:', ['Career Development', 'Fun', 'Inspiration', 'Networking', 'Skill-Building']),
    ]

    step = int(request.POST.get('step', 0)) if request.method == 'POST' else 0

    if 'quiz_answers' not in request.session:
        request.session['quiz_answers'] = {}

    if request.method == 'POST':
        selected_answer = request.POST.get('answer')
        if selected_answer:
            question_key = questions[step][0]
            # Save the answer in session
            request.session['quiz_answers'][question_key] = selected_answer
            request.session.modified = True
            step += 1

        if step == len(questions):
            # Pop the answers from the session
            answers = request.session.pop('quiz_answers')
            department = answers['department']

            model, encoders = load_model_and_encoders(department)
            
            def safe_transform(encoder, value):
                try:
                    return encoder.transform([value])[0]
                except ValueError:
                    return 0    
            # Converting the answers in numbers
            input_data = [
                safe_transform(encoders['Event_Type'], answers['event_type']),
                safe_transform(encoders['Time_Preference'], answers['time_preference']),
                safe_transform(encoders['Format'], answers['format']),
                safe_transform(encoders['Interest'], answers['interest']),
            ]

            prediction_encoded = model.predict([input_data])[0]
            predicted_event = encoders['Target_Event'].inverse_transform([prediction_encoded])[0]

            event_obj, _ = EventPredictionCount.objects.get_or_create(event_name=predicted_event)
            event_obj.count += 1
            event_obj.save()

            return render(request, 'decision_tree/quiz_result.html', {'predicted_event': predicted_event})

    # Show current question
    question_key, question_text, options = questions[step]

    context = {
        'step': step,
        'question_text': question_text,
        'options': options,
        'total_steps': len(questions),
        'next_step_exists': (step + 1) < len(questions),
    }
    return render(request, 'decision_tree/quiz.html', context)

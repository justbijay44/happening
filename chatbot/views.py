from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from .utils import get_dynamic_response

@csrf_exempt
def chat_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode('utf-8'))
            user_input = data.get("message", "").strip()
            
            # Debug logging
            print(f"Received message: '{user_input}'")
            
            if not user_input:
                return JsonResponse({"error": "Message cannot be empty"}, status=400)
            
            if len(user_input) > 200:
                return JsonResponse({"error": "Message too long"}, status=400)
            
            # Get response with HTML formatting for chat
            response = get_dynamic_response(user_input, html_output=True)
            
            # Debug logging
            print(f"Bot response: '{response[:100]}...'")
            
            return JsonResponse({"response": response})
        
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON. Send {'message': 'your text'}."}, status=400)
        except Exception as e:
            print(f"Error in chat_view: {e}")  # Debug logging
            return JsonResponse({"error": "Server error occurred"}, status=500)
    
    return JsonResponse({"response": "Use POST with a JSON body containing a 'message' field."})
# HAPPENING/chatbot/views.py
from django.http import JsonResponse
from django.shortcuts import render
from .utils.faqbot import get_response
from datetime import datetime

def chat_view(request):
    if request.method == "POST":
        user_input = request.POST.get("message", "").strip()
        context = request.session.get("chat_context", {})
        response, updated_context = get_response(user_input, context)
        request.session["chat_context"] = updated_context
        return JsonResponse({"response": response, "context": updated_context, "timestamp": datetime.now().strftime("%I:%M %p")})
    return JsonResponse({"error": "Use POST method with 'message' parameter"}, status=400)

def chat_interface(request):
    return render(request, 'chatbot/index.html')
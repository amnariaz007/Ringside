from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import service


@csrf_exempt  # PayPal can't send a CSRF token; authenticity comes from signature verification.
@require_POST
def paypal_webhook(request):
    headers = {k: v for k, v in request.headers.items()}
    result = service.handle(request.body, headers)
    return JsonResponse({"detail": result.message}, status=result.status)

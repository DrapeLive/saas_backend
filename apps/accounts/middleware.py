from django.utils.deprecation import MiddlewareMixin


class CompanyScopeMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not hasattr(request, "company"):
            request.company = None

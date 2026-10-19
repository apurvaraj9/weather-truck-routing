from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path


def frontend_missing(_request):
    """Shown only if the React build is not present (e.g. backend run alone in dev)."""
    return HttpResponse(
        "<h1>Backend is running</h1><p>The React build was not found at "
        f"<code>{settings.FRONTEND_DIST}</code>. In development open the Vite dev server "
        "(http://localhost:5173) instead, or run <code>npm run build</code> in /frontend.</p>",
        content_type="text/html",
    )


urlpatterns = [
    path("api/", include("planner.urls")),
    path("", frontend_missing),  # WhiteNoise serves index.html first when the build exists
]

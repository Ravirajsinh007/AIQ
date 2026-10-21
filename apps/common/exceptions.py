import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Standardizes error responses across all API endpoints:
    {
        "error": {
            "code": "status_or_custom_code",
            "message": "Human readable summary",
            "details": {...}
        }
    }
    Prevents sensitive exception tracebacks from leaking to clients.
    """
    response = exception_handler(exc, context)

    if response is not None:
        custom_data = {
            'error': {
                'code': getattr(exc, 'default_code', 'error'),
                'message': 'An error occurred during request processing.',
                'details': response.data
            }
        }

        # Handle specific common status codes
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            custom_data['error']['message'] = 'Request validation failed.'
        elif response.status_code == status.HTTP_401_UNAUTHORIZED:
            custom_data['error']['message'] = 'Authentication credentials were not provided or are invalid.'
        elif response.status_code == status.HTTP_403_FORBIDDEN:
            custom_data['error']['message'] = 'You do not have permission to perform this action.'
        elif response.status_code == status.HTTP_404_NOT_FOUND:
            custom_data['error']['message'] = 'The requested resource was not found.'
        elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            custom_data['error']['message'] = 'Request rate limit exceeded. Please try again later.'

        response.data = custom_data
        return response

    # Handle unhandled 500 exceptions securely
    logger.exception('Unhandled exception occurred in API request: %s', exc)
    return Response(
        {
            'error': {
                'code': 'internal_server_error',
                'message': 'An unexpected internal server error occurred.',
                'details': None
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )

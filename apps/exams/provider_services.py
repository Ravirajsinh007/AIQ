import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings


class ProviderConfigurationError(Exception):
    pass


class ProviderExecutionError(Exception):
    pass


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _post_json(url, token, payload, timeout):
    parsed_url = urlparse(url)
    if parsed_url.scheme != 'https' or not parsed_url.netloc or not token:
        raise ProviderConfigurationError(
            'Provider URL must be HTTPS and its bearer token must be configured.'
        )
    request = Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    opener = build_opener(_RejectRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
    except HTTPError as exc:
        exc.close()
        raise ProviderExecutionError('The configured external provider request failed.') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderExecutionError('The configured external provider request failed.') from exc
    except ValueError as exc:
        raise ProviderConfigurationError('The configured provider URL is invalid.') from exc
    if len(body) > 1024 * 1024:
        raise ProviderExecutionError('The external provider response exceeded the size limit.')
    try:
        result = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderExecutionError('The external provider returned invalid JSON.') from exc
    if not isinstance(result, dict):
        raise ProviderExecutionError('The external provider returned an invalid response shape.')
    return result


class CodeExecutionProvider:
    """HTTPS adapter for an isolated code runner; submitted code is never run by Django."""

    def execute(self, *, code, language, test_cases, time_limit_seconds, memory_limit_mb):
        url = getattr(settings, 'CODE_EXECUTION_PROVIDER_URL', '')
        token = getattr(settings, 'CODE_EXECUTION_PROVIDER_TOKEN', '')
        if not url or not token:
            raise ProviderConfigurationError(
                'Set CODE_EXECUTION_PROVIDER_URL and CODE_EXECUTION_PROVIDER_TOKEN '
                'to an isolated HTTPS code-execution service.'
            )
        payload = {
            'code': code,
            'language': language,
            'test_cases': [
                {'input': case['input'], 'expected_output': case['expected_output']}
                for case in test_cases
            ],
            'limits': {
                'time_limit_seconds': time_limit_seconds,
                'memory_limit_mb': memory_limit_mb,
            },
        }
        response = _post_json(
            url, token, payload,
            timeout=getattr(settings, 'CODE_EXECUTION_PROVIDER_TIMEOUT_SECONDS', 20),
        )
        passed = response.get('passed')
        if (
            not isinstance(passed, list)
            or len(passed) != len(test_cases)
            or any(not isinstance(value, bool) for value in passed)
        ):
            raise ProviderExecutionError(
                'The code-execution provider must return one boolean pass result per test case.'
            )
        return passed


class OCRProvider:
    """HTTPS adapter for a configured OCR service; no local/fallback OCR is fabricated."""

    def extract_text(self, *, file_bytes, filename, content_type):
        import base64

        url = getattr(settings, 'OCR_PROVIDER_URL', '')
        token = getattr(settings, 'OCR_PROVIDER_TOKEN', '')
        if not url or not token:
            raise ProviderConfigurationError(
                'Set OCR_PROVIDER_URL and OCR_PROVIDER_TOKEN to an OCR provider using the '
                'documented JSON contract.'
            )
        response = _post_json(
            url,
            token,
            {
                'filename': filename,
                'content_type': content_type,
                'file_base64': base64.b64encode(file_bytes).decode('ascii'),
            },
            timeout=getattr(settings, 'OCR_PROVIDER_TIMEOUT_SECONDS', 30),
        )
        text = response.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
            raise ProviderExecutionError(
                'The OCR provider must return non-empty text no longer than 1,000,000 characters.'
            )
        return text.strip()

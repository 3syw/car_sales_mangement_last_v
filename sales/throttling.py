from rest_framework.throttling import SimpleRateThrottle


class TenantCredentialThrottle(SimpleRateThrottle):
    """Throttle auth endpoints using tenant+username+IP to reduce brute-force attempts."""

    def get_cache_key(self, request, view):
        tenant_id = (
            request.data.get('tenant_id')
            or request.headers.get('X-Tenant-ID')
            or request.META.get('HTTP_X_TENANT_ID')
            or ''
        )
        username = request.data.get('username') or ''
        identifier = f"{tenant_id}:{username}:{self.get_ident(request)}"
        return self.cache_format % {'scope': self.scope, 'ident': identifier}


class AuthTokenBurstThrottle(TenantCredentialThrottle):
    scope = 'auth_token_burst'


class AuthTokenSustainedThrottle(TenantCredentialThrottle):
    scope = 'auth_token_sustained'


class AuthRefreshBurstThrottle(SimpleRateThrottle):
    scope = 'auth_refresh_burst'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class AuthRefreshSustainedThrottle(SimpleRateThrottle):
    scope = 'auth_refresh_sustained'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}

export const ACCESS_TOKEN_STORAGE_KEY = 'aasmaa_access_token';
export const REFRESH_TOKEN_STORAGE_KEY = 'aasmaa_refresh_token';
export const USER_STORAGE_KEY = 'aasmaa_user';

type ApiFetchOptions = RequestInit & {
    skipAuth?: boolean;
    retryOnAuthFailure?: boolean;
};

const isAuthUrl = (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    return url.includes('/api/auth/login') || url.includes('/api/auth/refresh');
};

export const getAccessToken = (): string | null => localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
export const getRefreshToken = (): string | null => localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);

export const storeAuthTokens = (accessToken: string, refreshToken: string) => {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, refreshToken);
};

export const clearAuthStorage = () => {
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    localStorage.removeItem(USER_STORAGE_KEY);
    localStorage.removeItem('aasmaa_authenticated');
};

export const storeUserSnapshot = (user: unknown) => {
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    localStorage.setItem('aasmaa_authenticated', 'true');
};

async function refreshAccessToken(): Promise<string | null> {
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
        return null;
    }

    const response = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
        clearAuthStorage();
        return null;
    }

    const data = await response.json();
    if (!data?.access_token) {
        clearAuthStorage();
        return null;
    }

    storeAuthTokens(data.access_token, refreshToken);
    return data.access_token;
}

export async function apiFetch(input: RequestInfo | URL, init: ApiFetchOptions = {}): Promise<Response> {
    const { skipAuth = false, retryOnAuthFailure = true, ...requestInit } = init;
    const headers = new Headers(requestInit.headers || {});
    const accessToken = getAccessToken();

    if (!skipAuth && accessToken && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${accessToken}`);
    }

    const response = await fetch(input, {
        ...requestInit,
        headers,
    });

    if (
        response.status === 401 &&
        !skipAuth &&
        retryOnAuthFailure &&
        !isAuthUrl(input) &&
        getRefreshToken()
    ) {
        const refreshedAccessToken = await refreshAccessToken();
        if (!refreshedAccessToken) {
            return response;
        }

        const retryHeaders = new Headers(requestInit.headers || {});
        retryHeaders.set('Authorization', `Bearer ${refreshedAccessToken}`);

        return fetch(input, {
            ...requestInit,
            headers: retryHeaders,
        });
    }

    return response;
}
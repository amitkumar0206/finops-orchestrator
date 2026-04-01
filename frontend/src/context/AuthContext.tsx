import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

import {
    apiFetch,
    clearAuthStorage,
    getAccessToken,
    getRefreshToken,
    storeAuthTokens,
    storeUserSnapshot,
} from '../lib/api';

export interface FeatureAccess {
    chat: boolean;
    analyze: boolean;
    generate: boolean;
    opportunities: boolean;
    admin_console: boolean;
}

export interface AuthUser {
    id: string;
    email: string;
    full_name?: string | null;
    is_admin: boolean;
    organization_id?: string | null;
    organization_name?: string | null;
    department?: string | null;
    title?: string | null;
    org_role?: string | null;
    feature_access: FeatureAccess;
    usage_summary?: {
        monthly_token_limit?: number;
        monthly_token_used?: number;
        queries_run?: number;
        analysis_runs?: number;
        generate_runs?: number;
    } | null;
}

interface DemoCatalogUser {
    id: string;
    email: string;
    full_name: string;
    org_role: string;
    department?: string | null;
    demo_password_hint?: string | null;
    feature_access: FeatureAccess;
}

interface DemoCatalog {
    users: DemoCatalogUser[];
    organization?: {
        name?: string;
    };
}

interface LoginPayload {
    email: string;
    password: string;
}

interface AuthContextValue {
    user: AuthUser | null;
    isAuthenticated: boolean;
    isCheckingAuth: boolean;
    demoCatalog: DemoCatalog | null;
    login: (payload: LoginPayload) => Promise<void>;
    logout: () => Promise<void>;
    refreshUser: () => Promise<void>;
    canAccess: (feature: keyof FeatureAccess) => boolean;
}

const defaultFeatures: FeatureAccess = {
    chat: false,
    analyze: false,
    generate: false,
    opportunities: false,
    admin_console: false,
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const normalizeUser = (user: Partial<AuthUser> | null | undefined): AuthUser | null => {
    if (!user?.id || !user.email) {
        return null;
    }

    return {
        id: user.id,
        email: user.email,
        full_name: user.full_name ?? null,
        is_admin: Boolean(user.is_admin),
        organization_id: user.organization_id ?? null,
        organization_name: user.organization_name ?? null,
        department: user.department ?? null,
        title: user.title ?? null,
        org_role: user.org_role ?? null,
        feature_access: {
            ...defaultFeatures,
            ...(user.feature_access || {}),
        },
        usage_summary: user.usage_summary ?? null,
    };
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [isCheckingAuth, setIsCheckingAuth] = useState(true);
    const [demoCatalog, setDemoCatalog] = useState<DemoCatalog | null>(null);

    const refreshUser = async () => {
        const accessToken = getAccessToken();
        if (!accessToken) {
            setUser(null);
            return;
        }

        const response = await apiFetch('/api/auth/me');
        if (!response.ok) {
            clearAuthStorage();
            setUser(null);
            return;
        }

        const payload = await response.json();
        const nextUser = normalizeUser(payload?.user);
        setUser(nextUser);
        if (nextUser) {
            storeUserSnapshot(nextUser);
        }
    };

    useEffect(() => {
        const bootstrap = async () => {
            try {
                const catalogResponse = await fetch('/api/auth/demo/catalog');
                if (catalogResponse.ok) {
                    const catalog = await catalogResponse.json();
                    setDemoCatalog(catalog);
                }
            } catch {
                setDemoCatalog(null);
            }

            if (getAccessToken() && getRefreshToken()) {
                await refreshUser();
            }

            setIsCheckingAuth(false);
        };

        void bootstrap();
    }, []);

    const login = async ({ email, password }: LoginPayload) => {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email, password }),
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload?.detail || payload?.message || 'Login failed');
        }

        storeAuthTokens(payload.access_token, payload.refresh_token);
        const nextUser = normalizeUser(payload.user);
        setUser(nextUser);
        if (nextUser) {
            storeUserSnapshot(nextUser);
        }
    };

    const logout = async () => {
        try {
            if (getAccessToken()) {
                await apiFetch('/api/auth/logout', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ refresh_token: getRefreshToken() }),
                    retryOnAuthFailure: false,
                });
            }
        } finally {
            clearAuthStorage();
            setUser(null);
        }
    };

    const value = useMemo<AuthContextValue>(() => ({
        user,
        isAuthenticated: Boolean(user),
        isCheckingAuth,
        demoCatalog,
        login,
        logout,
        refreshUser,
        canAccess: (feature) => Boolean(user?.is_admin || user?.feature_access?.[feature]),
    }), [demoCatalog, isCheckingAuth, user]);

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
    const value = useContext(AuthContext);
    if (!value) {
        throw new Error('useAuth must be used inside AuthProvider');
    }
    return value;
};
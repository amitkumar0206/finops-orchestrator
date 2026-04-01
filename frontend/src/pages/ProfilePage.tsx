import React, { useEffect, useMemo, useState } from 'react';
import {
    Box,
    Typography,
    Paper,
    Avatar,
    Divider,
    Chip,
    Alert,
    LinearProgress,
    List,
    ListItem,
    ListItemText,
    ListItemIcon,
} from '@mui/material';
import {
    CheckCircleOutline,
    AccessTimeOutlined,
    TrendingDown,
    CloudOutlined,
} from '@mui/icons-material';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/api';

const ProfilePage: React.FC = () => {
    const { user } = useAuth();
    const [usage, setUsage] = useState<any | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const loadUsage = async () => {
            try {
                const response = await apiFetch('/api/demo/me/usage');
                if (!response.ok) {
                    const payload = await response.json().catch(() => ({}));
                    throw new Error(payload?.detail || 'Failed to load profile usage');
                }
                const data = await response.json();
                setUsage(data);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load usage');
            }
        };

        void loadUsage();
    }, []);

    const stats = useMemo(() => ([
        { label: 'Queries Run', value: `${usage?.usage?.queries_run || 0}`, sub: 'Chat requests' },
        { label: 'Analyze Runs', value: `${usage?.usage?.analysis_runs || 0}`, sub: 'IaC reviews' },
        { label: 'Generate Runs', value: `${usage?.usage?.generate_runs || 0}`, sub: 'Blueprint workflows' },
        { label: 'Token Used', value: `${(usage?.usage?.monthly_token_used || 0).toLocaleString()}`, sub: 'This month' },
    ]), [usage]);

    const featureChips = Object.entries(user?.feature_access || {}).filter(([, enabled]) => enabled);
    const tokenLimit = usage?.usage?.monthly_token_limit || user?.usage_summary?.monthly_token_limit || 0;
    const tokenUsed = usage?.usage?.monthly_token_used || user?.usage_summary?.monthly_token_used || 0;
    const utilizationPct = tokenLimit ? Math.round((tokenUsed / tokenLimit) * 100) : 0;

    return (
        <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 820, mx: 'auto' }}>
            <Box sx={{ mb: 4 }}>
                <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.6rem' }}>
                    Profile
                </Typography>
                <Typography sx={{ color: '#64748b', mt: 0.5 }}>
                    Manage your personal information and account details.
                </Typography>
            </Box>

            {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}

            {/* Profile card */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 3 }}>
                <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 3 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2.5 }}>
                        <Avatar
                            sx={{
                                width: 72,
                                height: 72,
                                bgcolor: '#1565C0',
                                color: 'white',
                                fontWeight: 800,
                                fontSize: '1.8rem',
                            }}
                        >
                            {(user?.full_name || user?.email || 'A').charAt(0).toUpperCase()}
                        </Avatar>
                        <Box>
                            <Typography sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.2rem' }}>
                                {user?.full_name || user?.email}
                            </Typography>
                            <Typography sx={{ color: '#64748b', fontSize: '0.9rem' }}>{user?.email}</Typography>
                            <Chip
                                label={user?.is_admin ? 'Demo Admin' : (user?.org_role || 'member')}
                                size="small"
                                sx={{
                                    mt: 0.75,
                                    bgcolor: 'rgba(21,101,192,0.1)',
                                    color: '#1565C0',
                                    fontWeight: 700,
                                    fontSize: '0.75rem',
                                    border: '1px solid rgba(21,101,192,0.2)',
                                }}
                            />
                        </Box>
                    </Box>
                    <Chip label={user?.organization_name || 'Demo organization'} sx={{ bgcolor: 'rgba(15,23,42,0.06)', color: '#334155', fontWeight: 700 }} />
                </Box>

                <Divider sx={{ mb: 3 }} />

                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2.2 }}>
                    {[
                        { label: 'Full Name', value: user?.full_name || 'Not provided' },
                        { label: 'Email Address', value: user?.email || 'Not provided' },
                        { label: 'Role', value: user?.org_role || 'member' },
                        { label: 'Organization', value: user?.organization_name || 'Demo organization' },
                        { label: 'Department', value: user?.department || 'Not provided' },
                        { label: 'Title', value: user?.title || 'Not provided' },
                    ].map((field) => (
                        <Paper key={field.label} elevation={0} sx={{ p: 1.8, borderRadius: 2.5, bgcolor: 'rgba(15,23,42,0.03)', border: '1px solid rgba(15,23,42,0.06)' }}>
                            <Typography sx={{ fontSize: '0.76rem', textTransform: 'uppercase', letterSpacing: 0.35, color: '#64748b', fontWeight: 700 }}>{field.label}</Typography>
                            <Typography sx={{ color: '#0f172a', fontWeight: 600, mt: 0.45 }}>{field.value}</Typography>
                        </Paper>
                    ))}
                </Box>
            </Paper>

            {/* Stats */}
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4,1fr)' }, gap: 2, mb: 3 }}>
                {stats.map((s) => (
                    <Paper
                        key={s.label}
                        elevation={0}
                        sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 2.5, textAlign: 'center' }}
                    >
                        <Typography sx={{ fontWeight: 800, fontSize: '1.5rem', color: '#1565C0' }}>{s.value}</Typography>
                        <Typography sx={{ fontWeight: 700, fontSize: '0.82rem', color: '#0f172a', mt: 0.25 }}>{s.label}</Typography>
                        <Typography sx={{ fontSize: '0.75rem', color: '#94a3b8' }}>{s.sub}</Typography>
                    </Paper>
                ))}
            </Box>

            {/* Usage */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 3 }}>
                <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 2 }}>Monthly Usage</Typography>
                {[
                    { label: 'Chat Queries', used: usage?.usage?.queries_run || 0, limit: Math.max(usage?.usage?.queries_run || 0, 500) },
                    { label: 'AI Tokens', used: tokenUsed, limit: tokenLimit || Math.max(tokenUsed, 1000) },
                    { label: 'Generate Runs', used: usage?.usage?.generate_runs || 0, limit: Math.max(usage?.usage?.generate_runs || 0, 20) },
                ].map((item) => {
                    const pct = Math.round((item.used / item.limit) * 100);
                    return (
                        <Box key={item.label} sx={{ mb: 2 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                                <Typography sx={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155' }}>{item.label}</Typography>
                                <Typography sx={{ fontSize: '0.82rem', color: '#64748b' }}>
                                    {item.used.toLocaleString()} / {item.limit.toLocaleString()} ({pct}%)
                                </Typography>
                            </Box>
                            <LinearProgress
                                variant="determinate"
                                value={pct}
                                sx={{
                                    height: 6,
                                    borderRadius: 4,
                                    bgcolor: 'rgba(21,101,192,0.1)',
                                    '& .MuiLinearProgress-bar': {
                                        borderRadius: 4,
                                        bgcolor: pct > 80 ? '#ef4444' : '#1565C0',
                                    },
                                }}
                            />
                        </Box>
                    );
                })}

                <Box sx={{ mt: 2.25, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    {featureChips.map(([feature]) => (
                        <Chip key={feature} label={`Access: ${feature}`} size="small" sx={{ bgcolor: 'rgba(21,101,192,0.08)', color: '#1565C0', fontWeight: 700 }} />
                    ))}
                    <Chip label={`Token utilization ${utilizationPct}%`} size="small" sx={{ bgcolor: 'rgba(15,23,42,0.06)', color: '#334155', fontWeight: 700 }} />
                </Box>
            </Paper>

            {/* Recent activity */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3 }}>
                <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 1.5 }}>Recent Activity</Typography>
                <List disablePadding>
                    {(usage?.recent_activity || []).map((item: any, i: number) => {
                        const action = String(item.action || 'activity');
                        const icon = action.includes('generate')
                            ? <CloudOutlined sx={{ fontSize: 18, color: '#1565C0' }} />
                            : action.includes('analyze')
                                ? <TrendingDown sx={{ fontSize: 18, color: '#1565C0' }} />
                                : action.includes('login')
                                    ? <CheckCircleOutline sx={{ fontSize: 18, color: '#2e7d32' }} />
                                    : <AccessTimeOutlined sx={{ fontSize: 18, color: '#ed6c02' }} />;
                        return (
                            <React.Fragment key={i}>
                                {i > 0 && <Divider sx={{ my: 0.5 }} />}
                                <ListItem disablePadding sx={{ py: 0.75 }}>
                                    <ListItemIcon sx={{ minWidth: 36 }}>{icon}</ListItemIcon>
                                    <ListItemText
                                        primary={action.replace(':', ' · ')}
                                        secondary={new Date(item.timestamp).toLocaleString()}
                                        primaryTypographyProps={{ fontSize: '0.875rem', fontWeight: 500, color: '#334155' }}
                                        secondaryTypographyProps={{ fontSize: '0.78rem', color: '#94a3b8' }}
                                    />
                                </ListItem>
                            </React.Fragment>
                        )
                    })}
                </List>
            </Paper>
        </Box>
    );
};

export default ProfilePage;

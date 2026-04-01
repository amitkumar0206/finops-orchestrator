import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Divider,
    FormControlLabel,
    Grid,
    MenuItem,
    Paper,
    Stack,
    Switch,
    TextField,
    Typography,
} from '@mui/material';
import {
    AdminPanelSettingsOutlined,
    GroupOutlined,
    ManageAccountsOutlined,
    TimelineOutlined,
} from '@mui/icons-material';

import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/api';

interface DemoUser {
    id: string;
    email: string;
    full_name: string;
    department?: string | null;
    title?: string | null;
    org_role?: string | null;
    is_admin: boolean;
    is_active: boolean;
    monthly_token_limit: number;
    feature_access: Record<string, boolean>;
    usage?: {
        monthly_token_used?: number;
        queries_run?: number;
        analysis_runs?: number;
        generate_runs?: number;
    };
}

interface AdminSummary {
    organization: { name?: string };
    totals: {
        user_count: number;
        active_user_count: number;
        admin_count: number;
        monthly_token_limit: number;
        monthly_token_used: number;
        monthly_token_remaining: number;
    };
    feature_access_counts: Record<string, number>;
    recent_activity: Array<{
        timestamp: string;
        action: string;
        details?: Record<string, unknown>;
    }>;
    users: DemoUser[];
}

const featureLabels: Record<string, string> = {
    chat: 'Chat',
    analyze: 'Analyze',
    generate: 'Generate',
    opportunities: 'Opportunities',
    admin_console: 'Admin',
};

const emptyNewUser = {
    email: '',
    full_name: '',
    password: '',
    department: '',
    title: '',
    org_role: 'member',
    monthly_token_limit: 250000,
    is_admin: false,
    is_active: true,
    feature_access: {
        chat: true,
        analyze: true,
        generate: false,
        opportunities: true,
        admin_console: false,
    },
};

const AdminConsolePage: React.FC = () => {
    const { user } = useAuth();
    const [summary, setSummary] = useState<AdminSummary | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);
    const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);
    const [drafts, setDrafts] = useState<Record<string, DemoUser>>({});
    const [newUser, setNewUser] = useState(emptyNewUser);

    const loadSummary = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const response = await apiFetch('/api/demo/admin/summary');
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                throw new Error(payload?.detail || 'Failed to load admin summary');
            }
            const data: AdminSummary = await response.json();
            setSummary(data);
            setDrafts(Object.fromEntries(data.users.map((entry) => [entry.id, { ...entry }])));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load admin summary');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        void loadSummary();
    }, []);

    const totalUtilization = useMemo(() => {
        if (!summary?.totals.monthly_token_limit) return 0;
        return Math.round((summary.totals.monthly_token_used / summary.totals.monthly_token_limit) * 100);
    }, [summary]);

    const handleCreateUser = async () => {
        setError(null);
        setSaveMessage(null);
        setGeneratedPassword(null);

        try {
            const response = await apiFetch('/api/demo/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newUser),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload?.detail || 'Failed to create user');
            }
            setGeneratedPassword(payload.generated_password || null);
            setSaveMessage(`Created ${payload.user?.email || 'user'}`);
            setNewUser(emptyNewUser);
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to create user');
        }
    };

    const handleSaveUser = async (userId: string) => {
        setError(null);
        setSaveMessage(null);
        const draft = drafts[userId];
        if (!draft) return;

        try {
            const response = await apiFetch(`/api/demo/admin/users/${userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    full_name: draft.full_name,
                    department: draft.department,
                    title: draft.title,
                    org_role: draft.org_role,
                    is_admin: draft.is_admin,
                    is_active: draft.is_active,
                    monthly_token_limit: Number(draft.monthly_token_limit) || 0,
                    feature_access: draft.feature_access,
                }),
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(payload?.detail || 'Failed to update user');
            }
            setSaveMessage(`Updated ${payload.user?.email || 'user'}`);
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update user');
        }
    };

    if (!user?.is_admin) {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 920, mx: 'auto' }}>
                <Alert severity="error">This page is available only to demo admins.</Alert>
            </Box>
        );
    }

    return (
        <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 1180, mx: 'auto' }}>
            <Box sx={{ mb: 4 }}>
                <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.7rem' }}>
                    Demo Admin Console
                </Typography>
                <Typography sx={{ color: '#64748b', mt: 0.75 }}>
                    Create users, assign token allotments, manage feature access, and monitor team usage without a database.
                </Typography>
            </Box>

            {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
            {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}
            {generatedPassword && (
                <Alert severity="info" sx={{ mb: 3, borderRadius: 2 }}>
                    Temporary password for the new user: <strong>{generatedPassword}</strong>
                </Alert>
            )}

            <Grid container spacing={2} sx={{ mb: 3 }}>
                {[
                    { icon: <GroupOutlined />, label: 'Users', value: summary?.totals.user_count ?? '-', sub: `${summary?.totals.active_user_count ?? '-'} active` },
                    { icon: <AdminPanelSettingsOutlined />, label: 'Admins', value: summary?.totals.admin_count ?? '-', sub: 'Config-backed demo admins' },
                    { icon: <TimelineOutlined />, label: 'Token usage', value: summary ? `${totalUtilization}%` : '-', sub: `${summary?.totals.monthly_token_used?.toLocaleString() ?? '-'} used` },
                    { icon: <ManageAccountsOutlined />, label: 'Organization', value: summary?.organization.name || '-', sub: 'Demo tenant' },
                ].map((metric) => (
                    <Grid item xs={12} sm={6} md={3} key={metric.label}>
                        <Paper elevation={0} sx={{ p: 2.2, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                            <Stack direction="row" spacing={1.2} sx={{ alignItems: 'center', mb: 1 }}>
                                <Box sx={{ color: '#1565C0' }}>{metric.icon}</Box>
                                <Typography sx={{ fontWeight: 700, color: '#334155', fontSize: '0.88rem' }}>{metric.label}</Typography>
                            </Stack>
                            <Typography sx={{ fontWeight: 800, fontSize: '1.55rem', color: '#0f172a' }}>{metric.value}</Typography>
                            <Typography sx={{ color: '#64748b', fontSize: '0.78rem', mt: 0.35 }}>{metric.sub}</Typography>
                        </Paper>
                    </Grid>
                ))}
            </Grid>

            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', mb: 3 }}>
                <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 2 }}>Create demo user</Typography>
                <Grid container spacing={2}>
                    <Grid item xs={12} md={4}>
                        <TextField fullWidth label="Email" value={newUser.email} onChange={(e) => setNewUser((prev) => ({ ...prev, email: e.target.value }))} />
                    </Grid>
                    <Grid item xs={12} md={4}>
                        <TextField fullWidth label="Full name" value={newUser.full_name} onChange={(e) => setNewUser((prev) => ({ ...prev, full_name: e.target.value }))} />
                    </Grid>
                    <Grid item xs={12} md={4}>
                        <TextField fullWidth label="Password (optional)" value={newUser.password} onChange={(e) => setNewUser((prev) => ({ ...prev, password: e.target.value }))} helperText="Leave blank to auto-generate" />
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <TextField fullWidth select label="Role" value={newUser.org_role} onChange={(e) => setNewUser((prev) => ({ ...prev, org_role: e.target.value }))}>
                            {['owner', 'admin', 'member', 'viewer', 'developer', 'devops'].map((role) => (
                                <MenuItem key={role} value={role}>{role}</MenuItem>
                            ))}
                        </TextField>
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <TextField fullWidth label="Department" value={newUser.department} onChange={(e) => setNewUser((prev) => ({ ...prev, department: e.target.value }))} />
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <TextField fullWidth label="Title" value={newUser.title} onChange={(e) => setNewUser((prev) => ({ ...prev, title: e.target.value }))} />
                    </Grid>
                    <Grid item xs={12} md={3}>
                        <TextField fullWidth type="number" label="Monthly token limit" value={newUser.monthly_token_limit} onChange={(e) => setNewUser((prev) => ({ ...prev, monthly_token_limit: Number(e.target.value) || 0 }))} />
                    </Grid>
                    <Grid item xs={12}>
                        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: { md: 'center' }, justifyContent: 'space-between' }}>
                            <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
                                <FormControlLabel control={<Switch checked={newUser.is_active} onChange={(e) => setNewUser((prev) => ({ ...prev, is_active: e.target.checked }))} />} label="Active" />
                                <FormControlLabel control={<Switch checked={newUser.is_admin} onChange={(e) => setNewUser((prev) => ({ ...prev, is_admin: e.target.checked, feature_access: { ...prev.feature_access, admin_console: e.target.checked } }))} />} label="Admin" />
                                {Object.entries(featureLabels).map(([feature, label]) => {
                                    const featureKey = feature as keyof typeof newUser.feature_access;
                                    return (
                                        <FormControlLabel
                                            key={feature}
                                            control={
                                                <Switch
                                                    checked={Boolean(newUser.feature_access[featureKey])}
                                                    onChange={(e) => setNewUser((prev) => ({
                                                        ...prev,
                                                        feature_access: {
                                                            ...prev.feature_access,
                                                            [feature]: e.target.checked,
                                                        },
                                                    }))}
                                                />
                                            }
                                            label={label}
                                        />
                                    );
                                })}
                            </Stack>
                            <Button variant="contained" onClick={handleCreateUser} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>
                                Create user
                            </Button>
                        </Stack>
                    </Grid>
                </Grid>
            </Paper>

            <Stack spacing={2.5}>
                {isLoading && <Alert severity="info">Loading admin summary...</Alert>}
                {!isLoading && summary?.users.map((entry) => {
                    const draft = drafts[entry.id] || entry;
                    const utilizationPct = draft.monthly_token_limit
                        ? Math.round(((draft.usage?.monthly_token_used || 0) / draft.monthly_token_limit) * 100)
                        : 0;

                    return (
                        <Card key={entry.id} elevation={0} sx={{ borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                            <CardContent sx={{ p: 3 }}>
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ justifyContent: 'space-between', mb: 2 }}>
                                    <Box>
                                        <Typography sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.06rem' }}>{entry.full_name}</Typography>
                                        <Typography sx={{ color: '#64748b', fontSize: '0.9rem' }}>{entry.email}</Typography>
                                        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', mt: 1 }}>
                                            <Chip size="small" label={draft.org_role || 'member'} sx={{ bgcolor: 'rgba(21,101,192,0.08)', color: '#1565C0', fontWeight: 700 }} />
                                            <Chip size="small" label={draft.is_admin ? 'Admin' : 'Standard user'} sx={{ bgcolor: draft.is_admin ? 'rgba(13,71,161,0.1)' : 'rgba(100,116,139,0.1)', color: draft.is_admin ? '#0D47A1' : '#475569' }} />
                                            <Chip size="small" label={`${utilizationPct}% of token budget`} sx={{ bgcolor: 'rgba(15,23,42,0.06)', color: '#334155' }} />
                                        </Stack>
                                    </Box>
                                    <Button variant="contained" onClick={() => void handleSaveUser(entry.id)} sx={{ alignSelf: { xs: 'stretch', md: 'flex-start' }, textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>
                                        Save changes
                                    </Button>
                                </Stack>

                                <Grid container spacing={2}>
                                    <Grid item xs={12} md={4}>
                                        <TextField fullWidth label="Full name" value={draft.full_name} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, full_name: e.target.value } }))} />
                                    </Grid>
                                    <Grid item xs={12} md={3}>
                                        <TextField fullWidth select label="Role" value={draft.org_role || 'member'} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, org_role: e.target.value } }))}>
                                            {['owner', 'admin', 'member', 'viewer', 'developer', 'devops'].map((role) => (
                                                <MenuItem key={role} value={role}>{role}</MenuItem>
                                            ))}
                                        </TextField>
                                    </Grid>
                                    <Grid item xs={12} md={2.5}>
                                        <TextField fullWidth type="number" label="Token limit" value={draft.monthly_token_limit} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, monthly_token_limit: Number(e.target.value) || 0 } }))} />
                                    </Grid>
                                    <Grid item xs={12} md={2.5}>
                                        <TextField fullWidth label="Department" value={draft.department || ''} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, department: e.target.value } }))} />
                                    </Grid>
                                </Grid>

                                <Divider sx={{ my: 2 }} />

                                <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} sx={{ justifyContent: 'space-between' }}>
                                    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
                                        <FormControlLabel control={<Switch checked={draft.is_active} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, is_active: e.target.checked } }))} />} label="Active" />
                                        <FormControlLabel control={<Switch checked={draft.is_admin} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, is_admin: e.target.checked, feature_access: { ...draft.feature_access, admin_console: e.target.checked } } }))} />} label="Admin" />
                                        {Object.entries(featureLabels).map(([feature, label]) => (
                                            <FormControlLabel
                                                key={`${entry.id}-${feature}`}
                                                control={<Switch checked={Boolean(draft.feature_access?.[feature])} onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.id]: { ...draft, feature_access: { ...draft.feature_access, [feature]: e.target.checked } } }))} />}
                                                label={label}
                                            />
                                        ))}
                                    </Stack>
                                    <Box sx={{ minWidth: { lg: 260 } }}>
                                        <Typography sx={{ fontWeight: 700, color: '#0f172a', fontSize: '0.88rem' }}>Usage snapshot</Typography>
                                        <Typography sx={{ color: '#64748b', fontSize: '0.82rem', mt: 0.35 }}>
                                            Tokens used: {(draft.usage?.monthly_token_used || 0).toLocaleString()} / {Number(draft.monthly_token_limit || 0).toLocaleString()}
                                        </Typography>
                                        <Typography sx={{ color: '#64748b', fontSize: '0.82rem' }}>
                                            Queries: {draft.usage?.queries_run || 0} · Analyze: {draft.usage?.analysis_runs || 0} · Generate: {draft.usage?.generate_runs || 0}
                                        </Typography>
                                    </Box>
                                </Stack>
                            </CardContent>
                        </Card>
                    );
                })}
            </Stack>

            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', mt: 3 }}>
                <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 2 }}>Recent activity</Typography>
                <Stack spacing={1.2}>
                    {summary?.recent_activity.slice(0, 8).map((item, index) => (
                        <Box key={`${item.timestamp}-${index}`} sx={{ p: 1.4, borderRadius: 2, bgcolor: 'rgba(15,23,42,0.03)' }}>
                            <Typography sx={{ fontWeight: 600, color: '#334155', fontSize: '0.88rem' }}>{item.action}</Typography>
                            <Typography sx={{ color: '#64748b', fontSize: '0.78rem', mt: 0.25 }}>{new Date(item.timestamp).toLocaleString()}</Typography>
                        </Box>
                    ))}
                </Stack>
            </Paper>
        </Box>
    );
};

export default AdminConsolePage;
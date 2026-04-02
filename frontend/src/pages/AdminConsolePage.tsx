import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Avatar,
    Box,
    Button,
    Chip,
    Grid,
    IconButton,
    InputAdornment,
    LinearProgress,
    MenuItem,
    Paper,
    Stack,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    AdminPanelSettingsOutlined,
    ArrowBackOutlined,
    EditOutlined,
    GroupOutlined,
    ManageAccountsOutlined,
    PersonAddOutlined,
    SearchOutlined,
    TimelineOutlined,
} from '@mui/icons-material';

import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/api';

// --- Types ---

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

type AdminView = { type: 'list' } | { type: 'create' } | { type: 'edit'; userId: string };

// --- Constants ---

const featureLabels: Record<string, string> = {
    chat: 'Chat',
    analyze: 'Analyze',
    generate: 'Generate',
    opportunities: 'Opportunities',
    admin_console: 'Admin Console',
};

const orgRoles = ['owner', 'admin', 'member', 'viewer', 'developer', 'devops'];

const defaultNewUser = {
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

// --- Helpers ---

const AVATAR_COLORS = ['#1565C0', '#0D47A1', '#2E7D32', '#E65100', '#6A1B9A', '#00838F', '#AD1457', '#00695C'];

function avatarBg(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function nameInitials(name: string): string {
    return name.split(' ').map((p) => p.charAt(0).toUpperCase()).join('').slice(0, 2);
}

// --- Sub-components ---

const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <Typography sx={{ fontWeight: 700, fontSize: '0.74rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#94a3b8', mb: 2 }}>
        {children}
    </Typography>
);

interface PermissionToggleProps {
    label: string;
    checked: boolean;
    onChange: (v: boolean) => void;
}
const PermissionToggle: React.FC<PermissionToggleProps> = ({ label, checked, onChange }) => (
    <Paper
        elevation={0}
        onClick={() => onChange(!checked)}
        sx={{
            p: 1.4,
            borderRadius: 2,
            cursor: 'pointer',
            border: `1px solid ${checked ? 'rgba(21,101,192,0.35)' : 'rgba(15,23,42,0.1)'}`,
            bgcolor: checked ? 'rgba(21,101,192,0.05)' : 'transparent',
            transition: 'border-color 0.15s, background 0.15s',
            '&:hover': { borderColor: '#1565C0' },
        }}
    >
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography sx={{ fontSize: '0.84rem', fontWeight: 600, color: checked ? '#1565C0' : '#64748b' }}>{label}</Typography>
            <Switch
                size="small"
                checked={checked}
                onChange={(e) => { e.stopPropagation(); onChange(e.target.checked); }}
            />
        </Stack>
    </Paper>
);

// --- Main Component ---

const AdminConsolePage: React.FC = () => {
    const { user } = useAuth();
    const [summary, setSummary] = useState<AdminSummary | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);
    const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);

    const [view, setView] = useState<AdminView>({ type: 'list' });
    const [editDraft, setEditDraft] = useState<DemoUser | null>(null);
    const [newUser, setNewUser] = useState({ ...defaultNewUser });

    const [search, setSearch] = useState('');
    const [filterRole, setFilterRole] = useState('');
    const [filterDept, setFilterDept] = useState('');

    // Data loading

    const loadSummary = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await apiFetch('/api/demo/admin/summary');
            if (!res.ok) {
                const p = await res.json().catch(() => ({}));
                throw new Error(p?.detail || 'Failed to load admin summary');
            }
            setSummary(await res.json() as AdminSummary);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => { void loadSummary(); }, []);

    const totalUtilization = useMemo(() => {
        if (!summary?.totals.monthly_token_limit) return 0;
        return Math.round((summary.totals.monthly_token_used / summary.totals.monthly_token_limit) * 100);
    }, [summary]);

    const departments = useMemo(() =>
        Array.from(new Set((summary?.users ?? []).map((u) => u.department).filter(Boolean) as string[])).sort(),
        [summary]);

    const filteredUsers = useMemo(() => {
        const q = search.toLowerCase();
        return (summary?.users ?? []).filter((u) => {
            const matchSearch = !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || (u.department || '').toLowerCase().includes(q);
            return matchSearch && (!filterRole || u.org_role === filterRole) && (!filterDept || u.department === filterDept);
        });
    }, [summary, search, filterRole, filterDept]);

    // Navigation

    const openEdit = (userId: string) => {
        const found = summary?.users.find((u) => u.id === userId);
        if (!found) return;
        setEditDraft({ ...found });
        setError(null); setSaveMessage(null);
        setView({ type: 'edit', userId });
    };

    const openCreate = () => {
        setNewUser({ ...defaultNewUser });
        setError(null); setSaveMessage(null); setGeneratedPassword(null);
        setView({ type: 'create' });
    };

    const goBack = () => {
        setView({ type: 'list' });
        setEditDraft(null);
        setError(null); setSaveMessage(null); setGeneratedPassword(null);
    };

    // API actions

    const handleCreate = async () => {
        setError(null); setSaveMessage(null); setGeneratedPassword(null);
        try {
            const res = await apiFetch('/api/demo/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newUser),
            });
            const p = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(p?.detail || 'Failed to create user');
            setGeneratedPassword(p.generated_password || null);
            setSaveMessage(`User ${p.user?.email || ''} created successfully.`);
            setNewUser({ ...defaultNewUser });
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to create user');
        }
    };

    const handleSave = async () => {
        if (!editDraft || view.type !== 'edit') return;
        setError(null); setSaveMessage(null);
        try {
            const res = await apiFetch(`/api/demo/admin/users/${view.userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    full_name: editDraft.full_name,
                    department: editDraft.department,
                    title: editDraft.title,
                    org_role: editDraft.org_role,
                    is_admin: editDraft.is_admin,
                    is_active: editDraft.is_active,
                    monthly_token_limit: Number(editDraft.monthly_token_limit) || 0,
                    feature_access: editDraft.feature_access,
                }),
            });
            const p = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(p?.detail || 'Failed to update user');
            setSaveMessage(`Changes saved for ${p.user?.email || 'user'}.`);
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update user');
        }
    };

    // Guard

    if (!user?.is_admin) {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 900, mx: 'auto' }}>
                <Alert severity="error">This page is available only to admins.</Alert>
            </Box>
        );
    }

    // Edit view

    if (view.type === 'edit' && editDraft) {
        const usedPct = editDraft.monthly_token_limit
            ? Math.min(Math.round(((editDraft.usage?.monthly_token_used || 0) / editDraft.monthly_token_limit) * 100), 100)
            : 0;

        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 860, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={goBack} sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
                    Back to Users
                </Button>

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                    <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
                        <Avatar sx={{ width: 48, height: 48, fontWeight: 700, fontSize: '1.1rem', bgcolor: avatarBg(editDraft.full_name) }}>
                            {nameInitials(editDraft.full_name)}
                        </Avatar>
                        <Box>
                            <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a', lineHeight: 1.25 }}>{editDraft.full_name}</Typography>
                            <Typography sx={{ color: '#64748b', fontSize: '0.9rem' }}>{editDraft.email}</Typography>
                        </Box>
                    </Stack>
                    <Stack direction="row" spacing={1.5}>
                        <Button variant="outlined" onClick={goBack} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>
                            Cancel
                        </Button>
                        <Button variant="contained" onClick={() => void handleSave()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>
                            Save changes
                        </Button>
                    </Stack>
                </Stack>

                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}

                <Stack spacing={3}>
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Basic Information</SectionLabel>
                        <Grid container spacing={2}>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Full name" value={editDraft.full_name} onChange={(e) => setEditDraft((p) => p && ({ ...p, full_name: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth select label="Role" value={editDraft.org_role || 'member'} onChange={(e) => setEditDraft((p) => p && ({ ...p, org_role: e.target.value }))}>
                                    {orgRoles.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                                </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Department" value={editDraft.department || ''} onChange={(e) => setEditDraft((p) => p && ({ ...p, department: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Title" value={editDraft.title || ''} onChange={(e) => setEditDraft((p) => p && ({ ...p, title: e.target.value }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Token Budget</SectionLabel>
                        <Grid container spacing={3} sx={{ alignItems: 'center' }}>
                            <Grid item xs={12} sm={4}>
                                <TextField fullWidth type="number" label="Monthly limit" value={editDraft.monthly_token_limit} onChange={(e) => setEditDraft((p) => p && ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))} />
                            </Grid>
                            <Grid item xs={12} sm={8}>
                                <Stack spacing={0.75}>
                                    <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                                        <Typography sx={{ fontSize: '0.84rem', color: '#64748b' }}>
                                            {(editDraft.usage?.monthly_token_used || 0).toLocaleString()} of {(editDraft.monthly_token_limit || 0).toLocaleString()} used
                                        </Typography>
                                        <Typography sx={{ fontSize: '0.84rem', fontWeight: 700, color: usedPct > 80 ? '#C62828' : '#1565C0' }}>
                                            {usedPct}%
                                        </Typography>
                                    </Stack>
                                    <LinearProgress variant="determinate" value={usedPct} sx={{ height: 8, borderRadius: 4, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: usedPct > 80 ? '#C62828' : '#1565C0', borderRadius: 4 } }} />
                                    <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                                        Queries: {editDraft.usage?.queries_run || 0} · Analyze: {editDraft.usage?.analysis_runs || 0} · Generate: {editDraft.usage?.generate_runs || 0}
                                    </Typography>
                                </Stack>
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Status &amp; Permissions</SectionLabel>
                        <Grid container spacing={1.5}>
                            <Grid item xs={6} sm={4} md={3}>
                                <PermissionToggle label="Active" checked={editDraft.is_active} onChange={(v) => setEditDraft((p) => p && ({ ...p, is_active: v }))} />
                            </Grid>
                            <Grid item xs={6} sm={4} md={3}>
                                <PermissionToggle label="Admin access" checked={editDraft.is_admin} onChange={(v) => setEditDraft((p) => p && ({ ...p, is_admin: v, feature_access: { ...p.feature_access, admin_console: v } }))} />
                            </Grid>
                            {Object.entries(featureLabels).map(([feat, label]) => (
                                <Grid item xs={6} sm={4} md={3} key={feat}>
                                    <PermissionToggle
                                        label={label}
                                        checked={Boolean(editDraft.feature_access?.[feat])}
                                        onChange={(v) => setEditDraft((p) => p && ({ ...p, feature_access: { ...p.feature_access, [feat]: v } }))}
                                    />
                                </Grid>
                            ))}
                        </Grid>
                    </Paper>
                </Stack>
            </Box>
        );
    }

    // Create view

    if (view.type === 'create') {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 860, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={goBack} sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
                    Back to Users
                </Button>

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                    <Box>
                        <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>New User</Typography>
                        <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>Add a new team member to the organization.</Typography>
                    </Box>
                    <Stack direction="row" spacing={1.5}>
                        <Button variant="outlined" onClick={goBack} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>
                            Cancel
                        </Button>
                        <Button variant="contained" onClick={() => void handleCreate()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>
                            Create user
                        </Button>
                    </Stack>
                </Stack>

                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}
                {generatedPassword && (
                    <Alert severity="info" sx={{ mb: 3, borderRadius: 2 }}>
                        Temporary password: <strong>{generatedPassword}</strong> — share this with the new user.
                    </Alert>
                )}

                <Stack spacing={3}>
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Basic Information</SectionLabel>
                        <Grid container spacing={2}>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Full name" value={newUser.full_name} onChange={(e) => setNewUser((p) => ({ ...p, full_name: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Email" type="email" value={newUser.email} onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Password" type="password" value={newUser.password} onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))} helperText="Leave blank to auto-generate" />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth select label="Role" value={newUser.org_role} onChange={(e) => setNewUser((p) => ({ ...p, org_role: e.target.value }))}>
                                    {orgRoles.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                                </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Department" value={newUser.department} onChange={(e) => setNewUser((p) => ({ ...p, department: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Title" value={newUser.title} onChange={(e) => setNewUser((p) => ({ ...p, title: e.target.value }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Token Budget</SectionLabel>
                        <Grid container>
                            <Grid item xs={12} sm={5}>
                                <TextField fullWidth type="number" label="Monthly token limit" value={newUser.monthly_token_limit} onChange={(e) => setNewUser((p) => ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Status &amp; Permissions</SectionLabel>
                        <Grid container spacing={1.5}>
                            <Grid item xs={6} sm={4} md={3}>
                                <PermissionToggle label="Active" checked={newUser.is_active} onChange={(v) => setNewUser((p) => ({ ...p, is_active: v }))} />
                            </Grid>
                            <Grid item xs={6} sm={4} md={3}>
                                <PermissionToggle label="Admin access" checked={newUser.is_admin} onChange={(v) => setNewUser((p) => ({ ...p, is_admin: v, feature_access: { ...p.feature_access, admin_console: v } }))} />
                            </Grid>
                            {Object.entries(featureLabels).map(([feat, label]) => (
                                <Grid item xs={6} sm={4} md={3} key={feat}>
                                    <PermissionToggle
                                        label={label}
                                        checked={Boolean(newUser.feature_access[feat as keyof typeof newUser.feature_access])}
                                        onChange={(v) => setNewUser((p) => ({ ...p, feature_access: { ...p.feature_access, [feat]: v } }))}
                                    />
                                </Grid>
                            ))}
                        </Grid>
                    </Paper>
                </Stack>
            </Box>
        );
    }

    // List view

    return (
        <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1280, mx: 'auto' }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 3, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                <Box>
                    <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>Team Members</Typography>
                    <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>
                        {isLoading ? 'Loading...' : `${summary?.totals.user_count ?? 0} users · ${summary?.organization.name || 'Organization'}`}
                    </Typography>
                </Box>
                <Button variant="contained" startIcon={<PersonAddOutlined />} onClick={openCreate} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' }, px: 2.5, py: 1, flexShrink: 0 }}>
                    Add User
                </Button>
            </Stack>

            {error && <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>{error}</Alert>}
            {saveMessage && <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }}>{saveMessage}</Alert>}

            <Grid container spacing={2} sx={{ mb: 3 }}>
                {[
                    { icon: <GroupOutlined sx={{ fontSize: 18 }} />, label: 'Total users', value: summary?.totals.user_count ?? '-', sub: `${summary?.totals.active_user_count ?? '-'} active` },
                    { icon: <AdminPanelSettingsOutlined sx={{ fontSize: 18 }} />, label: 'Admins', value: summary?.totals.admin_count ?? '-', sub: 'With admin access' },
                    { icon: <TimelineOutlined sx={{ fontSize: 18 }} />, label: 'Org token usage', value: summary ? `${totalUtilization}%` : '-', sub: `${(summary?.totals.monthly_token_used || 0).toLocaleString()} used` },
                    { icon: <ManageAccountsOutlined sx={{ fontSize: 18 }} />, label: 'Organization', value: summary?.organization.name || '-', sub: 'Active tenant' },
                ].map((m) => (
                    <Grid item xs={6} md={3} key={m.label}>
                        <Paper elevation={0} sx={{ p: 2.2, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', height: '100%' }}>
                            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
                                <Box sx={{ color: '#1565C0' }}>{m.icon}</Box>
                                <Typography sx={{ fontWeight: 600, color: '#64748b', fontSize: '0.8rem' }}>{m.label}</Typography>
                            </Stack>
                            <Typography sx={{ fontWeight: 800, fontSize: '1.5rem', color: '#0f172a', lineHeight: 1.1 }}>{m.value}</Typography>
                            <Typography sx={{ color: '#94a3b8', fontSize: '0.76rem', mt: 0.4 }}>{m.sub}</Typography>
                        </Paper>
                    </Grid>
                ))}
            </Grid>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
                <TextField
                    size="small"
                    placeholder="Search by name, email, or department..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    InputProps={{ startAdornment: <InputAdornment position="start"><SearchOutlined sx={{ fontSize: 18, color: '#94a3b8' }} /></InputAdornment> }}
                    sx={{ flexGrow: 1, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
                />
                <TextField size="small" select label="Role" value={filterRole} onChange={(e) => setFilterRole(e.target.value)} sx={{ minWidth: 130, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
                    <MenuItem value="">All roles</MenuItem>
                    {orgRoles.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                </TextField>
                {departments.length > 0 && (
                    <TextField size="small" select label="Department" value={filterDept} onChange={(e) => setFilterDept(e.target.value)} sx={{ minWidth: 160, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}>
                        <MenuItem value="">All departments</MenuItem>
                        {departments.map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}
                    </TextField>
                )}
            </Stack>

            <Paper elevation={0} sx={{ borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', overflow: 'hidden', mb: 3 }}>
                {isLoading ? (
                    <Box sx={{ p: 6, textAlign: 'center' }}>
                        <Typography sx={{ color: '#64748b' }}>Loading users...</Typography>
                    </Box>
                ) : filteredUsers.length === 0 ? (
                    <Box sx={{ p: 6, textAlign: 'center' }}>
                        <Typography sx={{ color: '#64748b' }}>No users match the current filters.</Typography>
                    </Box>
                ) : (
                    <TableContainer>
                        <Table>
                            <TableHead>
                                <TableRow sx={{ bgcolor: '#f8fafc' }}>
                                    {['User', 'Department', 'Role', 'Status', 'Token usage', ''].map((h, idx) => (
                                        <TableCell key={idx} sx={{ fontWeight: 700, color: '#94a3b8', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid rgba(15,23,42,0.08)', py: 1.5, ...(h === '' ? { width: 52 } : {}), ...(h === 'Token usage' ? { minWidth: 160 } : {}) }}>
                                            {h}
                                        </TableCell>
                                    ))}
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {filteredUsers.map((u) => {
                                    const usedPct = u.monthly_token_limit
                                        ? Math.min(Math.round(((u.usage?.monthly_token_used || 0) / u.monthly_token_limit) * 100), 100)
                                        : 0;
                                    return (
                                        <TableRow
                                            key={u.id}
                                            hover
                                            onClick={() => openEdit(u.id)}
                                            sx={{ cursor: 'pointer', '&:last-child td': { border: 0 }, '& td': { borderBottom: '1px solid rgba(15,23,42,0.06)' }, '&:hover': { bgcolor: 'rgba(21,101,192,0.025)' } }}
                                        >
                                            <TableCell>
                                                <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                                                    <Avatar sx={{ width: 36, height: 36, fontSize: '0.8rem', fontWeight: 700, bgcolor: avatarBg(u.full_name), flexShrink: 0 }}>
                                                        {nameInitials(u.full_name)}
                                                    </Avatar>
                                                    <Box>
                                                        <Typography sx={{ fontWeight: 700, color: '#0f172a', fontSize: '0.9rem' }}>{u.full_name}</Typography>
                                                        <Typography sx={{ color: '#64748b', fontSize: '0.78rem' }}>{u.email}</Typography>
                                                    </Box>
                                                </Stack>
                                            </TableCell>
                                            <TableCell>
                                                <Typography sx={{ color: '#334155', fontSize: '0.88rem' }}>{u.department || '-'}</Typography>
                                                {u.title && <Typography sx={{ color: '#94a3b8', fontSize: '0.76rem' }}>{u.title}</Typography>}
                                            </TableCell>
                                            <TableCell>
                                                <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: '4px' }}>
                                                    <Chip size="small" label={u.org_role || 'member'} sx={{ bgcolor: 'rgba(21,101,192,0.08)', color: '#1565C0', fontWeight: 700, fontSize: '0.74rem' }} />
                                                    {u.is_admin && <Chip size="small" label="Admin" sx={{ bgcolor: 'rgba(13,71,161,0.1)', color: '#0D47A1', fontWeight: 700, fontSize: '0.74rem' }} />}
                                                </Stack>
                                            </TableCell>
                                            <TableCell>
                                                <Chip size="small" label={u.is_active ? 'Active' : 'Inactive'} sx={{ bgcolor: u.is_active ? 'rgba(46,125,50,0.1)' : 'rgba(100,116,139,0.1)', color: u.is_active ? '#2E7D32' : '#64748b', fontWeight: 700, fontSize: '0.74rem' }} />
                                            </TableCell>
                                            <TableCell>
                                                <Stack spacing={0.5}>
                                                    <LinearProgress variant="determinate" value={usedPct} sx={{ height: 6, borderRadius: 3, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: usedPct > 80 ? '#C62828' : '#1565C0', borderRadius: 3 } }} />
                                                    <Typography sx={{ color: '#94a3b8', fontSize: '0.72rem' }}>{usedPct}% of {(u.monthly_token_limit || 0).toLocaleString()}</Typography>
                                                </Stack>
                                            </TableCell>
                                            <TableCell>
                                                <Tooltip title="Edit user">
                                                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); openEdit(u.id); }} sx={{ color: '#94a3b8', '&:hover': { color: '#1565C0', bgcolor: 'rgba(21,101,192,0.08)' } }}>
                                                        <EditOutlined sx={{ fontSize: 17 }} />
                                                    </IconButton>
                                                </Tooltip>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}
            </Paper>

            {(summary?.recent_activity ?? []).length > 0 && (
                <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                    <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 2 }}>Recent Activity</Typography>
                    <Stack spacing={0.25}>
                        {(summary?.recent_activity ?? []).slice(0, 6).map((item, i) => (
                            <Stack key={`${item.timestamp}-${i}`} direction="row" spacing={2} sx={{ alignItems: 'flex-start', p: 1.2, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.03)' } }}>
                                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: '#1565C0', mt: 0.8, flexShrink: 0 }} />
                                <Box>
                                    <Typography sx={{ fontWeight: 600, color: '#334155', fontSize: '0.87rem' }}>{item.action}</Typography>
                                    <Typography sx={{ color: '#94a3b8', fontSize: '0.75rem' }}>{new Date(item.timestamp).toLocaleString()}</Typography>
                                </Box>
                            </Stack>
                        ))}
                    </Stack>
                </Paper>
            )}
        </Box>
    );
};

export default AdminConsolePage;

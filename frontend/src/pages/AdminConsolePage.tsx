import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Avatar,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    Grid,
    IconButton,
    InputAdornment,
    LinearProgress,
    MenuItem,
    Paper,
    Stack,
    Switch,
    Tab,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Tabs,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    AddBusinessOutlined,
    AdminPanelSettingsOutlined,
    ArrowBackOutlined,
    BusinessOutlined,
    DeleteOutlined,
    EditOutlined,
    GroupOutlined,
    InfoOutlined,
    PersonAddOutlined,
    SearchOutlined,
    TimelineOutlined,
    TokenOutlined,
    WarningAmberOutlined,
} from '@mui/icons-material';

import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Department {
    id: string;
    name: string;
    description?: string | null;
    monthly_token_limit: number;
    usage?: {
        user_count: number;
        active_user_count: number;
        total_token_used: number;
        total_user_token_limit: number;
    };
}

interface DemoUser {
    id: string;
    email: string;
    full_name: string;
    department?: string | null;
    department_id?: string | null;
    title?: string | null;
    org_role?: string | null;
    is_admin: boolean;
    is_active: boolean;
    monthly_token_limit: number;
    effective_monthly_token_limit?: number;
    token_topup_tokens?: number;
    token_limit_override?: boolean;
    feature_access: Record<string, boolean>;
    usage?: {
        monthly_token_used?: number;
        queries_run?: number;
        analysis_runs?: number;
        generate_runs?: number;
    };
}

interface AdminSummary {
    organization: {
        name?: string;
        monthly_token_budget?: number;
    };
    totals: {
        user_count: number;
        active_user_count: number;
        admin_count: number;
        department_count: number;
        org_monthly_token_budget: number;
        total_dept_allocated: number;
        unallocated_budget: number;
        monthly_token_limit: number;
        monthly_token_used: number;
        monthly_token_remaining: number;
    };
    feature_access_counts: Record<string, number>;
    users: DemoUser[];
    departments: Department[];
}

type MainTab = 'overview' | 'users' | 'departments';
type AdminView = { type: 'list' } | { type: 'create' } | { type: 'edit'; userId: string } | { type: 'dept-create' } | { type: 'dept-edit'; deptId: string };

// ─── Constants ────────────────────────────────────────────────────────────────

const featureLabels: Record<string, string> = {
    chat: 'Chat',
    analyze: 'Analyze',
    generate: 'Generate',
    opportunities: 'Opportunities',
    cur_analysis: 'CUR Analysis',
    admin_console: 'Admin Console',
};

const orgRoles = ['owner', 'admin', 'member', 'viewer', 'developer', 'devops'];

const defaultNewUser = {
    email: '',
    full_name: '',
    password: '',
    department_id: '',
    title: '',
    org_role: 'member',
    monthly_token_limit: 250000,
    token_topup_tokens: 0,
    token_limit_override: false,
    is_admin: false,
    is_active: true,
    feature_access: {
        chat: true,
        analyze: true,
        generate: false,
        opportunities: true,
        cur_analysis: false,
        admin_console: false,
    },
};

const defaultNewDept = {
    name: '',
    description: '',
    monthly_token_limit: 0,
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

const AVATAR_COLORS = ['#1565C0', '#0D47A1', '#2E7D32', '#E65100', '#6A1B9A', '#00838F', '#AD1457', '#00695C'];

function avatarBg(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function nameInitials(name: string): string {
    return name.split(' ').map((p) => p.charAt(0).toUpperCase()).join('').slice(0, 2);
}

function fmtNum(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return n.toLocaleString();
}

// ─── Sub-components ───────────────────────────────────────────────────────────

const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <Typography sx={{ fontWeight: 700, fontSize: '0.74rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: '#94a3b8', mb: 2 }}>
        {children}
    </Typography>
);

interface PermissionToggleProps { label: string; checked: boolean; onChange: (v: boolean) => void; }
const PermissionToggle: React.FC<PermissionToggleProps> = ({ label, checked, onChange }) => (
    <Paper
        elevation={0}
        onClick={() => onChange(!checked)}
        sx={{
            p: 1.4, borderRadius: 2, cursor: 'pointer',
            border: `1px solid ${checked ? 'rgba(21,101,192,0.35)' : 'rgba(15,23,42,0.1)'}`,
            bgcolor: checked ? 'rgba(21,101,192,0.05)' : 'transparent',
            transition: 'border-color 0.15s, background 0.15s',
            '&:hover': { borderColor: '#1565C0' },
        }}
    >
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography sx={{ fontSize: '0.84rem', fontWeight: 600, color: checked ? '#1565C0' : '#64748b' }}>{label}</Typography>
            <Switch size="small" checked={checked} onChange={(e) => { e.stopPropagation(); onChange(e.target.checked); }} />
        </Stack>
    </Paper>
);

interface StatCardProps { icon: React.ReactNode; label: string; value: React.ReactNode; sub?: React.ReactNode; }
const StatCard: React.FC<StatCardProps> = ({ icon, label, value, sub }) => (
    <Paper elevation={0} sx={{ p: 2.5, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', height: '100%' }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1.2 }}>
            <Box sx={{ color: '#1565C0' }}>{icon}</Box>
            <Typography sx={{ fontWeight: 600, color: '#64748b', fontSize: '0.8rem' }}>{label}</Typography>
        </Stack>
        <Typography sx={{ fontWeight: 800, fontSize: '1.5rem', color: '#0f172a', lineHeight: 1.1 }}>{value}</Typography>
        {sub && <Typography sx={{ color: '#94a3b8', fontSize: '0.76rem', mt: 0.4 }}>{sub}</Typography>}
    </Paper>
);

// ─── Main Component ───────────────────────────────────────────────────────────

const AdminConsolePage: React.FC = () => {
    const { user } = useAuth();

    // ── State ──
    const [summary, setSummary] = useState<AdminSummary | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);
    const [generatedPassword, setGeneratedPassword] = useState<string | null>(null);

    const [activeTab, setActiveTab] = useState<MainTab>('overview');
    const [view, setView] = useState<AdminView>({ type: 'list' });

    // User edit/create state
    const [editDraft, setEditDraft] = useState<DemoUser | null>(null);
    const [newUser, setNewUser] = useState({ ...defaultNewUser });

    // Department edit/create state
    const [deptDraft, setDeptDraft] = useState<Department | null>(null);
    const [newDept, setNewDept] = useState({ ...defaultNewDept });

    // Org budget edit state
    const [orgBudgetEdit, setOrgBudgetEdit] = useState<number | null>(null);
    const [orgBudgetSaving, setOrgBudgetSaving] = useState(false);
    const [orgBudgetMsg, setOrgBudgetMsg] = useState<string | null>(null);

    // Dept delete confirm
    const [deptDeleteConfirm, setDeptDeleteConfirm] = useState<Department | null>(null);

    // User list filters
    const [search, setSearch] = useState('');
    const [filterRole, setFilterRole] = useState('');
    const [filterDept, setFilterDept] = useState('');

    // ── Data loading ──
    const loadSummary = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const res = await apiFetch('/api/demo/admin/summary');
            if (!res.ok) {
                const p = await res.json().catch(() => ({})) as { detail?: string };
                throw new Error(p?.detail || 'Failed to load admin summary');
            }
            const data = await res.json() as AdminSummary;
            setSummary(data);
            if (orgBudgetEdit === null && data.totals.org_monthly_token_budget) {
                setOrgBudgetEdit(data.totals.org_monthly_token_budget);
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => { void loadSummary(); }, []);

    // ── Derived ──
    const departments = summary?.departments ?? [];

    const filteredUsers = useMemo(() => {
        const q = search.toLowerCase();
        return (summary?.users ?? []).filter((u) => {
            const matchSearch = !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || (u.department || '').toLowerCase().includes(q);
            return matchSearch && (!filterRole || u.org_role === filterRole) && (!filterDept || u.department_id === filterDept);
        });
    }, [summary, search, filterRole, filterDept]);

    const orgBudget = summary?.totals.org_monthly_token_budget ?? 0;
    const orgUsed = summary?.totals.monthly_token_used ?? 0;
    const orgDeptAllocated = summary?.totals.total_dept_allocated ?? 0;
    const orgUnallocated = summary?.totals.unallocated_budget ?? 0;
    const orgUtilPct = orgBudget ? Math.min(Math.round((orgUsed / orgBudget) * 100), 100) : 0;

    // ── Navigation helpers ──
    const clearMessages = () => { setError(null); setSaveMessage(null); setGeneratedPassword(null); };

    const openEdit = (userId: string) => {
        const found = summary?.users.find((u) => u.id === userId);
        if (!found) return;
        setEditDraft({ ...found });
        clearMessages();
        setView({ type: 'edit', userId });
        setActiveTab('users');
    };

    const openCreate = () => {
        setNewUser({ ...defaultNewUser });
        clearMessages();
        setView({ type: 'create' });
        setActiveTab('users');
    };

    const openDeptEdit = (deptId: string) => {
        const found = departments.find((d) => d.id === deptId);
        if (!found) return;
        setDeptDraft({ ...found });
        clearMessages();
        setView({ type: 'dept-edit', deptId });
        setActiveTab('departments');
    };

    const openDeptCreate = () => {
        setNewDept({ ...defaultNewDept });
        clearMessages();
        setView({ type: 'dept-create' });
        setActiveTab('departments');
    };

    const goBack = (tab?: MainTab) => {
        setView({ type: 'list' });
        setEditDraft(null);
        setDeptDraft(null);
        clearMessages();
        if (tab) setActiveTab(tab);
    };

    // ── API actions ──

    const passwordError = newUser.password.length > 0 && newUser.password.length < 8
        ? 'Password must be at least 8 characters (or leave blank to auto-generate)'
        : null;

    const handleCreate = async () => {
        if (passwordError) return;
        clearMessages();
        try {
            const res = await apiFetch('/api/demo/admin/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...newUser,
                    // Send null for optional fields instead of empty strings to pass backend validation
                    password: newUser.password || null,
                    department_id: newUser.department_id || null,
                    title: newUser.title || null,
                }),
            });
            const p = await res.json().catch(() => ({})) as { detail?: unknown; user?: DemoUser; generated_password?: string };
            if (!res.ok) {
                const detail = p?.detail;
                const msg = Array.isArray(detail)
                    ? detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join('; ')
                    : typeof detail === 'string' ? detail : 'Failed to create user';
                throw new Error(msg);
            }
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
        clearMessages();
        try {
            const res = await apiFetch(`/api/demo/admin/users/${view.userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    full_name: editDraft.full_name,
                    department_id: editDraft.department_id || null,
                    title: editDraft.title,
                    org_role: editDraft.org_role,
                    is_admin: editDraft.is_admin,
                    is_active: editDraft.is_active,
                    monthly_token_limit: Number(editDraft.monthly_token_limit) || 0,
                    token_topup_tokens: Math.max(Number(editDraft.token_topup_tokens) || 0, 0),
                    token_limit_override: (Number(editDraft.token_topup_tokens) || 0) > 0,
                    feature_access: editDraft.feature_access,
                }),
            });
            const p = await res.json().catch(() => ({})) as { detail?: string; user?: DemoUser };
            if (!res.ok) throw new Error(p?.detail || 'Failed to update user');
            setSaveMessage(`Changes saved for ${p.user?.email || 'user'}.`);
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update user');
        }
    };

    const handleDeptCreate = async () => {
        clearMessages();
        try {
            const res = await apiFetch('/api/demo/admin/departments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newDept),
            });
            const p = await res.json().catch(() => ({})) as { detail?: string; department?: Department };
            if (!res.ok) throw new Error(p?.detail || 'Failed to create department');
            setSaveMessage(`Department "${p.department?.name || ''}" created.`);
            setNewDept({ ...defaultNewDept });
            await loadSummary();
            goBack('departments');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to create department');
        }
    };

    const handleDeptSave = async () => {
        if (!deptDraft || view.type !== 'dept-edit') return;
        clearMessages();
        try {
            const res = await apiFetch(`/api/demo/admin/departments/${view.deptId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: deptDraft.name,
                    description: deptDraft.description || null,
                    monthly_token_limit: Number(deptDraft.monthly_token_limit) || 0,
                }),
            });
            const p = await res.json().catch(() => ({})) as { detail?: string; department?: Department };
            if (!res.ok) throw new Error(p?.detail || 'Failed to update department');
            setSaveMessage(`Department "${p.department?.name || ''}" updated.`);
            await loadSummary();
            goBack('departments');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to update department');
        }
    };

    const handleDeptDelete = async (dept: Department) => {
        setDeptDeleteConfirm(null);
        clearMessages();
        try {
            const res = await apiFetch(`/api/demo/admin/departments/${dept.id}`, { method: 'DELETE' });
            const p = await res.json().catch(() => ({})) as { detail?: string };
            if (!res.ok) throw new Error(p?.detail || 'Failed to delete department');
            setSaveMessage(`Department "${dept.name}" deleted.`);
            await loadSummary();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to delete department');
        }
    };

    const handleOrgBudgetSave = async () => {
        if (orgBudgetEdit === null) return;
        setOrgBudgetSaving(true);
        setOrgBudgetMsg(null);
        try {
            const res = await apiFetch('/api/demo/admin/org-settings', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ monthly_token_budget: orgBudgetEdit }),
            });
            const p = await res.json().catch(() => ({})) as { detail?: string };
            if (!res.ok) throw new Error(p?.detail || 'Failed to update org budget');
            setOrgBudgetMsg('Org budget updated.');
            await loadSummary();
        } catch (err) {
            setOrgBudgetMsg(err instanceof Error ? err.message : 'Failed to update');
        } finally {
            setOrgBudgetSaving(false);
        }
    };

    // ── Guard ──
    if (!user?.is_admin) {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 900, mx: 'auto' }}>
                <Alert severity="error">This page is available only to admins.</Alert>
            </Box>
        );
    }

    // ══════════════════════════════════════════════════════════════════════════
    // EDIT USER VIEW
    // ══════════════════════════════════════════════════════════════════════════
    if (view.type === 'edit' && editDraft) {
        const topup = Math.max(Number(editDraft.token_topup_tokens) || 0, 0);
        const baseLimit = editDraft.department_id
            ? (departments.find((d) => d.id === editDraft.department_id)?.monthly_token_limit ?? 0)
            : (Number(editDraft.monthly_token_limit) || 0);
        const effectiveLimit = baseLimit + topup;
        const usedPct = effectiveLimit
            ? Math.min(Math.round(((editDraft.usage?.monthly_token_used || 0) / effectiveLimit) * 100), 100)
            : 0;
        const userDept = departments.find((d) => d.id === editDraft.department_id);
        const deptLimit = userDept?.monthly_token_limit ?? 0;

        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 860, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={() => goBack('users')}
                    sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
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
                        <Button variant="outlined" onClick={() => goBack('users')} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>Cancel</Button>
                        <Button variant="contained" onClick={() => void handleSave()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>Save changes</Button>
                    </Stack>
                </Stack>

                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}

                <Stack spacing={3}>
                    {/* Basic Info */}
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
                                <TextField fullWidth select label="Department" value={editDraft.department_id || ''} onChange={(e) => {
                                    const dId = e.target.value;
                                    const dName = departments.find((d) => d.id === dId)?.name || null;
                                    setEditDraft((p) => p && ({ ...p, department_id: dId || null, department: dName, token_topup_tokens: Math.max(Number(p.token_topup_tokens) || 0, 0) }));
                                }}>
                                    <MenuItem value=""><em>— No department —</em></MenuItem>
                                    {departments.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
                                </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Title" value={editDraft.title || ''} onChange={(e) => setEditDraft((p) => p && ({ ...p, title: e.target.value }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    {/* Token Budget */}
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Token Budget</SectionLabel>

                        {editDraft.department_id && deptLimit > 0 && (
                            <Alert severity="info" icon={<InfoOutlined fontSize="small" />} sx={{ mb: 2, borderRadius: 2, fontSize: '0.82rem' }}>
                                Base monthly limit is inherited from <strong>{userDept?.name}</strong>: {fmtNum(deptLimit)} tokens/month.
                                Use one-time top-up tokens for temporary extra capacity.
                            </Alert>
                        )}

                        <Grid container spacing={3} sx={{ alignItems: 'center' }}>
                            <Grid item xs={12} sm={4}>
                                <TextField
                                    fullWidth type="number" label={editDraft.department_id ? 'Inherited monthly limit' : 'Monthly limit'}
                                    value={editDraft.monthly_token_limit}
                                    disabled={Boolean(editDraft.department_id)}
                                    onChange={(e) => setEditDraft((p) => p && ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))}
                                />
                            </Grid>
                            <Grid item xs={12} sm={4}>
                                <TextField
                                    fullWidth
                                    type="number"
                                    label="One-time top-up tokens"
                                    value={topup}
                                    onChange={(e) => setEditDraft((p) => p && ({ ...p, token_topup_tokens: Math.max(Number(e.target.value) || 0, 0) }))}
                                    helperText="Adds temporary extra tokens on top of the base monthly limit"
                                />
                            </Grid>
                            <Grid item xs={12} sm={12}>
                                <Stack spacing={0.75}>
                                    <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                                        <Typography sx={{ fontSize: '0.84rem', color: '#64748b' }}>
                                            {fmtNum(editDraft.usage?.monthly_token_used || 0)} of {fmtNum(effectiveLimit)} used
                                        </Typography>
                                        <Typography sx={{ fontSize: '0.84rem', fontWeight: 700, color: usedPct > 80 ? '#C62828' : '#1565C0' }}>{usedPct}%</Typography>
                                    </Stack>
                                    <LinearProgress variant="determinate" value={usedPct} sx={{ height: 8, borderRadius: 4, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: usedPct > 80 ? '#C62828' : '#1565C0', borderRadius: 4 } }} />
                                    <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                                        Base: {fmtNum(baseLimit)} · Top-up: {fmtNum(topup)} · Effective: {fmtNum(effectiveLimit)}
                                    </Typography>
                                    <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                                        Queries: {editDraft.usage?.queries_run || 0} · Analyze: {editDraft.usage?.analysis_runs || 0} · Generate: {editDraft.usage?.generate_runs || 0}
                                    </Typography>
                                </Stack>
                            </Grid>
                        </Grid>
                    </Paper>

                    {/* Status & Permissions */}
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

    // ══════════════════════════════════════════════════════════════════════════
    // CREATE USER VIEW
    // ══════════════════════════════════════════════════════════════════════════
    if (view.type === 'create') {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 860, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={() => goBack('users')}
                    sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
                    Back to Users
                </Button>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                    <Box>
                        <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>New User</Typography>
                        <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>Add a new team member to the organization.</Typography>
                    </Box>
                    <Stack direction="row" spacing={1.5}>
                        <Button variant="outlined" onClick={() => goBack('users')} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>Cancel</Button>
                        <Button variant="contained" onClick={() => void handleCreate()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>Create user</Button>
                    </Stack>
                </Stack>

                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}
                {generatedPassword && (
                    <Alert severity="info" sx={{ mb: 3, borderRadius: 2 }}>
                        Temporary password: <strong>{generatedPassword}</strong> — share this with the new user securely.
                    </Alert>
                )}

                <Stack spacing={3}>
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Basic Information</SectionLabel>
                        <Grid container spacing={2}>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Full name *" value={newUser.full_name} onChange={(e) => setNewUser((p) => ({ ...p, full_name: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Email *" type="email" value={newUser.email} onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField
                                    fullWidth
                                    label="Password"
                                    type="password"
                                    value={newUser.password}
                                    onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))}
                                    error={!!passwordError}
                                    helperText={passwordError ?? 'Leave blank to auto-generate'}
                                />
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth select label="Role" value={newUser.org_role} onChange={(e) => setNewUser((p) => ({ ...p, org_role: e.target.value }))}>
                                    {orgRoles.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
                                </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth select label="Department *" value={newUser.department_id} onChange={(e) => {
                                    const deptId = e.target.value;
                                    const dept = departments.find((d) => d.id === deptId);
                                    const autoLimit = dept && dept.monthly_token_limit > 0
                                        ? Math.floor(dept.monthly_token_limit * 0.5)
                                        : defaultNewUser.monthly_token_limit;
                                    setNewUser((p) => ({ ...p, department_id: deptId, monthly_token_limit: autoLimit }));
                                }}>
                                    <MenuItem value=""><em>— Select a department —</em></MenuItem>
                                    {departments.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
                                </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                                <TextField fullWidth label="Title" value={newUser.title} onChange={(e) => setNewUser((p) => ({ ...p, title: e.target.value }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Token Budget</SectionLabel>
                        {newUser.department_id && (
                            <Alert severity="info" icon={<InfoOutlined fontSize="small" />} sx={{ mb: 2, borderRadius: 2, fontSize: '0.82rem' }}>
                                Department limit: <strong>{fmtNum(departments.find((d) => d.id === newUser.department_id)?.monthly_token_limit ?? 0)}</strong> tokens/month.
                                Optional one-time top-up tokens can be added for temporary extra capacity.
                            </Alert>
                        )}
                        <Grid container spacing={2}>
                            <Grid item xs={12} sm={5}>
                                <TextField fullWidth type="number" label="Monthly token limit" value={newUser.monthly_token_limit} onChange={(e) => setNewUser((p) => ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))} />
                            </Grid>
                            <Grid item xs={12} sm={5}>
                                <TextField
                                    fullWidth
                                    type="number"
                                    label="One-time top-up tokens"
                                    value={newUser.token_topup_tokens}
                                    onChange={(e) => setNewUser((p) => ({ ...p, token_topup_tokens: Math.max(Number(e.target.value) || 0, 0) }))}
                                />
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

    // ══════════════════════════════════════════════════════════════════════════
    // CREATE DEPARTMENT VIEW
    // ══════════════════════════════════════════════════════════════════════════
    if (view.type === 'dept-create') {
        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 720, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={() => goBack('departments')}
                    sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
                    Back to Departments
                </Button>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                    <Box>
                        <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>New Department</Typography>
                        <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>Create a new department and set its monthly token quota.</Typography>
                    </Box>
                    <Stack direction="row" spacing={1.5}>
                        <Button variant="outlined" onClick={() => goBack('departments')} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>Cancel</Button>
                        <Button variant="contained" onClick={() => void handleDeptCreate()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>Create</Button>
                    </Stack>
                </Stack>
                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                    <Grid container spacing={2}>
                        <Grid item xs={12}>
                            <TextField fullWidth label="Department name *" value={newDept.name} onChange={(e) => setNewDept((p) => ({ ...p, name: e.target.value }))} />
                        </Grid>
                        <Grid item xs={12}>
                            <TextField fullWidth label="Description" multiline rows={2} value={newDept.description} onChange={(e) => setNewDept((p) => ({ ...p, description: e.target.value }))} />
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <TextField fullWidth type="number" label="Monthly token limit" helperText="0 = unlimited" value={newDept.monthly_token_limit} onChange={(e) => setNewDept((p) => ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))} />
                        </Grid>
                    </Grid>
                </Paper>
            </Box>
        );
    }

    // ══════════════════════════════════════════════════════════════════════════
    // EDIT DEPARTMENT VIEW
    // ══════════════════════════════════════════════════════════════════════════
    if (view.type === 'dept-edit' && deptDraft) {
        const deptUsed = deptDraft.usage?.total_token_used ?? 0;
        const deptLimit = deptDraft.monthly_token_limit;
        const deptPct = deptLimit ? Math.min(Math.round((deptUsed / deptLimit) * 100), 100) : 0;

        return (
            <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 720, mx: 'auto' }}>
                <Button startIcon={<ArrowBackOutlined />} onClick={() => goBack('departments')}
                    sx={{ mb: 3, textTransform: 'none', color: '#64748b', fontWeight: 600, borderRadius: 2, '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' } }}>
                    Back to Departments
                </Button>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                    <Box>
                        <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>{deptDraft.name}</Typography>
                        <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>{deptDraft.usage?.user_count ?? 0} members</Typography>
                    </Box>
                    <Stack direction="row" spacing={1.5}>
                        <Button variant="outlined" onClick={() => goBack('departments')} sx={{ textTransform: 'none', fontWeight: 600, borderRadius: 2, borderColor: 'rgba(15,23,42,0.18)', color: '#334155' }}>Cancel</Button>
                        <Button variant="contained" onClick={() => void handleDeptSave()} sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>Save changes</Button>
                    </Stack>
                </Stack>
                {error && <Alert severity="error" sx={{ mb: 3, borderRadius: 2 }}>{error}</Alert>}
                {saveMessage && <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>{saveMessage}</Alert>}

                <Stack spacing={3}>
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Department Details</SectionLabel>
                        <Grid container spacing={2}>
                            <Grid item xs={12}>
                                <TextField fullWidth label="Department name *" value={deptDraft.name} onChange={(e) => setDeptDraft((p) => p && ({ ...p, name: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12}>
                                <TextField fullWidth label="Description" multiline rows={2} value={deptDraft.description || ''} onChange={(e) => setDeptDraft((p) => p && ({ ...p, description: e.target.value }))} />
                            </Grid>
                            <Grid item xs={12} sm={6}>
                                <TextField fullWidth type="number" label="Monthly token limit" helperText="0 = unlimited" value={deptDraft.monthly_token_limit} onChange={(e) => setDeptDraft((p) => p && ({ ...p, monthly_token_limit: Number(e.target.value) || 0 }))} />
                            </Grid>
                        </Grid>
                    </Paper>

                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                        <SectionLabel>Token Usage</SectionLabel>
                        <Stack spacing={1}>
                            <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                                <Typography sx={{ fontSize: '0.86rem', color: '#64748b' }}>
                                    {fmtNum(deptUsed)} of {deptLimit ? fmtNum(deptLimit) : '∞'} used
                                </Typography>
                                {deptLimit > 0 && (
                                    <Typography sx={{ fontSize: '0.86rem', fontWeight: 700, color: deptPct > 80 ? '#C62828' : '#1565C0' }}>{deptPct}%</Typography>
                                )}
                            </Stack>
                            {deptLimit > 0 && (
                                <LinearProgress variant="determinate" value={deptPct} sx={{ height: 8, borderRadius: 4, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: deptPct > 80 ? '#C62828' : '#1565C0', borderRadius: 4 } }} />
                            )}
                            <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                                {deptDraft.usage?.user_count ?? 0} total · {deptDraft.usage?.active_user_count ?? 0} active members
                            </Typography>
                        </Stack>
                    </Paper>
                </Stack>
            </Box>
        );
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MAIN TAB VIEW (Overview / Users / Departments)
    // ══════════════════════════════════════════════════════════════════════════
    return (
        <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1280, mx: 'auto' }}>

            {/* Page header */}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 3, justifyContent: 'space-between', alignItems: { sm: 'center' } }}>
                <Box>
                    <Typography variant="h5" sx={{ fontWeight: 800, color: '#0f172a' }}>Admin Console</Typography>
                    <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mt: 0.25 }}>
                        {isLoading ? 'Loading…' : `${summary?.organization?.name || 'Organization'} · ${summary?.totals.user_count ?? 0} users · ${departments.length} departments`}
                    </Typography>
                </Box>
                <Stack direction="row" spacing={1.5}>
                    {activeTab === 'departments' && (
                        <Button variant="outlined" startIcon={<AddBusinessOutlined />} onClick={openDeptCreate}
                            sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, borderColor: '#1565C0', color: '#1565C0', '&:hover': { bgcolor: 'rgba(21,101,192,0.06)' } }}>
                            New Department
                        </Button>
                    )}
                    <Button variant="contained" startIcon={<PersonAddOutlined />} onClick={openCreate}
                        sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' }, px: 2.5, py: 1 }}>
                        Add User
                    </Button>
                </Stack>
            </Stack>

            {error && <Alert severity="error" sx={{ mb: 2, borderRadius: 2 }}>{error}</Alert>}
            {saveMessage && <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }}>{saveMessage}</Alert>}
            {isLoading && <LinearProgress sx={{ mb: 2, borderRadius: 1 }} />}

            {/* Tabs */}
            <Box sx={{ mb: 3, borderBottom: '1px solid rgba(15,23,42,0.1)' }}>
                <Tabs value={activeTab} onChange={(_, v) => { setActiveTab(v as MainTab); setView({ type: 'list' }); clearMessages(); }}
                    sx={{ '& .MuiTab-root': { textTransform: 'none', fontWeight: 600, minWidth: 0, px: 2 }, '& .Mui-selected': { color: '#1565C0' }, '& .MuiTabs-indicator': { bgcolor: '#1565C0' } }}>
                    <Tab value="overview" icon={<TimelineOutlined sx={{ fontSize: 17 }} />} iconPosition="start" label="Overview" />
                    <Tab value="users" icon={<GroupOutlined sx={{ fontSize: 17 }} />} iconPosition="start" label="Users" />
                    <Tab value="departments" icon={<BusinessOutlined sx={{ fontSize: 17 }} />} iconPosition="start" label="Departments" />
                </Tabs>
            </Box>

            {/* ── OVERVIEW TAB ── */}
            {activeTab === 'overview' && (
                <Stack spacing={3}>
                    {/* Org token budget card */}
                    <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(21,101,192,0.18)', bgcolor: 'rgba(21,101,192,0.02)' }}>
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' }, justifyContent: 'space-between', mb: 2.5 }}>
                            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                                <Box sx={{ p: 1, bgcolor: '#1565C0', borderRadius: 2, display: 'flex' }}>
                                    <TokenOutlined sx={{ fontSize: 20, color: '#fff' }} />
                                </Box>
                                <Box>
                                    <Typography sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.05rem' }}>Organization Monthly Token Budget</Typography>
                                    <Typography sx={{ color: '#64748b', fontSize: '0.82rem' }}>Admin-controlled org-wide token quota. All dept &amp; user limits are governed by this cap.</Typography>
                                </Box>
                            </Stack>
                            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexShrink: 0 }}>
                                <TextField
                                    size="small" type="number" label="Monthly budget"
                                    value={orgBudgetEdit ?? orgBudget}
                                    onChange={(e) => setOrgBudgetEdit(Number(e.target.value) || 0)}
                                    sx={{ width: 180, '& .MuiOutlinedInput-root': { borderRadius: 2 } }}
                                    InputProps={{ inputProps: { min: 0 } }}
                                />
                                <Button variant="contained" size="small" onClick={() => void handleOrgBudgetSave()} disabled={orgBudgetSaving}
                                    sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' }, whiteSpace: 'nowrap' }}>
                                    {orgBudgetSaving ? <CircularProgress size={16} sx={{ color: '#fff' }} /> : 'Save budget'}
                                </Button>
                            </Stack>
                        </Stack>
                        {orgBudgetMsg && (
                            <Alert severity={orgBudgetMsg.startsWith('Org budget') ? 'success' : 'error'} sx={{ mb: 2, borderRadius: 2 }}>{orgBudgetMsg}</Alert>
                        )}
                        <Stack spacing={1}>
                            <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                                <Typography sx={{ fontSize: '0.84rem', color: '#64748b' }}>
                                    {fmtNum(orgUsed)} used · {fmtNum(orgDeptAllocated)} allocated to depts · {fmtNum(orgUnallocated)} unallocated
                                </Typography>
                                <Typography sx={{ fontSize: '0.84rem', fontWeight: 700, color: orgUtilPct > 80 ? '#C62828' : '#1565C0' }}>{orgUtilPct}%</Typography>
                            </Stack>
                            <LinearProgress variant="determinate" value={orgUtilPct}
                                sx={{ height: 10, borderRadius: 5, bgcolor: 'rgba(21,101,192,0.1)', '& .MuiLinearProgress-bar': { bgcolor: orgUtilPct > 80 ? '#C62828' : '#1565C0', borderRadius: 5 } }} />
                            <Stack direction="row" spacing={2}>
                                <Chip size="small" label={`Budget: ${fmtNum(orgBudget)}`} sx={{ bgcolor: 'rgba(21,101,192,0.1)', color: '#1565C0', fontWeight: 700, fontSize: '0.74rem' }} />
                                <Chip size="small" label={`Used: ${fmtNum(orgUsed)}`} sx={{ bgcolor: 'rgba(100,116,139,0.1)', color: '#64748b', fontWeight: 700, fontSize: '0.74rem' }} />
                                <Chip size="small" label={`Dept allocated: ${fmtNum(orgDeptAllocated)}`} sx={{ bgcolor: 'rgba(46,125,50,0.1)', color: '#2E7D32', fontWeight: 700, fontSize: '0.74rem' }} />
                            </Stack>
                        </Stack>
                    </Paper>

                    {/* Stat cards */}
                    <Grid container spacing={2}>
                        <Grid item xs={6} sm={3}>
                            <StatCard icon={<GroupOutlined sx={{ fontSize: 18 }} />} label="Total users" value={summary?.totals.user_count ?? '-'} sub={`${summary?.totals.active_user_count ?? '-'} active`} />
                        </Grid>
                        <Grid item xs={6} sm={3}>
                            <StatCard icon={<BusinessOutlined sx={{ fontSize: 18 }} />} label="Departments" value={summary?.totals.department_count ?? '-'} sub={`${fmtNum(orgDeptAllocated)} tokens allocated`} />
                        </Grid>
                        <Grid item xs={6} sm={3}>
                            <StatCard icon={<AdminPanelSettingsOutlined sx={{ fontSize: 18 }} />} label="Admins" value={summary?.totals.admin_count ?? '-'} sub="With admin access" />
                        </Grid>
                        <Grid item xs={6} sm={3}>
                            <StatCard icon={<TokenOutlined sx={{ fontSize: 18 }} />} label="Tokens used" value={fmtNum(orgUsed)} sub={`of ${fmtNum(orgBudget)} budget`} />
                        </Grid>
                    </Grid>

                    {/* Department token breakdown */}
                    {departments.length > 0 && (
                        <Paper elevation={0} sx={{ p: 3, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }}>
                            <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2.5 }}>
                                <Typography sx={{ fontWeight: 700, color: '#0f172a' }}>Department Token Allocation</Typography>
                                <Button size="small" onClick={() => setActiveTab('departments')} sx={{ textTransform: 'none', color: '#1565C0', fontWeight: 600 }}>View all</Button>
                            </Stack>
                            <Stack spacing={2.5}>
                                {departments.map((dept) => {
                                    const used = dept.usage?.total_token_used ?? 0;
                                    const limit = dept.monthly_token_limit;
                                    const pct = limit ? Math.min(Math.round((used / limit) * 100), 100) : 0;
                                    return (
                                        <Box key={dept.id}>
                                            <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 0.5 }}>
                                                <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                                                    <Typography sx={{ fontWeight: 700, color: '#334155', fontSize: '0.88rem' }}>{dept.name}</Typography>
                                                    <Chip size="small" label={`${dept.usage?.user_count ?? 0} users`} sx={{ fontSize: '0.72rem', height: 18, bgcolor: 'rgba(15,23,42,0.06)', color: '#64748b' }} />
                                                </Stack>
                                                <Typography sx={{ fontSize: '0.82rem', color: '#64748b' }}>
                                                    {fmtNum(used)} / {limit ? fmtNum(limit) : '∞'}
                                                    {limit > 0 && <span style={{ fontWeight: 700, color: pct > 80 ? '#C62828' : '#1565C0', marginLeft: 6 }}>{pct}%</span>}
                                                </Typography>
                                            </Stack>
                                            {limit > 0 && (
                                                <LinearProgress variant="determinate" value={pct} sx={{ height: 7, borderRadius: 4, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: pct > 80 ? '#C62828' : '#1565C0', borderRadius: 4 } }} />
                                            )}
                                        </Box>
                                    );
                                })}
                            </Stack>
                        </Paper>
                    )}

                </Stack>
            )}

            {/* ── USERS TAB ── */}
            {activeTab === 'users' && (
                <Stack spacing={2}>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                        <TextField
                            size="small" placeholder="Search by name, email, or department…"
                            value={search} onChange={(e) => setSearch(e.target.value)}
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
                                {departments.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
                            </TextField>
                        )}
                    </Stack>

                    <Paper elevation={0} sx={{ borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', overflow: 'hidden' }}>
                        {!isLoading && filteredUsers.length === 0 ? (
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
                                            const used = u.usage?.monthly_token_used || 0;
                                            const limit = u.effective_monthly_token_limit || u.monthly_token_limit || 0;
                                            const usedPct = limit ? Math.min(Math.round((used / limit) * 100), 100) : 0;
                                            return (
                                                <TableRow key={u.id} hover onClick={() => openEdit(u.id)}
                                                    sx={{ cursor: 'pointer', '&:last-child td': { border: 0 }, '& td': { borderBottom: '1px solid rgba(15,23,42,0.06)' }, '&:hover': { bgcolor: 'rgba(21,101,192,0.025)' } }}>
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
                                                        <Typography sx={{ color: '#334155', fontSize: '0.88rem' }}>{u.department || <span style={{ color: '#94a3b8' }}>—</span>}</Typography>
                                                        {u.title && <Typography sx={{ color: '#94a3b8', fontSize: '0.76rem' }}>{u.title}</Typography>}
                                                    </TableCell>
                                                    <TableCell>
                                                        <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: '4px' }}>
                                                            <Chip size="small" label={u.org_role || 'member'} sx={{ bgcolor: 'rgba(21,101,192,0.08)', color: '#1565C0', fontWeight: 700, fontSize: '0.74rem' }} />
                                                            {u.is_admin && <Chip size="small" label="Admin" sx={{ bgcolor: 'rgba(13,71,161,0.1)', color: '#0D47A1', fontWeight: 700, fontSize: '0.74rem' }} />}
                                                            {(u.token_topup_tokens || 0) > 0 && <Chip size="small" label={`Top-up +${fmtNum(u.token_topup_tokens || 0)}`} sx={{ bgcolor: 'rgba(230,81,0,0.1)', color: '#E65100', fontWeight: 700, fontSize: '0.74rem' }} />}
                                                        </Stack>
                                                    </TableCell>
                                                    <TableCell>
                                                        <Chip size="small" label={u.is_active ? 'Active' : 'Inactive'}
                                                            sx={{ bgcolor: u.is_active ? 'rgba(46,125,50,0.1)' : 'rgba(100,116,139,0.1)', color: u.is_active ? '#2E7D32' : '#64748b', fontWeight: 700, fontSize: '0.74rem' }} />
                                                    </TableCell>
                                                    <TableCell>
                                                        <Stack spacing={0.5}>
                                                            <LinearProgress variant="determinate" value={usedPct} sx={{ height: 6, borderRadius: 3, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: usedPct > 80 ? '#C62828' : '#1565C0', borderRadius: 3 } }} />
                                                            <Typography sx={{ color: '#94a3b8', fontSize: '0.72rem' }}>{usedPct}% of {fmtNum(limit)}</Typography>
                                                        </Stack>
                                                    </TableCell>
                                                    <TableCell>
                                                        <Tooltip title="Edit user">
                                                            <IconButton size="small" onClick={(e) => { e.stopPropagation(); openEdit(u.id); }}
                                                                sx={{ color: '#94a3b8', '&:hover': { color: '#1565C0', bgcolor: 'rgba(21,101,192,0.08)' } }}>
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
                </Stack>
            )}

            {/* ── DEPARTMENTS TAB ── */}
            {activeTab === 'departments' && (
                <Stack spacing={2}>
                    {departments.length === 0 && !isLoading ? (
                        <Paper elevation={0} sx={{ p: 6, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', textAlign: 'center' }}>
                            <BusinessOutlined sx={{ fontSize: 40, color: '#cbd5e1', mb: 1.5 }} />
                            <Typography sx={{ fontWeight: 700, color: '#334155', mb: 0.5 }}>No departments yet</Typography>
                            <Typography sx={{ color: '#64748b', mb: 2.5, fontSize: '0.88rem' }}>Create departments to organize users and assign token budgets.</Typography>
                            <Button variant="contained" startIcon={<AddBusinessOutlined />} onClick={openDeptCreate}
                                sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2, bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }}>
                                Create first department
                            </Button>
                        </Paper>
                    ) : (
                        <Grid container spacing={2}>
                            {departments.map((dept) => {
                                const used = dept.usage?.total_token_used ?? 0;
                                const limit = dept.monthly_token_limit;
                                const pct = limit ? Math.min(Math.round((used / limit) * 100), 100) : 0;
                                return (
                                    <Grid item xs={12} md={6} key={dept.id}>
                                        <Paper elevation={0} sx={{ p: 2.5, borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)', height: '100%', transition: 'box-shadow 0.15s', '&:hover': { boxShadow: '0 4px 20px rgba(21,101,192,0.08)' } }}>
                                            <Stack spacing={2}>
                                                <Stack direction="row" sx={{ alignItems: 'flex-start', justifyContent: 'space-between' }}>
                                                    <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                                                        <Box sx={{ p: 1, bgcolor: 'rgba(21,101,192,0.08)', borderRadius: 2, display: 'flex' }}>
                                                            <BusinessOutlined sx={{ fontSize: 20, color: '#1565C0' }} />
                                                        </Box>
                                                        <Box>
                                                            <Typography sx={{ fontWeight: 800, color: '#0f172a', fontSize: '0.95rem' }}>{dept.name}</Typography>
                                                            {dept.description && <Typography sx={{ color: '#64748b', fontSize: '0.78rem', mt: 0.2 }}>{dept.description}</Typography>}
                                                        </Box>
                                                    </Stack>
                                                    <Stack direction="row" spacing={0.5}>
                                                        <Tooltip title="Edit department">
                                                            <IconButton size="small" onClick={() => openDeptEdit(dept.id)}
                                                                sx={{ color: '#94a3b8', '&:hover': { color: '#1565C0', bgcolor: 'rgba(21,101,192,0.08)' } }}>
                                                                <EditOutlined sx={{ fontSize: 17 }} />
                                                            </IconButton>
                                                        </Tooltip>
                                                        <Tooltip title="Delete department">
                                                            <IconButton size="small" onClick={() => setDeptDeleteConfirm(dept)}
                                                                sx={{ color: '#94a3b8', '&:hover': { color: '#C62828', bgcolor: 'rgba(198,40,40,0.06)' } }}>
                                                                <DeleteOutlined sx={{ fontSize: 17 }} />
                                                            </IconButton>
                                                        </Tooltip>
                                                    </Stack>
                                                </Stack>

                                                <Divider sx={{ borderColor: 'rgba(15,23,42,0.06)' }} />

                                                <Stack direction="row" spacing={3}>
                                                    <Box>
                                                        <Typography sx={{ fontWeight: 800, fontSize: '1.3rem', color: '#0f172a', lineHeight: 1 }}>{dept.usage?.user_count ?? 0}</Typography>
                                                        <Typography sx={{ fontSize: '0.74rem', color: '#94a3b8', mt: 0.3 }}>Users</Typography>
                                                    </Box>
                                                    <Box>
                                                        <Typography sx={{ fontWeight: 800, fontSize: '1.3rem', color: '#0f172a', lineHeight: 1 }}>{fmtNum(used)}</Typography>
                                                        <Typography sx={{ fontSize: '0.74rem', color: '#94a3b8', mt: 0.3 }}>Tokens used</Typography>
                                                    </Box>
                                                    <Box>
                                                        <Typography sx={{ fontWeight: 800, fontSize: '1.3rem', color: limit ? (pct > 80 ? '#C62828' : '#1565C0') : '#94a3b8', lineHeight: 1 }}>
                                                            {limit ? fmtNum(limit) : '∞'}
                                                        </Typography>
                                                        <Typography sx={{ fontSize: '0.74rem', color: '#94a3b8', mt: 0.3 }}>Monthly limit</Typography>
                                                    </Box>
                                                </Stack>

                                                {limit > 0 && (
                                                    <Stack spacing={0.5}>
                                                        <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                                                            <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>{fmtNum(used)} of {fmtNum(limit)}</Typography>
                                                            <Typography sx={{ fontSize: '0.78rem', fontWeight: 700, color: pct > 80 ? '#C62828' : '#1565C0' }}>{pct}%</Typography>
                                                        </Stack>
                                                        <LinearProgress variant="determinate" value={pct} sx={{ height: 6, borderRadius: 3, bgcolor: 'rgba(15,23,42,0.07)', '& .MuiLinearProgress-bar': { bgcolor: pct > 80 ? '#C62828' : '#1565C0', borderRadius: 3 } }} />
                                                        {pct > 80 && (
                                                            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
                                                                <WarningAmberOutlined sx={{ fontSize: 14, color: '#C62828' }} />
                                                                <Typography sx={{ fontSize: '0.75rem', color: '#C62828', fontWeight: 600 }}>High token usage — consider increasing the limit.</Typography>
                                                            </Stack>
                                                        )}
                                                    </Stack>
                                                )}
                                                {!limit && (
                                                    <Typography sx={{ fontSize: '0.78rem', color: '#94a3b8' }}>No token limit set — click edit to assign a budget.</Typography>
                                                )}
                                            </Stack>
                                        </Paper>
                                    </Grid>
                                );
                            })}
                        </Grid>
                    )}
                </Stack>
            )}

            {/* ── Delete Department Dialog ── */}
            <Dialog open={Boolean(deptDeleteConfirm)} onClose={() => setDeptDeleteConfirm(null)} maxWidth="xs" fullWidth PaperProps={{ sx: { borderRadius: 3 } }}>
                <DialogTitle sx={{ fontWeight: 800, color: '#0f172a' }}>Delete Department</DialogTitle>
                <DialogContent>
                    <Typography sx={{ color: '#334155' }}>
                        Are you sure you want to delete <strong>{deptDeleteConfirm?.name}</strong>?
                        This action cannot be undone. All users must be moved out of this department first.
                    </Typography>
                </DialogContent>
                <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
                    <Button onClick={() => setDeptDeleteConfirm(null)} sx={{ textTransform: 'none', fontWeight: 600, color: '#64748b' }}>Cancel</Button>
                    <Button variant="contained" onClick={() => deptDeleteConfirm && void handleDeptDelete(deptDeleteConfirm)}
                        sx={{ textTransform: 'none', fontWeight: 700, bgcolor: '#C62828', '&:hover': { bgcolor: '#B71C1C' }, borderRadius: 2 }}>
                        Delete
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
};

export default AdminConsolePage;

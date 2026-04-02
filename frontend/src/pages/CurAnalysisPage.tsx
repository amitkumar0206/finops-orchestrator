import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Collapse,
    Divider,
    Grid,
    IconButton,
    LinearProgress,
    Paper,
    Stack,
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
    CloudUpload as CloudUploadIcon,
    BoltOutlined as BoltOutlinedIcon,
    Replay as ReplayIcon,
    ReceiptLongOutlined as ReceiptLongOutlinedIcon,
    SavingsOutlined as SavingsOutlinedIcon,
    InsightsOutlined as InsightsOutlinedIcon,
    CalendarMonthOutlined as CalendarMonthOutlinedIcon,
    PaidOutlined as PaidOutlinedIcon,
    OpenInNewOutlined as OpenInNewOutlinedIcon,
    InfoOutlined as InfoOutlinedIcon,
    ExpandMore as ExpandMoreIcon,
    ExpandLess as ExpandLessIcon,
    CloudSyncOutlined as CloudSyncOutlinedIcon,
} from '@mui/icons-material';

import { apiFetch } from '../lib/api';

// ─── Types ────────────────────────────────────────────────────────────────────

interface CURCapabilities {
    enabled: boolean;
    advisory_mode_available: boolean;
    connected_mode_available: boolean;
    upload_max_size_mb: number;
    upload_max_rows: number;
    lookback_days: number;
    thresholds: Record<string, number>;
}

interface CURSummary {
    rows_analyzed: number;
    period_start?: string | null;
    period_end?: string | null;
    period_days: number;
    total_unblended_cost_usd: number;
    total_opportunities: number;
    estimated_monthly_savings_usd: number;
    by_detector: Record<string, number>;
}

interface CUROpportunity {
    id?: string;
    title: string;
    description?: string;
    category?: string;
    service?: string;
    region?: string | null;
    resource_id?: string | null;
    estimated_monthly_savings?: number;
    estimated_annual_savings?: number;
    current_monthly_cost?: number | null;
    effort_level?: string;
    risk_level?: string;
    confidence_score?: number;
    [key: string]: unknown;
}

interface CURAnalysisResponse {
    mode: 'advisory' | 'connected';
    account_id?: string | null;
    summary?: CURSummary | null;
    opportunities: CUROpportunity[];
    ingest_result?: {
        total_signals: number;
        new_opportunities: number;
        updated_opportunities: number;
        skipped: number;
        errors: number;
    } | null;
}

type Mode = 'advisory' | 'connected';

// ─── Constants / helpers ──────────────────────────────────────────────────────

const BRAND_BLUE = '#1565C0';
const BRAND_BLUE_DARK = '#0D47A1';

const CATEGORY_LABELS: Record<string, string> = {
    idle_resources: 'Idle Resources',
    rightsizing: 'Rightsizing',
    purchase_option: 'Purchase Options',
    reserved_capacity: 'Reserved Capacity',
    savings_plans: 'Savings Plans',
    storage_optimization: 'Storage',
    data_transfer: 'Data Transfer',
    scheduling: 'Scheduling',
    anomaly: 'Cost Anomaly',
    other: 'Other',
};

const fmtMoney = (n?: number | null): string => {
    if (n == null || Number.isNaN(n)) return '—';
    return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: n >= 100 ? 0 : 2 });
};

const fmtNum = (n?: number | null): string => {
    if (n == null || Number.isNaN(n)) return '—';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toLocaleString();
};

const fmtCategory = (c?: string): string =>
    c ? CATEGORY_LABELS[c] ?? c.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()) : 'Other';

const levelChipSx = (level?: string) => {
    const l = (level || '').toLowerCase();
    if (l === 'high') return { bgcolor: 'rgba(220,38,38,0.1)', color: '#b91c1c', border: '1px solid rgba(220,38,38,0.2)' };
    if (l === 'medium') return { bgcolor: 'rgba(217,119,6,0.1)', color: '#b45309', border: '1px solid rgba(217,119,6,0.2)' };
    if (l === 'low') return { bgcolor: 'rgba(5,150,105,0.1)', color: '#047857', border: '1px solid rgba(5,150,105,0.2)' };
    return { bgcolor: 'rgba(15,23,42,0.06)', color: '#475569', border: '1px solid rgba(15,23,42,0.1)' };
};

const parseApiError = async (response: Response, fallback: string): Promise<string> => {
    try {
        const body = await response.text();
        if (!body) return fallback;
        let parsed: any = null;
        try {
            parsed = JSON.parse(body);
        } catch {
            /* not json */
        }
        const detail = parsed?.detail ?? parsed?.message;
        if (detail && typeof detail === 'object') {
            return String(detail.message || JSON.stringify(detail));
        }
        if (Array.isArray(detail)) {
            return detail.map((d: any) => d?.msg).filter(Boolean).join('. ') || fallback;
        }
        if (typeof detail === 'string' && detail.trim()) return detail;
        if (body.trim()) return body;
        return fallback;
    } catch {
        return fallback;
    }
};

// ─── Sub-components ───────────────────────────────────────────────────────────

interface StatTileProps {
    icon: React.ReactNode;
    label: string;
    value: React.ReactNode;
    sub?: React.ReactNode;
    accent?: string;
}

const StatTile: React.FC<StatTileProps> = ({ icon, label, value, sub, accent = BRAND_BLUE }) => (
    <Paper
        elevation={0}
        sx={{
            p: 2,
            height: '100%',
            borderRadius: 3,
            border: '1px solid rgba(15,23,42,0.08)',
            bgcolor: '#ffffff',
        }}
    >
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
            <Box
                sx={{
                    width: 40,
                    height: 40,
                    borderRadius: 2,
                    display: 'grid',
                    placeItems: 'center',
                    bgcolor: 'rgba(21,101,192,0.1)',
                    color: accent,
                    flexShrink: 0,
                }}
            >
                {icon}
            </Box>
            <Box sx={{ minWidth: 0 }}>
                <Typography sx={{ fontWeight: 600, color: '#64748b', fontSize: '0.74rem', textTransform: 'uppercase', letterSpacing: 0.4 }}>
                    {label}
                </Typography>
                <Typography sx={{ fontWeight: 800, fontSize: '1.25rem', color: '#0f172a', lineHeight: 1.15 }}>
                    {value}
                </Typography>
                {sub && <Typography sx={{ color: '#94a3b8', fontSize: '0.74rem' }}>{sub}</Typography>}
            </Box>
        </Stack>
    </Paper>
);

interface OpportunityRowProps {
    opp: CUROpportunity;
}

const OpportunityRow: React.FC<OpportunityRowProps> = ({ opp }) => {
    const [open, setOpen] = useState(false);
    return (
        <>
            <TableRow hover sx={{ '& > *': { borderBottom: 'unset' } }}>
                <TableCell sx={{ width: 40, pr: 0 }}>
                    <IconButton size="small" onClick={() => setOpen((v) => !v)} aria-label="expand">
                        {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                    </IconButton>
                </TableCell>
                <TableCell sx={{ maxWidth: 360 }}>
                    <Typography sx={{ fontWeight: 600, fontSize: '0.88rem', color: '#0f172a' }}>{opp.title}</Typography>
                    {opp.resource_id && (
                        <Typography sx={{ fontSize: '0.74rem', color: '#94a3b8', fontFamily: 'ui-monospace, monospace' }} noWrap>
                            {opp.resource_id}
                        </Typography>
                    )}
                </TableCell>
                <TableCell>
                    <Chip
                        size="small"
                        label={fmtCategory(opp.category)}
                        sx={{
                            fontSize: '0.72rem',
                            fontWeight: 600,
                            bgcolor: 'rgba(21,101,192,0.08)',
                            color: BRAND_BLUE_DARK,
                            border: '1px solid rgba(21,101,192,0.18)',
                        }}
                    />
                </TableCell>
                <TableCell sx={{ fontSize: '0.84rem', color: '#334155' }}>{opp.service || '—'}</TableCell>
                <TableCell sx={{ fontSize: '0.84rem', color: '#334155' }}>{opp.region || '—'}</TableCell>
                <TableCell align="right">
                    <Typography sx={{ fontWeight: 700, fontSize: '0.9rem', color: '#047857' }}>
                        {fmtMoney(opp.estimated_monthly_savings)}
                    </Typography>
                    <Typography sx={{ fontSize: '0.7rem', color: '#94a3b8' }}>/ month</Typography>
                </TableCell>
                <TableCell align="center">
                    <Chip size="small" label={(opp.effort_level || '—').toUpperCase()} sx={{ ...levelChipSx(opp.effort_level), fontSize: '0.68rem', fontWeight: 700, height: 22 }} />
                </TableCell>
                <TableCell align="center">
                    <Chip size="small" label={(opp.risk_level || '—').toUpperCase()} sx={{ ...levelChipSx(opp.risk_level), fontSize: '0.68rem', fontWeight: 700, height: 22 }} />
                </TableCell>
            </TableRow>
            <TableRow>
                <TableCell sx={{ py: 0, borderBottom: '1px solid rgba(15,23,42,0.06)' }} colSpan={8}>
                    <Collapse in={open} timeout="auto" unmountOnExit>
                        <Box sx={{ py: 1.5, px: 1 }}>
                            {opp.description && (
                                <Typography sx={{ fontSize: '0.86rem', color: '#475569', mb: 1.2, lineHeight: 1.6 }}>
                                    {opp.description}
                                </Typography>
                            )}
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                {opp.current_monthly_cost != null && (
                                    <Chip size="small" variant="outlined" label={`Current: ${fmtMoney(opp.current_monthly_cost)}/mo`} />
                                )}
                                {opp.estimated_annual_savings != null && (
                                    <Chip size="small" variant="outlined" label={`Annual: ${fmtMoney(opp.estimated_annual_savings)}`} />
                                )}
                                {typeof opp.confidence_score === 'number' && (
                                    <Chip size="small" variant="outlined" label={`Confidence: ${Math.round(opp.confidence_score * 100)}%`} />
                                )}
                            </Stack>
                        </Box>
                    </Collapse>
                </TableCell>
            </TableRow>
        </>
    );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const CurAnalysisPage: React.FC = () => {
    const [capabilities, setCapabilities] = useState<CURCapabilities | null>(null);
    const [capError, setCapError] = useState<string | null>(null);

    const [mode, setMode] = useState<Mode>('advisory');
    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const [accountId, setAccountId] = useState('');
    const [isDragging, setIsDragging] = useState(false);

    const [isRunning, setIsRunning] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<CURAnalysisResponse | null>(null);

    const fileInputRef = useRef<HTMLInputElement | null>(null);

    // Load capabilities on mount
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const resp = await apiFetch('/api/v1/cur-analysis/capabilities');
                if (!resp.ok) {
                    const msg = await parseApiError(resp, 'Failed to load CUR analysis capabilities');
                    throw new Error(msg);
                }
                const data: CURCapabilities = await resp.json();
                if (cancelled) return;
                setCapabilities(data);
                // Default to connected mode if available, otherwise advisory
                setMode(data.connected_mode_available ? 'connected' : 'advisory');
            } catch (e) {
                if (!cancelled) setCapError(e instanceof Error ? e.message : String(e));
            }
        })();
        return () => {
            cancelled = true;
        };
    }, []);

    const accountIdValid = accountId === '' || /^\d{12}$/.test(accountId);
    const fileTooLarge =
        !!selectedFile && !!capabilities && selectedFile.size > capabilities.upload_max_size_mb * 1024 * 1024;

    const canRunAdvisory = !!selectedFile && accountIdValid && !fileTooLarge;
    const canRunConnected = !!capabilities?.connected_mode_available;

    const reset = () => {
        setSelectedFile(null);
        setAccountId('');
        setResult(null);
        setError(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const acceptFile = (file: File | null) => {
        if (!file) return;
        const lower = file.name.toLowerCase();
        if (!(lower.endsWith('.csv') || lower.endsWith('.csv.gz') || lower.endsWith('.gz'))) {
            setError('Only AWS CUR CSV exports (.csv or .csv.gz) are accepted.');
            return;
        }
        setError(null);
        setSelectedFile(file);
    };

    const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        acceptFile(e.target.files?.[0] ?? null);
    };

    const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault();
        setIsDragging(false);
        acceptFile(e.dataTransfer.files?.[0] ?? null);
    };

    const runAdvisory = async () => {
        if (!selectedFile) return;
        setIsRunning(true);
        setError(null);
        setResult(null);
        try {
            const fd = new FormData();
            fd.append('file', selectedFile);
            if (accountId) fd.append('account_id', accountId);
            const resp = await apiFetch('/api/v1/cur-analysis/upload', { method: 'POST', body: fd });
            if (!resp.ok) {
                const msg = await parseApiError(resp, `Upload failed (${resp.status})`);
                throw new Error(msg);
            }
            const data: CURAnalysisResponse = await resp.json();
            setResult(data);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Upload failed');
        } finally {
            setIsRunning(false);
        }
    };

    const runConnected = async () => {
        setIsRunning(true);
        setError(null);
        setResult(null);
        try {
            const resp = await apiFetch('/api/v1/cur-analysis/mine', { method: 'POST' });
            if (!resp.ok) {
                const msg = await parseApiError(resp, `Mining failed (${resp.status})`);
                throw new Error(msg);
            }
            const data: CURAnalysisResponse = await resp.json();
            setResult(data);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Mining failed');
        } finally {
            setIsRunning(false);
        }
    };

    const sortedOpps = useMemo(() => {
        if (!result?.opportunities) return [];
        return [...result.opportunities].sort(
            (a, b) => (b.estimated_monthly_savings || 0) - (a.estimated_monthly_savings || 0),
        );
    }, [result]);

    const periodLabel = useMemo(() => {
        const s = result?.summary;
        if (!s) return null;
        if (s.period_start && s.period_end) {
            const start = s.period_start.slice(0, 10);
            const end = s.period_end.slice(0, 10);
            return start === end ? start : `${start} → ${end}`;
        }
        return `${s.period_days} days`;
    }, [result]);

    return (
        <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1320, mx: 'auto' }}>
            <Stack spacing={2.5}>
                {/* Header banner */}
                <Paper
                    elevation={0}
                    sx={{
                        position: 'relative',
                        overflow: 'hidden',
                        p: { xs: 1.4, md: 1.8 },
                        borderRadius: 2.5,
                        border: '1px solid rgba(21, 101, 192, 0.16)',
                        background: 'linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%)',
                    }}
                >
                    <Box
                        sx={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: 5,
                            background: 'linear-gradient(180deg, #1558ad 0%, #0b8f9e 100%)',
                        }}
                    />
                    <Stack
                        direction={{ xs: 'column', md: 'row' }}
                        spacing={1.5}
                        sx={{ pl: { xs: 1.1, md: 1.4 }, alignItems: { md: 'center' } }}
                    >
                        <Stack spacing={0.55} sx={{ flex: 1 }}>
                            <Typography variant="overline" sx={{ color: 'primary.main', fontWeight: 700, letterSpacing: 0.8 }}>
                                CUR Deep Analysis
                            </Typography>
                            <Typography variant="h5" sx={{ fontWeight: 700, color: '#123a63', lineHeight: 1.2 }}>
                                Billing Export Pattern Mining
                            </Typography>
                            <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 820 }}>
                                Mine your AWS Cost & Usage Report for idle resources, commitment gaps, scheduling
                                wins, and spend anomalies — connected via Athena, or advisory via CSV upload.
                            </Typography>
                        </Stack>
                        {capabilities && (
                            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                                <Chip
                                    size="small"
                                    icon={<CloudSyncOutlinedIcon sx={{ fontSize: '1rem !important' }} />}
                                    label={capabilities.connected_mode_available ? 'Connected' : 'Connected unavailable'}
                                    sx={{
                                        fontWeight: 600,
                                        bgcolor: capabilities.connected_mode_available ? 'rgba(5,150,105,0.1)' : 'rgba(15,23,42,0.06)',
                                        color: capabilities.connected_mode_available ? '#047857' : '#64748b',
                                    }}
                                />
                                <Chip
                                    size="small"
                                    icon={<CloudUploadIcon sx={{ fontSize: '1rem !important' }} />}
                                    label="Advisory"
                                    sx={{ fontWeight: 600, bgcolor: 'rgba(21,101,192,0.1)', color: BRAND_BLUE_DARK }}
                                />
                            </Stack>
                        )}
                    </Stack>
                </Paper>

                {capError && (
                    <Alert severity="error" icon={<InfoOutlinedIcon />}>
                        {capError}
                    </Alert>
                )}

                {capabilities && !capabilities.enabled && (
                    <Alert severity="warning">
                        CUR pattern mining is disabled for this deployment. Contact your administrator to enable it.
                    </Alert>
                )}

                {/* Mode + input card */}
                <Card sx={{ borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }} elevation={0}>
                    <Box sx={{ borderBottom: '1px solid rgba(15,23,42,0.06)', px: 1 }}>
                        <Tabs
                            value={mode}
                            onChange={(_, v: Mode) => {
                                setMode(v);
                                setError(null);
                            }}
                        >
                            <Tab
                                value="advisory"
                                label="Advisory · Upload CSV"
                                icon={<CloudUploadIcon sx={{ fontSize: 18 }} />}
                                iconPosition="start"
                                sx={{ textTransform: 'none', fontWeight: 600, minHeight: 52 }}
                            />
                            <Tab
                                value="connected"
                                disabled={!canRunConnected}
                                label={
                                    <Stack direction="row" spacing={0.75} alignItems="center">
                                        <span>Connected · Live Athena</span>
                                        {!canRunConnected && (
                                            <Tooltip title="Athena / CUR table is not configured for this deployment.">
                                                <InfoOutlinedIcon sx={{ fontSize: 16, color: '#94a3b8' }} />
                                            </Tooltip>
                                        )}
                                    </Stack>
                                }
                                icon={<CloudSyncOutlinedIcon sx={{ fontSize: 18 }} />}
                                iconPosition="start"
                                sx={{ textTransform: 'none', fontWeight: 600, minHeight: 52 }}
                            />
                        </Tabs>
                    </Box>

                    <CardContent>
                        {mode === 'advisory' && (
                            <Stack spacing={2}>
                                <Box
                                    onDragOver={(e) => {
                                        e.preventDefault();
                                        setIsDragging(true);
                                    }}
                                    onDragLeave={() => setIsDragging(false)}
                                    onDrop={onDrop}
                                    onClick={() => fileInputRef.current?.click()}
                                    sx={{
                                        border: `2px dashed ${isDragging ? BRAND_BLUE : 'rgba(15,23,42,0.15)'}`,
                                        borderRadius: 2.5,
                                        bgcolor: isDragging ? 'rgba(21,101,192,0.06)' : 'rgba(248,250,252,0.6)',
                                        py: { xs: 3, md: 4 },
                                        px: 2,
                                        textAlign: 'center',
                                        cursor: 'pointer',
                                        transition: 'all 0.15s ease',
                                        '&:hover': { borderColor: BRAND_BLUE, bgcolor: 'rgba(21,101,192,0.04)' },
                                    }}
                                >
                                    <input
                                        ref={fileInputRef}
                                        hidden
                                        type="file"
                                        accept=".csv,.gz,application/gzip,text/csv"
                                        onChange={onFileChange}
                                    />
                                    <ReceiptLongOutlinedIcon sx={{ fontSize: 38, color: BRAND_BLUE, mb: 1 }} />
                                    {selectedFile ? (
                                        <>
                                            <Typography sx={{ fontWeight: 700, color: '#0f172a' }}>{selectedFile.name}</Typography>
                                            <Typography sx={{ fontSize: '0.82rem', color: '#64748b' }}>
                                                {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB · click to replace
                                            </Typography>
                                        </>
                                    ) : (
                                        <>
                                            <Typography sx={{ fontWeight: 700, color: '#0f172a' }}>
                                                Drop your CUR export here
                                            </Typography>
                                            <Typography sx={{ fontSize: '0.84rem', color: '#64748b' }}>
                                                or <span style={{ color: BRAND_BLUE, fontWeight: 600 }}>browse</span> · .csv or .csv.gz
                                                {capabilities && ` · max ${capabilities.upload_max_size_mb} MB / ${fmtNum(capabilities.upload_max_rows)} rows`}
                                            </Typography>
                                        </>
                                    )}
                                </Box>

                                {fileTooLarge && capabilities && (
                                    <Alert severity="error">
                                        File exceeds the {capabilities.upload_max_size_mb} MB upload limit.
                                    </Alert>
                                )}

                                <Stack
                                    direction={{ xs: 'column', sm: 'row' }}
                                    spacing={1.5}
                                    alignItems={{ xs: 'stretch', sm: 'center' }}
                                >
                                    <TextField
                                        size="small"
                                        label="AWS Account ID (optional)"
                                        placeholder="123456789012"
                                        value={accountId}
                                        onChange={(e) => setAccountId(e.target.value.replace(/\D/g, '').slice(0, 12))}
                                        error={!accountIdValid}
                                        helperText={
                                            !accountIdValid
                                                ? 'Must be exactly 12 digits'
                                                : 'Override if the export omits lineItem/UsageAccountId'
                                        }
                                        sx={{ maxWidth: { sm: 280 } }}
                                        inputProps={{ inputMode: 'numeric' }}
                                    />
                                    <Box sx={{ flex: 1 }} />
                                    {selectedFile && (
                                        <Button variant="text" color="inherit" startIcon={<ReplayIcon />} onClick={reset} disabled={isRunning}>
                                            Clear
                                        </Button>
                                    )}
                                    <Button
                                        variant="contained"
                                        disableElevation
                                        onClick={runAdvisory}
                                        disabled={!canRunAdvisory || isRunning || !capabilities?.enabled}
                                        startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <BoltOutlinedIcon />}
                                        sx={{
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            borderRadius: 2,
                                            px: 2.4,
                                            bgcolor: BRAND_BLUE,
                                            '&:hover': { bgcolor: BRAND_BLUE_DARK },
                                        }}
                                    >
                                        {isRunning ? 'Analyzing…' : 'Analyze CUR Export'}
                                    </Button>
                                </Stack>
                            </Stack>
                        )}

                        {mode === 'connected' && (
                            <Stack spacing={2}>
                                <Alert
                                    severity={canRunConnected ? 'info' : 'warning'}
                                    icon={<CloudSyncOutlinedIcon />}
                                    sx={{ borderRadius: 2 }}
                                >
                                    {canRunConnected ? (
                                        <>
                                            Runs the Athena + Cost Explorer detectors against your live CUR table for
                                            the last <b>{capabilities?.lookback_days ?? 30} days</b>. Findings are
                                            persisted to your Opportunities backlog.
                                        </>
                                    ) : (
                                        <>
                                            Athena / CUR is not configured for this deployment. Use the{' '}
                                            <b>Advisory · Upload CSV</b> tab instead.
                                        </>
                                    )}
                                </Alert>
                                <Stack direction="row" spacing={1.5} justifyContent="flex-end">
                                    <Button
                                        variant="contained"
                                        disableElevation
                                        onClick={runConnected}
                                        disabled={!canRunConnected || isRunning || !capabilities?.enabled}
                                        startIcon={isRunning ? <CircularProgress size={16} color="inherit" /> : <BoltOutlinedIcon />}
                                        sx={{
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            borderRadius: 2,
                                            px: 2.4,
                                            bgcolor: BRAND_BLUE,
                                            '&:hover': { bgcolor: BRAND_BLUE_DARK },
                                        }}
                                    >
                                        {isRunning ? 'Mining…' : 'Mine Live CUR'}
                                    </Button>
                                </Stack>
                            </Stack>
                        )}

                        {error && (
                            <Alert severity="error" sx={{ mt: 2, borderRadius: 2 }}>
                                {error}
                            </Alert>
                        )}
                    </CardContent>

                    {isRunning && <LinearProgress sx={{ borderBottomLeftRadius: 12, borderBottomRightRadius: 12 }} />}
                </Card>

                {/* Results */}
                {result && result.summary && (
                    <Stack spacing={2.5}>
                        {/* Summary tiles */}
                        <Grid container spacing={2}>
                            <Grid item xs={12} sm={6} md={3}>
                                <StatTile
                                    icon={<SavingsOutlinedIcon />}
                                    label="Est. Monthly Savings"
                                    value={fmtMoney(result.summary.estimated_monthly_savings_usd)}
                                    sub={`${fmtMoney(result.summary.estimated_monthly_savings_usd * 12)} / year`}
                                    accent="#047857"
                                />
                            </Grid>
                            <Grid item xs={12} sm={6} md={3}>
                                <StatTile
                                    icon={<InsightsOutlinedIcon />}
                                    label="Opportunities"
                                    value={result.summary.total_opportunities}
                                    sub={`${Object.keys(result.summary.by_detector).length} detector(s) fired`}
                                />
                            </Grid>
                            <Grid item xs={12} sm={6} md={3}>
                                <StatTile
                                    icon={<PaidOutlinedIcon />}
                                    label="Spend Analyzed"
                                    value={fmtMoney(result.summary.total_unblended_cost_usd)}
                                    sub={result.mode === 'advisory' ? `${fmtNum(result.summary.rows_analyzed)} CUR rows` : 'Live Athena'}
                                />
                            </Grid>
                            <Grid item xs={12} sm={6} md={3}>
                                <StatTile
                                    icon={<CalendarMonthOutlinedIcon />}
                                    label="Billing Period"
                                    value={`${result.summary.period_days}d`}
                                    sub={periodLabel}
                                />
                            </Grid>
                        </Grid>

                        {/* Findings card */}
                        <Card sx={{ borderRadius: 3, border: '1px solid rgba(15,23,42,0.08)' }} elevation={0}>
                            <CardContent sx={{ pb: 1 }}>
                                <Stack
                                    direction={{ xs: 'column', md: 'row' }}
                                    spacing={1.5}
                                    sx={{ alignItems: { md: 'center' }, mb: 1.5 }}
                                >
                                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                                        <Chip
                                            color="success"
                                            size="small"
                                            label={result.mode === 'advisory' ? 'Advisory · CSV' : 'Connected · Athena'}
                                            sx={{ fontWeight: 700 }}
                                        />
                                        {result.account_id && (
                                            <Chip
                                                size="small"
                                                variant="outlined"
                                                label={`Account ${result.account_id}`}
                                                sx={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.74rem' }}
                                            />
                                        )}
                                        {result.ingest_result ? (
                                            <Chip
                                                size="small"
                                                variant="outlined"
                                                label={`Persisted: ${result.ingest_result.new_opportunities} new · ${result.ingest_result.updated_opportunities} updated`}
                                                sx={{ fontSize: '0.74rem' }}
                                            />
                                        ) : (
                                            <Tooltip title="Findings were returned but could not be persisted to the Opportunities store.">
                                                <Chip size="small" variant="outlined" color="warning" label="Not persisted" sx={{ fontSize: '0.74rem' }} />
                                            </Tooltip>
                                        )}
                                    </Stack>
                                    <Box sx={{ flex: 1 }} />
                                    <Stack direction="row" spacing={1}>
                                        <Button
                                            size="small"
                                            variant="text"
                                            startIcon={<ReplayIcon />}
                                            onClick={mode === 'advisory' ? runAdvisory : runConnected}
                                            disabled={isRunning || (mode === 'advisory' && !canRunAdvisory)}
                                            sx={{ textTransform: 'none', fontWeight: 600 }}
                                        >
                                            Run again
                                        </Button>
                                        <Button
                                            size="small"
                                            component={RouterLink}
                                            to="/analyze"
                                            variant="outlined"
                                            endIcon={<OpenInNewOutlinedIcon sx={{ fontSize: 16 }} />}
                                            sx={{
                                                textTransform: 'none',
                                                fontWeight: 600,
                                                borderColor: 'rgba(21,101,192,0.34)',
                                                color: BRAND_BLUE,
                                                '&:hover': { borderColor: BRAND_BLUE, bgcolor: 'rgba(21,101,192,0.06)' },
                                            }}
                                        >
                                            View in Opportunities
                                        </Button>
                                    </Stack>
                                </Stack>

                                {/* By-detector chips */}
                                <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                                    {Object.entries(result.summary.by_detector)
                                        .sort(([, a], [, b]) => b - a)
                                        .map(([cat, count]) => (
                                            <Chip
                                                key={cat}
                                                size="small"
                                                label={`${fmtCategory(cat)} · ${count}`}
                                                sx={{
                                                    fontSize: '0.74rem',
                                                    fontWeight: 600,
                                                    bgcolor: 'rgba(21,101,192,0.08)',
                                                    color: BRAND_BLUE_DARK,
                                                    border: '1px solid rgba(21,101,192,0.16)',
                                                }}
                                            />
                                        ))}
                                </Stack>
                            </CardContent>
                            <Divider />

                            {sortedOpps.length === 0 ? (
                                <Box sx={{ py: 5, textAlign: 'center' }}>
                                    <InsightsOutlinedIcon sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                    <Typography sx={{ fontWeight: 600, color: '#0f172a' }}>No opportunities detected</Typography>
                                    <Typography sx={{ fontSize: '0.86rem', color: '#64748b', mt: 0.5 }}>
                                        Either spend is already well-optimized, or thresholds were not met for this period.
                                    </Typography>
                                </Box>
                            ) : (
                                <TableContainer sx={{ maxHeight: 560 }}>
                                    <Table size="small" stickyHeader>
                                        <TableHead>
                                            <TableRow>
                                                <TableCell sx={{ width: 40 }} />
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }}>Opportunity</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }}>Category</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }}>Service</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }}>Region</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }} align="right">Savings</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }} align="center">Effort</TableCell>
                                                <TableCell sx={{ fontWeight: 700, color: '#475569' }} align="center">Risk</TableCell>
                                            </TableRow>
                                        </TableHead>
                                        <TableBody>
                                            {sortedOpps.map((opp, i) => (
                                                <OpportunityRow key={opp.id || `${opp.title}-${i}`} opp={opp} />
                                            ))}
                                        </TableBody>
                                    </Table>
                                </TableContainer>
                            )}
                        </Card>
                    </Stack>
                )}
            </Stack>
        </Box>
    );
};

export default CurAnalysisPage;

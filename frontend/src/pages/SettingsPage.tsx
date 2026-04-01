import React, { useState } from 'react';
import {
    Box,
    Typography,
    Paper,
    Divider,
    Switch,
    Select,
    MenuItem,
    FormControl,
    InputLabel,
    Button,
    Chip,
    List,
    ListItem,
    ListItemText,
    ListItemSecondaryAction,
    Alert,
} from '@mui/material';
import {
    NotificationsOutlined,
    SecurityOutlined,
    StorageOutlined,
    PaletteOutlined,
    LanguageOutlined,
    SaveOutlined,
} from '@mui/icons-material';
import { useAuth } from '../context/AuthContext';

const sectionHeader = (icon: React.ReactNode, title: string) => (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2.5 }}>
        <Box sx={{ color: '#1565C0' }}>{icon}</Box>
        <Typography variant="h6" sx={{ fontWeight: 700, color: '#0f172a', fontSize: '1rem' }}>
            {title}
        </Typography>
    </Box>
);

const SettingsPage: React.FC = () => {
    const { user } = useAuth();
    const [saved, setSaved] = useState(false);
    const [notifications, setNotifications] = useState({
        costAlerts: true,
        weeklyReports: true,
        anomalyDetection: true,
        deploymentUpdates: false,
    });
    const [preferences, setPreferences] = useState({
        currency: 'USD',
        timezone: 'America/New_York',
        dateFormat: 'MM/DD/YYYY',
        theme: 'light',
    });
    const [security, setSecurity] = useState({
        mfaEnabled: false,
        sessionTimeout: '30',
        apiLogging: true,
    });

    const handleSave = () => {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
    };

    return (
        <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 820, mx: 'auto' }}>
            <Box sx={{ mb: 4 }}>
                <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.6rem' }}>
                    Settings
                </Typography>
                <Typography sx={{ color: '#64748b', mt: 0.5 }}>
                    Manage your account preferences and application configuration.
                </Typography>
            </Box>

            {saved && (
                <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>
                    Settings saved successfully.
                </Alert>
            )}

            {/* Notifications */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 3 }}>
                {sectionHeader(<NotificationsOutlined />, 'Notifications')}
                <List disablePadding>
                    {[
                        { key: 'costAlerts', label: 'Cost threshold alerts', desc: 'Get notified when spending exceeds set thresholds' },
                        { key: 'weeklyReports', label: 'Weekly cost reports', desc: 'Receive a weekly summary of cloud spending' },
                        { key: 'anomalyDetection', label: 'Anomaly detection alerts', desc: 'Alert when unusual cost spikes are detected' },
                        { key: 'deploymentUpdates', label: 'Deployment notifications', desc: 'Notify on infrastructure deployment changes' },
                    ].map((item, i) => (
                        <React.Fragment key={item.key}>
                            {i > 0 && <Divider sx={{ my: 1 }} />}
                            <ListItem disablePadding sx={{ py: 0.5 }}>
                                <ListItemText
                                    primary={item.label}
                                    secondary={item.desc}
                                    primaryTypographyProps={{ fontWeight: 600, fontSize: '0.9rem' }}
                                    secondaryTypographyProps={{ fontSize: '0.8rem', color: '#64748b' }}
                                />
                                <ListItemSecondaryAction>
                                    <Switch
                                        checked={notifications[item.key as keyof typeof notifications]}
                                        onChange={(e) => setNotifications((p) => ({ ...p, [item.key]: e.target.checked }))}
                                        size="small"
                                        sx={{ '& .MuiSwitch-thumb': { color: '#1565C0' }, '& .Mui-checked + .MuiSwitch-track': { backgroundColor: '#1565C0' } }}
                                    />
                                </ListItemSecondaryAction>
                            </ListItem>
                        </React.Fragment>
                    ))}
                </List>
            </Paper>

            {/* Preferences */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 3 }}>
                {sectionHeader(<PaletteOutlined />, 'Display & Preferences')}
                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2.5 }}>
                    {[
                        { key: 'currency', label: 'Currency', options: ['USD', 'EUR', 'GBP', 'CAD', 'AUD'] },
                        { key: 'timezone', label: 'Timezone', options: ['America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London', 'Asia/Kolkata'] },
                        { key: 'dateFormat', label: 'Date Format', options: ['MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD'] },
                        { key: 'theme', label: 'Theme', options: ['light', 'dark', 'system'] },
                    ].map((item) => (
                        <FormControl key={item.key} size="small" fullWidth>
                            <InputLabel>{item.label}</InputLabel>
                            <Select
                                value={preferences[item.key as keyof typeof preferences]}
                                label={item.label}
                                onChange={(e) => setPreferences((p) => ({ ...p, [item.key]: e.target.value }))}
                            >
                                {item.options.map((opt) => (
                                    <MenuItem key={opt} value={opt}>{opt}</MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    ))}
                </Box>
            </Paper>

            {/* Security */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 3 }}>
                {sectionHeader(<SecurityOutlined />, 'Security')}
                <List disablePadding>
                    <ListItem disablePadding sx={{ py: 0.5 }}>
                        <ListItemText
                            primary="Multi-factor authentication"
                            secondary="Add an extra layer of security to your account"
                            primaryTypographyProps={{ fontWeight: 600, fontSize: '0.9rem' }}
                            secondaryTypographyProps={{ fontSize: '0.8rem', color: '#64748b' }}
                        />
                        <ListItemSecondaryAction>
                            <Switch
                                checked={security.mfaEnabled}
                                onChange={(e) => setSecurity((p) => ({ ...p, mfaEnabled: e.target.checked }))}
                                size="small"
                            />
                        </ListItemSecondaryAction>
                    </ListItem>
                    <Divider sx={{ my: 1 }} />
                    <ListItem disablePadding sx={{ py: 0.5 }}>
                        <ListItemText
                            primary="API request logging"
                            secondary="Log all API requests for audit purposes"
                            primaryTypographyProps={{ fontWeight: 600, fontSize: '0.9rem' }}
                            secondaryTypographyProps={{ fontSize: '0.8rem', color: '#64748b' }}
                        />
                        <ListItemSecondaryAction>
                            <Switch
                                checked={security.apiLogging}
                                onChange={(e) => setSecurity((p) => ({ ...p, apiLogging: e.target.checked }))}
                                size="small"
                            />
                        </ListItemSecondaryAction>
                    </ListItem>
                    <Divider sx={{ my: 1 }} />
                    <ListItem disablePadding sx={{ py: 1 }}>
                        <ListItemText
                            primary="Session timeout"
                            secondary="Automatically log out after inactivity"
                            primaryTypographyProps={{ fontWeight: 600, fontSize: '0.9rem' }}
                            secondaryTypographyProps={{ fontSize: '0.8rem', color: '#64748b' }}
                        />
                        <ListItemSecondaryAction>
                            <FormControl size="small" sx={{ minWidth: 110 }}>
                                <Select
                                    value={security.sessionTimeout}
                                    onChange={(e) => setSecurity((p) => ({ ...p, sessionTimeout: e.target.value }))}
                                >
                                    <MenuItem value="15">15 min</MenuItem>
                                    <MenuItem value="30">30 min</MenuItem>
                                    <MenuItem value="60">1 hour</MenuItem>
                                    <MenuItem value="240">4 hours</MenuItem>
                                    <MenuItem value="0">Never</MenuItem>
                                </Select>
                            </FormControl>
                        </ListItemSecondaryAction>
                    </ListItem>
                </List>
            </Paper>

            {/* Data */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 4 }}>
                {sectionHeader(<StorageOutlined />, 'Data & Integrations')}
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.5 }}>
                    {[
                        { label: 'AWS Cost Explorer', status: 'connected' },
                        { label: 'AWS CUR (S3)', status: 'connected' },
                        { label: 'AWS Athena', status: 'connected' },
                        { label: 'Slack', status: 'not connected' },
                        { label: 'PagerDuty', status: 'not connected' },
                        { label: 'Datadog', status: 'not connected' },
                    ].map((item) => (
                        <Chip
                            key={item.label}
                            label={item.label}
                            size="small"
                            icon={<LanguageOutlined style={{ fontSize: 14 }} />}
                            sx={{
                                bgcolor: item.status === 'connected' ? 'rgba(21,101,192,0.08)' : 'rgba(100,116,139,0.08)',
                                color: item.status === 'connected' ? '#1565C0' : '#64748b',
                                border: `1px solid ${item.status === 'connected' ? 'rgba(21,101,192,0.2)' : 'rgba(100,116,139,0.2)'}`,
                                fontWeight: 600,
                            }}
                        />
                    ))}
                </Box>
            </Paper>

            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3, mb: 4 }}>
                {sectionHeader(<SecurityOutlined />, 'Demo Access Snapshot')}
                <Typography sx={{ color: '#64748b', fontSize: '0.9rem', mb: 1.5 }}>
                    These controls are managed by the demo admin through the config-backed identity store.
                </Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.2, mb: 1.5 }}>
                    {Object.entries(user?.feature_access || {}).map(([feature, enabled]) => (
                        <Chip
                            key={feature}
                            label={`${feature}: ${enabled ? 'enabled' : 'disabled'}`}
                            size="small"
                            sx={{
                                bgcolor: enabled ? 'rgba(21,101,192,0.08)' : 'rgba(100,116,139,0.08)',
                                color: enabled ? '#1565C0' : '#64748b',
                                border: `1px solid ${enabled ? 'rgba(21,101,192,0.2)' : 'rgba(100,116,139,0.18)'}`,
                                fontWeight: 700,
                            }}
                        />
                    ))}
                </Box>
                <Typography sx={{ color: '#334155', fontSize: '0.88rem', fontWeight: 600 }}>
                    Monthly token allotment: {(user?.usage_summary?.monthly_token_limit || 0).toLocaleString()}
                </Typography>
                <Typography sx={{ color: '#64748b', fontSize: '0.82rem', mt: 0.3 }}>
                    Used this month: {(user?.usage_summary?.monthly_token_used || 0).toLocaleString()}
                </Typography>
            </Paper>

            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                    variant="contained"
                    startIcon={<SaveOutlined />}
                    onClick={handleSave}
                    sx={{ bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' }, textTransform: 'none', fontWeight: 700, px: 3, borderRadius: 2 }}
                >
                    Save Settings
                </Button>
            </Box>
        </Box>
    );
};

export default SettingsPage;

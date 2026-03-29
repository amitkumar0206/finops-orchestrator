import React, { useState } from 'react';
import {
    Box,
    Typography,
    Paper,
    Avatar,
    Divider,
    Button,
    TextField,
    Chip,
    Alert,
    LinearProgress,
    List,
    ListItem,
    ListItemText,
    ListItemIcon,
} from '@mui/material';
import {
    EditOutlined,
    SaveOutlined,
    CheckCircleOutline,
    AccessTimeOutlined,
    TrendingDown,
    CloudOutlined,
} from '@mui/icons-material';

const ProfilePage: React.FC = () => {
    const [editing, setEditing] = useState(false);
    const [saved, setSaved] = useState(false);
    const [profile, setProfile] = useState({
        name: 'Agranee A.',
        email: 'admin@aasmaa.ai',
        role: 'FinOps Admin',
        organization: 'Aasmaa Solutions',
        department: 'Cloud Engineering',
        phone: '+1 (555) 012-3456',
    });

    const handleSave = () => {
        setEditing(false);
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
    };

    const recentActivity = [
        { icon: <TrendingDown sx={{ fontSize: 18, color: '#1565C0' }} />, text: 'Ran cost analysis for Q1 2026', time: '2 hours ago' },
        { icon: <CloudOutlined sx={{ fontSize: 18, color: '#1565C0' }} />, text: 'Uploaded IaC file for review', time: 'Yesterday' },
        { icon: <CheckCircleOutline sx={{ fontSize: 18, color: '#2e7d32' }} />, text: 'Deployed aasmaa-services stack', time: '2 days ago' },
        { icon: <AccessTimeOutlined sx={{ fontSize: 18, color: '#ed6c02' }} />, text: 'Generated cost optimization report', time: '3 days ago' },
        { icon: <CheckCircleOutline sx={{ fontSize: 18, color: '#2e7d32' }} />, text: 'Reviewed EC2 rightsizing recommendations', time: '1 week ago' },
    ];

    const stats = [
        { label: 'Queries Run', value: '1,247', sub: 'All time' },
        { label: 'Cost Savings Found', value: '$48,320', sub: 'This month' },
        { label: 'Files Analyzed', value: '34', sub: 'IaC reviews' },
        { label: 'Reports Generated', value: '89', sub: 'All time' },
    ];

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

            {saved && (
                <Alert severity="success" sx={{ mb: 3, borderRadius: 2 }}>
                    Profile updated successfully.
                </Alert>
            )}

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
                            {profile.name.charAt(0)}
                        </Avatar>
                        <Box>
                            <Typography sx={{ fontWeight: 800, color: '#0f172a', fontSize: '1.2rem' }}>
                                {profile.name}
                            </Typography>
                            <Typography sx={{ color: '#64748b', fontSize: '0.9rem' }}>{profile.email}</Typography>
                            <Chip
                                label={profile.role}
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
                    <Button
                        variant={editing ? 'outlined' : 'contained'}
                        startIcon={editing ? <SaveOutlined /> : <EditOutlined />}
                        onClick={editing ? handleSave : () => setEditing(true)}
                        size="small"
                        sx={{
                            textTransform: 'none',
                            fontWeight: 700,
                            borderRadius: 2,
                            ...(editing
                                ? { borderColor: '#1565C0', color: '#1565C0' }
                                : { bgcolor: '#1565C0', '&:hover': { bgcolor: '#0D47A1' } }),
                        }}
                    >
                        {editing ? 'Save' : 'Edit Profile'}
                    </Button>
                </Box>

                <Divider sx={{ mb: 3 }} />

                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}>
                    {[
                        { key: 'name', label: 'Full Name' },
                        { key: 'email', label: 'Email Address' },
                        { key: 'role', label: 'Role' },
                        { key: 'organization', label: 'Organization' },
                        { key: 'department', label: 'Department' },
                        { key: 'phone', label: 'Phone Number' },
                    ].map((field) => (
                        <TextField
                            key={field.key}
                            label={field.label}
                            value={profile[field.key as keyof typeof profile]}
                            disabled={!editing}
                            size="small"
                            onChange={(e) => setProfile((p) => ({ ...p, [field.key]: e.target.value }))}
                            sx={{
                                '& .MuiOutlinedInput-root': { borderRadius: 2 },
                                '& .Mui-disabled': { WebkitTextFillColor: '#0f172a !important' },
                            }}
                        />
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
                    { label: 'API Queries', used: 1247, limit: 5000 },
                    { label: 'AI Tokens', used: 284000, limit: 500000 },
                    { label: 'File Uploads', used: 34, limit: 100 },
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
            </Paper>

            {/* Recent activity */}
            <Paper elevation={0} sx={{ border: '1px solid rgba(15,23,42,0.08)', borderRadius: 3, p: 3 }}>
                <Typography sx={{ fontWeight: 700, color: '#0f172a', mb: 1.5 }}>Recent Activity</Typography>
                <List disablePadding>
                    {recentActivity.map((item, i) => (
                        <React.Fragment key={i}>
                            {i > 0 && <Divider sx={{ my: 0.5 }} />}
                            <ListItem disablePadding sx={{ py: 0.75 }}>
                                <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
                                <ListItemText
                                    primary={item.text}
                                    secondary={item.time}
                                    primaryTypographyProps={{ fontSize: '0.875rem', fontWeight: 500, color: '#334155' }}
                                    secondaryTypographyProps={{ fontSize: '0.78rem', color: '#94a3b8' }}
                                />
                            </ListItem>
                        </React.Fragment>
                    ))}
                </List>
            </Paper>
        </Box>
    );
};

export default ProfilePage;

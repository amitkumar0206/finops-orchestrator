import React from 'react';
import { Avatar, Box, Button, Grid, Paper, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import {
    ForumOutlined as ForumOutlinedIcon,
    InsightsOutlined as InsightsOutlinedIcon,
    AutoFixHighOutlined as AutoFixHighOutlinedIcon,
    ReceiptLongOutlined as ReceiptLongOutlinedIcon,
    ArrowForward as ArrowForwardIcon,
    LogoutOutlined as LogoutOutlinedIcon,
    SettingsOutlined as SettingsOutlinedIcon,
    PersonOutlineOutlined as PersonOutlineOutlinedIcon,
    AdminPanelSettingsOutlined as AdminPanelSettingsOutlinedIcon,
} from '@mui/icons-material';
import { useAuth } from '../context/AuthContext';

const BRAND_BLUE = '#1565C0';
const BRAND_BLUE_DARK = '#0D47A1';

interface LandingPageProps {
    onLogout?: () => void;
}

const flowCards = [
    {
        key: '/chat',
        title: 'Chat',
        subtitle: 'Ask cloud cost questions in plain English',
        description: 'Get instant answers backed by live queries — charts, summaries, and next actions.',
        icon: <ForumOutlinedIcon sx={{ fontSize: 26 }} />,
    },
    {
        key: '/analyze',
        title: 'Analyze',
        subtitle: 'Inspect IaC and architecture decisions',
        description: 'Uncover risks, cost drivers, and optimization opportunities in your IaC files.',
        icon: <InsightsOutlinedIcon sx={{ fontSize: 26 }} />,
    },
    {
        key: '/cur-analysis',
        title: 'CUR Analysis',
        subtitle: 'Mine your AWS billing export',
        description: 'Upload a CUR CSV or run live Athena detectors to surface idle resources, commitment gaps, and savings.',
        icon: <ReceiptLongOutlinedIcon sx={{ fontSize: 26 }} />,
    },
    {
        key: '/generate',
        title: 'Generate',
        subtitle: 'Create cloud blueprints with AI',
        description: 'Generate Terraform or CloudFormation templates from a plain-English description.',
        icon: <AutoFixHighOutlinedIcon sx={{ fontSize: 26 }} />,
    },
] as const;

const LandingPage: React.FC<LandingPageProps> = ({ onLogout }) => {
    const { user, canAccess } = useAuth();
    const initials = (user?.full_name || user?.email || 'A')
        .split(' ')
        .map((part) => part.charAt(0).toUpperCase())
        .join('')
        .slice(0, 2);

    const visibleCards = flowCards.filter((card) => {
        if (card.key === '/chat') return canAccess('chat');
        if (card.key === '/analyze') return canAccess('analyze');
        if (card.key === '/cur-analysis') return canAccess('cur_analysis');
        if (card.key === '/generate') return canAccess('generate');
        return false;
    });

    const cardMd = visibleCards.length >= 4 ? 3 : 4;

    return (
        <Box
            sx={{
                minHeight: '100vh',
                bgcolor: '#f8fafc',
                px: { xs: 2, md: 4 },
                py: { xs: 2.5, md: 3.5 },
                backgroundImage: 'radial-gradient(circle at 12% 18%, rgba(21,101,192,0.13), transparent 42%), radial-gradient(circle at 88% 24%, rgba(13,71,161,0.08), transparent 38%), linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%)',
            }}
        >
            <Box sx={{ maxWidth: 1160, mx: 'auto' }}>
                <Paper
                    elevation={0}
                    sx={{
                        borderRadius: 4,
                        border: '1px solid rgba(15,23,42,0.08)',
                        bgcolor: 'rgba(255,255,255,0.88)',
                        backdropFilter: 'blur(8px)',
                        px: { xs: 1.25, sm: 2.25 },
                        py: 1,
                        mb: 2.5,
                    }}
                >
                    <Stack
                        direction={{ xs: 'column', md: 'row' }}
                        spacing={1.2}
                        sx={{ alignItems: { xs: 'stretch', md: 'center' }, justifyContent: 'space-between' }}
                    >
                        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
                            <img src="/aasmaa-logo.png" alt="aasmaa" style={{ height: 32 }} />
                            <Typography sx={{ color: '#64748b', fontSize: '0.85rem', fontWeight: 500, display: { xs: 'none', sm: 'block' } }}>
                                AI FinOps Command Center
                            </Typography>
                        </Stack>

                        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
                            <Button
                                component={RouterLink}
                                to="/profile"
                                startIcon={<PersonOutlineOutlinedIcon sx={{ fontSize: 18 }} />}
                                sx={{
                                    color: '#334155',
                                    textTransform: 'none',
                                    fontWeight: 600,
                                    borderRadius: 2,
                                    px: 1.5,
                                    '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' },
                                }}
                            >
                                Profile
                            </Button>
                            <Button
                                component={RouterLink}
                                to="/settings"
                                startIcon={<SettingsOutlinedIcon sx={{ fontSize: 18 }} />}
                                sx={{
                                    color: '#334155',
                                    textTransform: 'none',
                                    fontWeight: 600,
                                    borderRadius: 2,
                                    px: 1.5,
                                    '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' },
                                }}
                            >
                                Settings
                            </Button>
                            {canAccess('admin_console') && (
                                <Button
                                    component={RouterLink}
                                    to="/admin"
                                    startIcon={<AdminPanelSettingsOutlinedIcon sx={{ fontSize: 18 }} />}
                                    sx={{
                                        color: '#334155',
                                        textTransform: 'none',
                                        fontWeight: 600,
                                        borderRadius: 2,
                                        px: 1.5,
                                        '&:hover': { bgcolor: 'rgba(15,23,42,0.05)' },
                                    }}
                                >
                                    Admin
                                </Button>
                            )}
                            <Button
                                onClick={onLogout}
                                startIcon={<LogoutOutlinedIcon sx={{ fontSize: 18 }} />}
                                sx={{
                                    color: BRAND_BLUE_DARK,
                                    textTransform: 'none',
                                    fontWeight: 700,
                                    borderRadius: 2,
                                    px: 1.5,
                                    border: '1px solid rgba(21,101,192,0.28)',
                                    '&:hover': { bgcolor: 'rgba(21,101,192,0.08)', borderColor: BRAND_BLUE },
                                }}
                            >
                                Logout
                            </Button>
                            <Avatar sx={{ width: 34, height: 34, fontSize: '0.82rem', fontWeight: 700, bgcolor: BRAND_BLUE }}>{initials}</Avatar>
                        </Stack>
                    </Stack>
                </Paper>

                <Paper
                    elevation={0}
                    sx={{
                        p: { xs: 2.2, md: 3.2 },
                        borderRadius: 4,
                        border: '1px solid rgba(15,23,42,0.08)',
                        bgcolor: '#ffffff',
                        boxShadow: '0 18px 34px rgba(15,23,42,0.08)',
                        mb: 2.5,
                        overflow: 'hidden',
                    }}
                >
                    <Grid container spacing={{ xs: 2.25, md: 3.5 }} alignItems="center">
                        <Grid item xs={12} md={7}>
                            <Typography sx={{ color: BRAND_BLUE, fontWeight: 700, fontSize: '0.82rem', letterSpacing: 0.5, textTransform: 'uppercase', mb: 1.1 }}>
                                Cost Intelligence Platform
                            </Typography>
                            <Typography
                                variant="h3"
                                sx={{
                                    fontWeight: 800,
                                    color: '#0f172a',
                                    fontSize: { xs: '1.55rem', sm: '1.9rem', md: '2.25rem' },
                                    lineHeight: 1.16,
                                    maxWidth: 620,
                                }}
                            >
                                Operate cloud spend with executive clarity and engineering speed.
                            </Typography>
                            <Typography
                                sx={{
                                    mt: 1.4,
                                    color: '#64748b',
                                    fontSize: '0.94rem',
                                    lineHeight: 1.65,
                                    maxWidth: 610,
                                }}
                            >
                                Aasmaa combines conversational analysis, architecture insights, and AI blueprint generation into one professional FinOps workspace built for decisive teams.
                            </Typography>
                            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} sx={{ mt: 2.25 }}>
                                {canAccess('chat') && (
                                    <Button
                                        component={RouterLink}
                                        to="/chat"
                                        variant="contained"
                                        disableElevation
                                        endIcon={<ArrowForwardIcon sx={{ fontSize: '1rem !important' }} />}
                                        sx={{
                                            bgcolor: BRAND_BLUE,
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            borderRadius: 2,
                                            px: 2.1,
                                            py: 1,
                                            '&:hover': { bgcolor: BRAND_BLUE_DARK },
                                        }}
                                    >
                                        Open Cost Chat
                                    </Button>
                                )}
                                {canAccess('analyze') && (
                                    <Button
                                        component={RouterLink}
                                        to="/analyze"
                                        variant="outlined"
                                        sx={{
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            borderRadius: 2,
                                            px: 2.1,
                                            py: 1,
                                            color: BRAND_BLUE,
                                            borderColor: 'rgba(21,101,192,0.34)',
                                            '&:hover': { borderColor: BRAND_BLUE, bgcolor: 'rgba(21,101,192,0.06)' },
                                        }}
                                    >
                                        Start Analysis
                                    </Button>
                                )}
                                {canAccess('admin_console') && (
                                    <Button
                                        component={RouterLink}
                                        to="/admin"
                                        variant="outlined"
                                        sx={{
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            borderRadius: 2,
                                            px: 2.1,
                                            py: 1,
                                            color: '#0f172a',
                                            borderColor: 'rgba(15,23,42,0.16)',
                                            '&:hover': { borderColor: '#0f172a', bgcolor: 'rgba(15,23,42,0.04)' },
                                        }}
                                    >
                                        Open Admin Console
                                    </Button>
                                )}
                            </Stack>
                        </Grid>

                        <Grid item xs={12} md={5}>
                            <Paper
                                elevation={0}
                                sx={{
                                    p: 2,
                                    borderRadius: 3,
                                    border: '1px solid rgba(21,101,192,0.2)',
                                    background: 'linear-gradient(145deg, rgba(21,101,192,0.08) 0%, rgba(13,71,161,0.04) 100%)',
                                }}
                            >
                                <Typography sx={{ color: '#0f172a', fontWeight: 700, mb: 1.5, fontSize: '0.95rem' }}>
                                    Today at a glance
                                </Typography>
                                <Stack spacing={1}>
                                    {[
                                        { label: 'Optimization opportunities', value: '17', sub: '+4 since yesterday' },
                                        { label: 'Potential monthly savings', value: '$12.4K', sub: 'Across 9 services' },
                                        { label: 'IaC issues detected', value: '6', sub: '2 high-priority' },
                                    ].map((metric) => (
                                        <Box
                                            key={metric.label}
                                            sx={{
                                                p: 1.2,
                                                borderRadius: 2,
                                                bgcolor: '#ffffff',
                                                border: '1px solid rgba(15,23,42,0.08)',
                                            }}
                                        >
                                            <Typography sx={{ fontSize: '0.74rem', color: '#64748b', fontWeight: 600 }}>{metric.label}</Typography>
                                            <Typography sx={{ fontSize: '1.2rem', color: BRAND_BLUE_DARK, fontWeight: 800, mt: 0.25 }}>{metric.value}</Typography>
                                            <Typography sx={{ fontSize: '0.73rem', color: '#64748b' }}>{metric.sub}</Typography>
                                        </Box>
                                    ))}
                                </Stack>
                            </Paper>
                        </Grid>
                    </Grid>
                </Paper>

                <Grid container spacing={2} alignItems="stretch">
                    {visibleCards.map((card) => (
                        <Grid key={card.key} item xs={12} sm={6} md={cardMd} sx={{ display: 'flex' }}>
                            <Paper
                                elevation={0}
                                sx={{
                                    width: '100%',
                                    p: 2.25,
                                    borderRadius: 3,
                                    border: '1px solid #e2e8f0',
                                    bgcolor: '#ffffff',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    position: 'relative',
                                    overflow: 'hidden',
                                    transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                                    '&::before': {
                                        content: '""',
                                        position: 'absolute',
                                        top: 0,
                                        left: 0,
                                        right: 0,
                                        height: 3,
                                        bgcolor: BRAND_BLUE,
                                        opacity: 0,
                                        transition: 'opacity 0.2s ease',
                                    },
                                    '&:hover': {
                                        borderColor: BRAND_BLUE,
                                        boxShadow: '0 14px 32px rgba(15,23,42,0.1)',
                                        transform: 'translateY(-4px)',
                                    },
                                    '&:hover::before': {
                                        opacity: 1,
                                    },
                                }}
                            >
                                <Box
                                    sx={{
                                        width: 46,
                                        height: 46,
                                        borderRadius: 2,
                                        display: 'grid',
                                        placeItems: 'center',
                                        bgcolor: 'rgba(21,101,192,0.12)',
                                        color: BRAND_BLUE,
                                        mb: 1.5,
                                    }}
                                >
                                    {card.icon}
                                </Box>

                                <Typography variant="h6" sx={{ fontWeight: 700, color: '#0f172a', fontSize: '1.05rem', mb: 0.4 }}>
                                    {card.title}
                                </Typography>
                                <Typography sx={{ fontWeight: 600, color: BRAND_BLUE, fontSize: '0.84rem', mb: 0.75 }}>
                                    {card.subtitle}
                                </Typography>
                                <Typography sx={{ color: '#64748b', fontSize: '0.88rem', lineHeight: 1.6, flexGrow: 1 }}>
                                    {card.description}
                                </Typography>

                                <Box sx={{ pt: 1.75 }}>
                                    <Button
                                        component={RouterLink}
                                        to={card.key}
                                        endIcon={<ArrowForwardIcon sx={{ fontSize: '1rem !important' }} />}
                                        variant="contained"
                                        fullWidth
                                        disableElevation
                                        sx={{
                                            textTransform: 'none',
                                            fontWeight: 700,
                                            fontSize: '0.875rem',
                                            borderRadius: 1.75,
                                            py: 0.9,
                                            bgcolor: BRAND_BLUE,
                                            '&:hover': { bgcolor: BRAND_BLUE_DARK },
                                        }}
                                    >
                                        Launch {card.title}
                                    </Button>
                                </Box>
                            </Paper>
                        </Grid>
                    ))}
                </Grid>
            </Box>
        </Box>
    );
};

export default LandingPage;


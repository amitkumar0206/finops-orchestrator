import React from 'react';
import { Box, Button, Grid, Paper, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import {
    ForumOutlined as ForumOutlinedIcon,
    InsightsOutlined as InsightsOutlinedIcon,
    AutoFixHighOutlined as AutoFixHighOutlinedIcon,
    ArrowForward as ArrowForwardIcon,
} from '@mui/icons-material';

const BRAND_BLUE = '#1565C0';

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
        key: '/generate',
        title: 'Generate',
        subtitle: 'Create cloud blueprints with AI',
        description: 'Generate Terraform or CloudFormation templates from a plain-English description.',
        icon: <AutoFixHighOutlinedIcon sx={{ fontSize: 26 }} />,
    },
] as const;

const LandingPage: React.FC = () => {
    return (
        <Box sx={{ minHeight: '100vh', bgcolor: '#f8fafc', p: { xs: 2.5, md: 4 } }}>
            <Box sx={{ maxWidth: 1080, mx: 'auto' }}>
                {/* Logo + Hero */}
                <Box sx={{ mb: 4 }}>
                    <img src="/aasmaa-logo.png" alt="aasmaa" style={{ height: 32, marginBottom: 24 }} />
                    <Typography
                        variant="h4"
                        sx={{ fontWeight: 800, color: '#0f172a', fontSize: { xs: '1.6rem', md: '2rem' }, lineHeight: 1.2 }}
                    >
                        Cut cloud costs faster with instant, expert-level answers.
                    </Typography>
                    <Typography
                        variant="body2"
                        sx={{ mt: 1, color: '#64748b', fontSize: '0.95rem', maxWidth: 620 }}
                    >
                        Ask in plain English — get live charts, ranked insights, and recommendations in seconds.
                    </Typography>
                </Box>

                {/* Feature cards */}
                <Grid container spacing={2} alignItems="stretch">
                    {flowCards.map((card) => (
                        <Grid key={card.key} item xs={12} md={4} sx={{ display: 'flex' }}>
                            <Paper
                                elevation={0}
                                sx={{
                                    width: '100%',
                                    p: 2.5,
                                    borderRadius: 2.5,
                                    border: '1px solid #e2e8f0',
                                    bgcolor: '#ffffff',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    transition: 'box-shadow 0.18s ease, border-color 0.18s ease',
                                    '&:hover': {
                                        borderColor: BRAND_BLUE,
                                        boxShadow: `0 0 0 1px ${BRAND_BLUE}18, 0 8px 24px rgba(15,23,42,0.08)`,
                                    },
                                }}
                            >
                                {/* Icon */}
                                <Box
                                    sx={{
                                        width: 44,
                                        height: 44,
                                        borderRadius: 2,
                                        display: 'grid',
                                        placeItems: 'center',
                                        bgcolor: `${BRAND_BLUE}12`,
                                        color: BRAND_BLUE,
                                        mb: 1.5,
                                    }}
                                >
                                    {card.icon}
                                </Box>

                                <Typography variant="h6" sx={{ fontWeight: 700, color: '#0f172a', fontSize: '1.05rem', mb: 0.5 }}>
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
                                            fontWeight: 600,
                                            fontSize: '0.875rem',
                                            borderRadius: 1.5,
                                            py: 0.9,
                                            bgcolor: BRAND_BLUE,
                                            '&:hover': { bgcolor: '#0D47A1' },
                                        }}
                                    >
                                        Start {card.title}
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


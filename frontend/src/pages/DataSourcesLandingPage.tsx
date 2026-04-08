import React from 'react';
import { Box, Grid, Paper, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import SettingsSuggestOutlinedIcon from '@mui/icons-material/SettingsSuggestOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import ArrowForwardOutlinedIcon from '@mui/icons-material/ArrowForwardOutlined';

import DataSourcesNavBar from '../components/DataSources/DataSourcesNavBar';

const cards = [
    {
        title: 'Setup',
        subtitle: 'Create and validate data sources',
        description: 'Register AWS/Azure/GCP/generic sources and verify connection details before ingesting files.',
        to: '/data-sources/setup',
        icon: <SettingsSuggestOutlinedIcon sx={{ fontSize: 28 }} />,
    },
    {
        title: 'Upload',
        subtitle: 'Ingest billing exports',
        description: 'Select a configured source and upload billing files to run normalization for spend analysis.',
        to: '/data-sources/upload',
        icon: <UploadFileOutlinedIcon sx={{ fontSize: 28 }} />,
    },
    {
        title: 'Run History',
        subtitle: 'Review outcomes and validation',
        description: 'Track ingestion status, validation output, and normalized record counts for each run.',
        to: '/data-sources/runs',
        icon: <HistoryOutlinedIcon sx={{ fontSize: 28 }} />,
    },
];

const DataSourcesLandingPage: React.FC = () => {
    return (
        <Box sx={{ p: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a' }}>Data Sources</Typography>
            <Typography variant="body2" sx={{ color: '#475569', mb: 2 }}>
                Multi-cloud billing onboarding flow. Start with Setup, continue to Upload, then verify results in Run History.
            </Typography>

            <DataSourcesNavBar active="landing" />

            <Grid container spacing={2}>
                {cards.map((card) => (
                    <Grid key={card.title} item xs={12} md={4}>
                        <Paper
                            component={RouterLink}
                            to={card.to}
                            variant="outlined"
                            sx={{
                                p: 2.5,
                                borderRadius: 3,
                                textDecoration: 'none',
                                color: 'inherit',
                                display: 'block',
                                minHeight: 220,
                                transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                                '&:hover': {
                                    transform: 'translateY(-4px)',
                                    boxShadow: '0 14px 32px rgba(15,23,42,0.1)',
                                    borderColor: '#1565C0',
                                },
                            }}
                        >
                            <Stack spacing={1.25}>
                                <Box sx={{ color: '#1565C0' }}>{card.icon}</Box>
                                <Typography sx={{ fontWeight: 800, fontSize: '1.2rem' }}>{card.title}</Typography>
                                <Typography sx={{ fontWeight: 600, color: '#334155', fontSize: '0.95rem' }}>{card.subtitle}</Typography>
                                <Typography variant="body2" sx={{ color: '#64748b', minHeight: 64 }}>
                                    {card.description}
                                </Typography>
                                <Stack direction="row" alignItems="center" spacing={0.5} sx={{ color: '#1565C0', fontWeight: 700, fontSize: '0.9rem' }}>
                                    <span>Open</span>
                                    <ArrowForwardOutlinedIcon sx={{ fontSize: 16 }} />
                                </Stack>
                            </Stack>
                        </Paper>
                    </Grid>
                ))}
            </Grid>
        </Box>
    );
};

export default DataSourcesLandingPage;

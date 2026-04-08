import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Box, Grid, Paper, Stack, Typography } from '@mui/material';

import DataSourceWizard from '../components/DataSources/DataSourceWizard';
import DataSourcesNavBar from '../components/DataSources/DataSourcesNavBar';
import {
    DataSource,
    DataSourceDraft,
    createDataSource,
    getCapabilities,
    listDataSources,
    testDataSource,
} from '../lib/dataSourcesApi';

const DataSourcesSetupPage: React.FC = () => {
    const [sources, setSources] = useState<DataSource[]>([]);
    const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
    const [pageHint, setPageHint] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    const refreshSources = useCallback(async () => {
        try {
            const data = await listDataSources();
            setSources(data);
            if (data.length > 0 && !selectedSourceId) {
                setSelectedSourceId(data[0].id);
            }
            setPageHint(null);
        } catch {
            setSources([]);
            setPageHint('No sources are configured yet. Action item: create your first source using the setup wizard below.');
        }
    }, [selectedSourceId]);

    useEffect(() => {
        (async () => {
            try {
                setActionError(null);
                await getCapabilities();
                await refreshSources();
            } catch {
                setPageHint('Data Sources setup is not fully configured in this environment yet. You can still create your first source below.');
            }
        })();
    }, [refreshSources]);

    const saveDraft = async (payload: DataSourceDraft) => {
        setActionError(null);
        const created = await createDataSource(payload);
        setSelectedSourceId(created.id);
        await refreshSources();
        setMessage('Data source saved. Continue to Upload page to ingest billing files.');
    };

    const ingestNow = async (payload: DataSourceDraft) => {
        await saveDraft(payload);
        setMessage('Source saved. Next: open Upload page and submit a billing export file.');
    };

    const onTestConnection = async (payload: DataSourceDraft) => {
        setActionError(null);
        const created = await createDataSource(payload);
        setSelectedSourceId(created.id);
        const testResult = await testDataSource(created.id);
        await refreshSources();
        setMessage(testResult.success ? 'Connection test passed.' : 'Connection test failed.');
    };

    return (
        <Box sx={{ p: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a' }}>Data Sources Setup</Typography>
            <Typography variant="body2" sx={{ color: '#475569', mb: 2 }}>
                Step 1 of 3: register your billing sources.
            </Typography>

            <DataSourcesNavBar active="setup" />

            <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
                <Typography variant="body2" sx={{ color: '#475569' }}>
                    Use this page to create source definitions and test connection details. Once at least one source is added, continue to Upload.
                </Typography>
            </Paper>

            {pageHint && <Alert severity="info" sx={{ mb: 2 }}>{pageHint}</Alert>}
            {actionError && <Alert severity="warning" sx={{ mb: 2 }}>{actionError}</Alert>}
            {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}

            {sources.length === 0 && !pageHint && (
                <Alert severity="info" sx={{ mb: 2 }}>
                    Action item: add your first data source. After saving it, use the Upload page to ingest files.
                </Alert>
            )}

            <Grid container spacing={2.5}>
                <Grid item xs={12} md={7}>
                    <DataSourceWizard
                        onSaveDraft={saveDraft}
                        onIngestNow={ingestNow}
                        onTestConnection={onTestConnection}
                    />
                </Grid>
                <Grid item xs={12} md={5}>
                    <Paper variant="outlined" sx={{ p: 2 }}>
                        <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>Registered Sources</Typography>
                        <Stack spacing={1}>
                            {sources.length === 0 ? (
                                <Typography variant="body2" color="text.secondary">No sources yet.</Typography>
                            ) : sources.map((source) => (
                                <Paper
                                    key={source.id}
                                    variant="outlined"
                                    sx={{
                                        p: 1.5,
                                        borderColor: selectedSourceId === source.id ? '#1565C0' : undefined,
                                        cursor: 'pointer',
                                    }}
                                    onClick={() => setSelectedSourceId(source.id)}
                                >
                                    <Typography sx={{ fontWeight: 700 }}>{source.name}</Typography>
                                    <Typography variant="body2" color="text.secondary">
                                        {source.provider_type} | {source.connection_mode} | {source.status}
                                    </Typography>
                                </Paper>
                            ))}
                        </Stack>
                    </Paper>
                </Grid>
            </Grid>
        </Box>
    );
};

export default DataSourcesSetupPage;

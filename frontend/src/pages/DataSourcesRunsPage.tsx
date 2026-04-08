import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert,
    Box,
    FormControl,
    InputLabel,
    MenuItem,
    Paper,
    Select,
    Typography,
} from '@mui/material';

import DataSourcesNavBar from '../components/DataSources/DataSourcesNavBar';
import SourceRunHistoryTable from '../components/DataSources/SourceRunHistoryTable';
import { DataSource, DataSourceRun, getCapabilities, listDataSources, listRuns } from '../lib/dataSourcesApi';

const DataSourcesRunsPage: React.FC = () => {
    const [sources, setSources] = useState<DataSource[]>([]);
    const [runs, setRuns] = useState<DataSourceRun[]>([]);
    const [selectedSourceId, setSelectedSourceId] = useState<string>('');
    const [pageHint, setPageHint] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    const refreshSources = useCallback(async () => {
        try {
            const data = await listDataSources();
            setSources(data);
            if (!selectedSourceId && data.length > 0) {
                setSelectedSourceId(data[0].id);
            }
            setPageHint(null);
        } catch {
            setSources([]);
            setPageHint('Run history is empty until a source is configured and at least one upload is completed.');
        }
    }, [selectedSourceId]);

    useEffect(() => {
        (async () => {
            try {
                setActionError(null);
                await getCapabilities();
                await refreshSources();
            } catch {
                setPageHint('Run history cannot load yet. Action item: create a source in Setup and ingest at least one file in Upload.');
            }
        })();
    }, [refreshSources]);

    useEffect(() => {
        if (!selectedSourceId) {
            setRuns([]);
            return;
        }

        void (async () => {
            try {
                setActionError(null);
                const data = await listRuns(selectedSourceId);
                setRuns(data);
            } catch (e) {
                setActionError(e instanceof Error ? e.message : String(e));
            }
        })();
    }, [selectedSourceId]);

    return (
        <Box sx={{ p: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a' }}>Data Source Run History</Typography>
            <Typography variant="body2" sx={{ color: '#475569', mb: 2 }}>
                Step 3 of 3: review run status, validation output, and normalized record counts.
            </Typography>

            <DataSourcesNavBar active="runs" />

            <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
                <Typography variant="body2" sx={{ color: '#475569' }}>
                    This page is read-only for ingestion results. Use Setup to add sources and Upload to create runs.
                </Typography>
            </Paper>

            {pageHint && <Alert severity="info" sx={{ mb: 2 }}>{pageHint}</Alert>}
            {actionError && <Alert severity="warning" sx={{ mb: 2 }}>{actionError}</Alert>}

            {sources.length === 0 ? (
                <Alert severity="info">
                    No data sources available yet. Action item: create one in Setup and run an upload first.
                </Alert>
            ) : (
                <>
                    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
                        <FormControl fullWidth sx={{ maxWidth: 520 }}>
                            <InputLabel>Data source</InputLabel>
                            <Select
                                label="Data source"
                                value={selectedSourceId}
                                onChange={(e) => setSelectedSourceId(e.target.value)}
                            >
                                {sources.map((source) => (
                                    <MenuItem key={source.id} value={source.id}>
                                        {source.name} ({source.provider_type})
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    </Paper>

                    <SourceRunHistoryTable runs={runs} />
                </>
            )}
        </Box>
    );
};

export default DataSourcesRunsPage;

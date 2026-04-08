import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    FormControl,
    InputLabel,
    MenuItem,
    Paper,
    Select,
    Stack,
    Typography,
} from '@mui/material';
import DataSourcesNavBar from '../components/DataSources/DataSourcesNavBar';

import { DataSource, getCapabilities, listDataSources, uploadDataSourceFile } from '../lib/dataSourcesApi';

const DataSourcesUploadPage: React.FC = () => {
    const [sources, setSources] = useState<DataSource[]>([]);
    const [selectedSourceId, setSelectedSourceId] = useState<string>('');
    const [pageHint, setPageHint] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

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
            setPageHint(null); // shown inside the empty state instead
        }
    }, [selectedSourceId]);

    useEffect(() => {
        (async () => {
            try {
                setActionError(null);
                await getCapabilities();
                await refreshSources();
            } catch {
                setPageHint('Service unavailable — uploads require the backend to be configured with a database. Contact your administrator.');
            }
        })();
    }, [refreshSources]);

    const openUpload = async () => {
        if (!selectedSourceId) {
            setActionError('Choose a data source first.');
            return;
        }

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.csv,.gz,.json';
        input.onchange = async () => {
            const file = input.files?.[0];
            if (!file) return;

            try {
                setActionError(null);
                const out = await uploadDataSourceFile(selectedSourceId, file);
                setMessage(`Upload complete. Run ${String(out.run_id).slice(0, 8)} finished with status ${out.status}.`);
            } catch (e) {
                setActionError(e instanceof Error ? e.message : String(e));
            }
        };
        input.click();
    };

    return (
        <Box sx={{ p: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 800, color: '#0f172a' }}>Data Sources Upload</Typography>
            <Typography variant="body2" sx={{ color: '#475569', mb: 2 }}>
                Step 2 of 3: upload billing exports into a selected source.
            </Typography>

            <DataSourcesNavBar active="upload" />

            <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
                <Typography variant="body2" sx={{ color: '#475569' }}>
                    Use this page only for file ingestion. If there are no sources, create one on Setup first and return here.
                </Typography>
            </Paper>

            {actionError && <Alert severity="warning" sx={{ mb: 2 }}>{actionError}</Alert>}
            {message && <Alert severity="success" sx={{ mb: 2 }}>{message}</Alert>}

            {sources.length === 0 ? (
                <Alert severity="info" sx={{ mb: 2 }}>
                    {pageHint ?? 'No data sources are configured yet. Go to Setup to create your first source, then return here to upload a billing file.'}
                </Alert>
            ) : (
                <Paper variant="outlined" sx={{ p: 2.5, maxWidth: 760 }}>
                    <Stack spacing={2}>
                        <FormControl fullWidth>
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

                        <Button variant="contained" onClick={() => void openUpload()}>
                            Upload billing file
                        </Button>
                    </Stack>
                </Paper>
            )}
        </Box>
    );
};

export default DataSourcesUploadPage;

import React from 'react';
import { Button, Paper, Stack, Tooltip } from '@mui/material';
import SettingsSuggestOutlinedIcon from '@mui/icons-material/SettingsSuggestOutlined';
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined';
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined';
import { Link as RouterLink } from 'react-router-dom';

type DataSourcesNavTarget = 'landing' | 'setup' | 'upload' | 'runs';

interface Props {
    active: DataSourcesNavTarget;
}

const DataSourcesNavBar: React.FC<Props> = ({ active }) => {
    const items: Array<{
        key: DataSourcesNavTarget;
        label: string;
        to: string;
        icon: React.ReactNode;
    }> = [
            { key: 'landing', label: 'Overview', to: '/data-sources', icon: <SettingsSuggestOutlinedIcon fontSize="small" /> },
            { key: 'setup', label: 'Setup', to: '/data-sources/setup', icon: <SettingsSuggestOutlinedIcon fontSize="small" /> },
            { key: 'upload', label: 'Upload', to: '/data-sources/upload', icon: <UploadFileOutlinedIcon fontSize="small" /> },
            { key: 'runs', label: 'Run History', to: '/data-sources/runs', icon: <HistoryOutlinedIcon fontSize="small" /> },
        ];

    return (
        <Paper variant="outlined" sx={{ px: 1.25, py: 1, borderRadius: 2, mb: 2 }}>
            <Stack direction="row" spacing={1} flexWrap="wrap" justifyContent="flex-end">
                {items.map((item) => (
                    <Tooltip key={item.key} title={item.label}>
                        <Button
                            component={RouterLink}
                            to={item.to}
                            size="small"
                            startIcon={item.icon}
                            variant={active === item.key ? 'contained' : 'outlined'}
                            sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 1.5 }}
                        >
                            {item.label}
                        </Button>
                    </Tooltip>
                ))}
            </Stack>
        </Paper>
    );
};

export default DataSourcesNavBar;

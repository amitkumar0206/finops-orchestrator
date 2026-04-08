import React from 'react';
import { Chip, Tooltip } from '@mui/material';
import AccessTimeOutlinedIcon from '@mui/icons-material/AccessTimeOutlined';

interface Props {
    latestRunAt?: string | null;
    latestRunStatus?: string | null;
}

const rel = (iso?: string | null): string => {
    if (!iso) return 'No runs yet';
    const d = new Date(iso).getTime();
    const diffMs = Date.now() - d;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'Just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
};

const colorByStatus = (status?: string | null): 'default' | 'success' | 'warning' | 'error' => {
    if (status === 'completed') return 'success';
    if (status === 'running' || status === 'pending') return 'warning';
    if (status === 'failed') return 'error';
    return 'default';
};

const DataFreshnessBadge: React.FC<Props> = ({ latestRunAt, latestRunStatus }) => {
    const label = latestRunAt ? `Freshness: ${rel(latestRunAt)}` : 'Freshness: not ingested';
    const tooltip = latestRunAt
        ? `Last run ${new Date(latestRunAt).toLocaleString()} (${latestRunStatus || 'unknown'})`
        : 'No successful run yet';

    return (
        <Tooltip title={tooltip}>
            <Chip
                size="small"
                icon={<AccessTimeOutlinedIcon />}
                color={colorByStatus(latestRunStatus)}
                label={label}
                variant="outlined"
            />
        </Tooltip>
    );
};

export default DataFreshnessBadge;

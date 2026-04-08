import React from 'react';
import {
    Paper,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
    Chip,
} from '@mui/material';

export interface DataSourceRun {
    id: string;
    status: string;
    trigger_type: string;
    records_read: number;
    records_normalized: number;
    validation_errors: string[];
    created_at: string;
}

interface Props {
    runs: DataSourceRun[];
}

const SourceRunHistoryTable: React.FC<Props> = ({ runs }) => {
    return (
        <TableContainer component={Paper} variant="outlined">
            <Table size="small">
                <TableHead>
                    <TableRow>
                        <TableCell>Run</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Trigger</TableCell>
                        <TableCell align="right">Read</TableCell>
                        <TableCell align="right">Normalized</TableCell>
                        <TableCell>Validation</TableCell>
                        <TableCell>Created</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {runs.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={7}>
                                <Typography variant="body2" color="text.secondary">No runs yet.</Typography>
                            </TableCell>
                        </TableRow>
                    ) : runs.map((run) => (
                        <TableRow key={run.id}>
                            <TableCell sx={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.75rem' }}>{run.id.slice(0, 8)}</TableCell>
                            <TableCell><Chip size="small" label={run.status} /></TableCell>
                            <TableCell>{run.trigger_type}</TableCell>
                            <TableCell align="right">{run.records_read}</TableCell>
                            <TableCell align="right">{run.records_normalized}</TableCell>
                            <TableCell>{run.validation_errors?.[0] || 'None'}</TableCell>
                            <TableCell>{new Date(run.created_at).toLocaleString()}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    );
};

export default SourceRunHistoryTable;

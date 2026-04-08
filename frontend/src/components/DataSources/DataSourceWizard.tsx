import React, { useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    FormControl,
    FormControlLabel,
    InputLabel,
    MenuItem,
    Paper,
    Radio,
    RadioGroup,
    Select,
    Stack,
    Step,
    StepLabel,
    Stepper,
    TextField,
    Typography,
} from '@mui/material';

export interface DataSourceDraft {
    name: string;
    provider_type: 'aws_cur' | 'azure_export' | 'gcp_billing' | 'generic_cost';
    connection_mode: 'connected' | 'advisory_upload';
    credentials: Record<string, string>;
    scope: Record<string, string>;
    retention_months: number;
    status: 'draft' | 'active' | 'disabled';
}

interface Props {
    onSaveDraft: (payload: DataSourceDraft) => Promise<void>;
    onIngestNow: (payload: DataSourceDraft) => Promise<void>;
    onTestConnection: (payload: DataSourceDraft) => Promise<void>;
}

const steps = ['Choose Source', 'Connection Mode', 'Security + Scope', 'Validation'];

const credentialSchema = {
    aws_cur: ['bucket', 'prefix'],
    azure_export: ['tenant_id', 'client_id', 'scope'],
    gcp_billing: ['project_id', 'dataset'],
    generic_cost: [],
};

const DataSourceWizard: React.FC<Props> = ({ onSaveDraft, onIngestNow, onTestConnection }) => {
    const [activeStep, setActiveStep] = useState(0);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [draft, setDraft] = useState<DataSourceDraft>({
        name: '',
        provider_type: 'aws_cur',
        connection_mode: 'advisory_upload',
        credentials: {},
        scope: {},
        retention_months: 24,
        status: 'draft',
    });

    const requiredKeys = useMemo(() => credentialSchema[draft.provider_type], [draft.provider_type]);
    const missingCredentials = requiredKeys.filter((k) => draft.connection_mode === 'connected' && !draft.credentials[k]);
    const hasName = draft.name.trim().length >= 3;
    const hasVisibility = (draft.scope.visibility || '').trim().length > 0;
    const hasRetention = Number.isFinite(draft.retention_months) && draft.retention_months > 0;

    const canProceedStep0 = hasName;
    const canProceedStep1 = true;
    const canProceedStep2 = (draft.connection_mode !== 'connected' || missingCredentials.length === 0) && hasVisibility && hasRetention;
    const canValidate = hasName && missingCredentials.length === 0 && hasVisibility && hasRetention;

    const canProceedCurrentStep =
        activeStep === 0 ? canProceedStep0
            : activeStep === 1 ? canProceedStep1
                : activeStep === 2 ? canProceedStep2
                    : canValidate;

    const updateCredential = (key: string, value: string) => {
        setDraft((p) => ({ ...p, credentials: { ...p.credentials, [key]: value } }));
    };

    const save = async (mode: 'draft' | 'ingest' | 'test') => {
        setSaving(true);
        setError(null);
        try {
            if (mode === 'ingest') {
                await onIngestNow(draft);
            } else if (mode === 'test') {
                await onTestConnection(draft);
            } else {
                await onSaveDraft(draft);
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setSaving(false);
        }
    };

    return (
        <Paper variant="outlined" sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>Data Source Wizard</Typography>
            <Stepper activeStep={activeStep} alternativeLabel sx={{ mb: 2 }}>
                {steps.map((s) => (
                    <Step key={s}><StepLabel>{s}</StepLabel></Step>
                ))}
            </Stepper>

            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

            {activeStep === 0 && (
                <Stack spacing={2}>
                    <TextField
                        label="Source name"
                        value={draft.name}
                        onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
                        helperText="Plain-language name visible to your FinOps team"
                        error={!hasName && draft.name.length > 0}
                    />
                    {!hasName && (
                        <Alert severity="info">Enter a source name (minimum 3 characters) to continue.</Alert>
                    )}
                    <FormControl fullWidth>
                        <InputLabel>Provider</InputLabel>
                        <Select
                            label="Provider"
                            value={draft.provider_type}
                            onChange={(e) => setDraft((p) => ({ ...p, provider_type: e.target.value as DataSourceDraft['provider_type'] }))}
                        >
                            <MenuItem value="aws_cur">AWS CUR</MenuItem>
                            <MenuItem value="azure_export">Azure Export</MenuItem>
                            <MenuItem value="gcp_billing">GCP Billing Export</MenuItem>
                            <MenuItem value="generic_cost">SaaS / Any Cost CSV</MenuItem>
                        </Select>
                    </FormControl>
                </Stack>
            )}

            {activeStep === 1 && (
                <FormControl>
                    <RadioGroup
                        value={draft.connection_mode}
                        onChange={(e) => setDraft((p) => ({ ...p, connection_mode: e.target.value as DataSourceDraft['connection_mode'] }))}
                    >
                        <FormControlLabel value="connected" control={<Radio />} label="Connected mode" />
                        <FormControlLabel value="advisory_upload" control={<Radio />} label="Advisory upload" />
                    </RadioGroup>
                </FormControl>
            )}

            {activeStep === 2 && (
                <Stack spacing={2}>
                    <Alert severity="info">
                        Credentials are stored in redacted form and ingestion stays scoped to your organization.
                    </Alert>
                    {requiredKeys.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">No credentials required for this source type in advisory mode.</Typography>
                    ) : requiredKeys.map((key) => (
                        <TextField
                            key={key}
                            label={key}
                            value={draft.credentials[key] || ''}
                            onChange={(e) => updateCredential(key, e.target.value)}
                            required={draft.connection_mode === 'connected'}
                        />
                    ))}
                    <TextField
                        label="Org visibility"
                        value={draft.scope.visibility || 'org_admins'}
                        onChange={(e) => setDraft((p) => ({ ...p, scope: { ...p.scope, visibility: e.target.value } }))}
                        helperText="Example: org_admins, finops_team"
                        error={!hasVisibility}
                    />
                    <TextField
                        type="number"
                        label="Retention months"
                        value={draft.retention_months}
                        onChange={(e) => setDraft((p) => ({ ...p, retention_months: Number(e.target.value || 24) }))}
                        error={!hasRetention}
                    />
                    {!canProceedStep2 && (
                        <Alert severity="info">Complete required security/scope fields before continuing.</Alert>
                    )}
                </Stack>
            )}

            {activeStep === 3 && (
                <Stack spacing={1}>
                    <Typography variant="body2">Currency detected: <strong>Ready</strong></Typography>
                    <Typography variant="body2">Billing period fields: <strong>Ready</strong></Typography>
                    <Typography variant="body2">Account/project IDs: <strong>Ready</strong></Typography>
                    <Typography variant="body2">Service dimensions: <strong>Ready</strong></Typography>
                    <Typography variant="body2">Missing fields: <strong>{missingCredentials.length ? missingCredentials.join(', ') : 'none'}</strong></Typography>
                    {!canValidate && (
                        <Alert severity="warning">Please complete source name and required connection fields before ingesting.</Alert>
                    )}
                </Stack>
            )}

            <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 2.5 }}>
                <Button onClick={() => setActiveStep((s) => Math.max(0, s - 1))} disabled={activeStep === 0 || saving}>Back</Button>
                <Stack direction="row" spacing={1}>
                    <Button variant="outlined" onClick={() => void save('draft')} disabled={saving}>Save draft</Button>
                    <Button variant="outlined" onClick={() => void save('test')} disabled={saving || !canValidate}>Test connection</Button>
                    {activeStep < steps.length - 1 ? (
                        <Button
                            variant="contained"
                            onClick={() => setActiveStep((s) => Math.min(steps.length - 1, s + 1))}
                            disabled={!canProceedCurrentStep || saving}
                        >
                            Next
                        </Button>
                    ) : (
                        <Button variant="contained" onClick={() => void save('ingest')} disabled={saving || !canValidate}>Ingest now</Button>
                    )}
                </Stack>
            </Box>
        </Paper>
    );
};

export default DataSourceWizard;

import { apiFetch } from './api';

export type DataSource = {
    id: string;
    name: string;
    provider_type: string;
    connection_mode: string;
    status: string;
    latest_run_status?: string | null;
    latest_run_at?: string | null;
};

export type DataSourceRun = {
    id: string;
    status: string;
    trigger_type: string;
    records_read: number;
    records_normalized: number;
    validation_errors: string[];
    created_at: string;
};

export type DataSourceDraft = {
    name: string;
    provider_type: 'aws_cur' | 'azure_export' | 'gcp_billing' | 'generic_cost';
    connection_mode: 'connected' | 'advisory_upload';
    credentials: Record<string, string>;
    scope: Record<string, string>;
    retention_months: number;
    status: 'draft' | 'active' | 'disabled';
};

const parseError = async (resp: Response, fallback: string): Promise<string> => {
    try {
        const text = await resp.text();
        if (!text) return fallback;
        const body = JSON.parse(text);
        return body?.detail || fallback;
    } catch {
        return fallback;
    }
};

export const getCapabilities = async (): Promise<void> => {
    const cap = await apiFetch('/api/v1/data-sources/capabilities');
    if (!cap.ok) {
        throw new Error(await parseError(cap, 'Data Sources feature is unavailable'));
    }
};

export const listDataSources = async (): Promise<DataSource[]> => {
    const resp = await apiFetch('/api/v1/data-sources');
    if (!resp.ok) {
        throw new Error(await parseError(resp, 'Failed to load data sources'));
    }
    return resp.json();
};

export const listRuns = async (dataSourceId: string): Promise<DataSourceRun[]> => {
    const resp = await apiFetch(`/api/v1/data-sources/${dataSourceId}/runs`);
    if (!resp.ok) {
        throw new Error(await parseError(resp, 'Failed to load source run history'));
    }
    return resp.json();
};

export const createDataSource = async (payload: DataSourceDraft): Promise<DataSource> => {
    const resp = await apiFetch('/api/v1/data-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!resp.ok) {
        throw new Error(await parseError(resp, 'Failed to save data source draft'));
    }
    return resp.json();
};

export const testDataSource = async (dataSourceId: string): Promise<{ success: boolean }> => {
    const resp = await apiFetch(`/api/v1/data-sources/${dataSourceId}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
    });
    if (!resp.ok) {
        throw new Error(await parseError(resp, 'Connection test failed'));
    }
    return resp.json();
};

export const uploadDataSourceFile = async (
    dataSourceId: string,
    file: File,
): Promise<{ run_id: string; status: string }> => {
    const form = new FormData();
    form.append('data_source_id', dataSourceId);
    form.append('file', file);
    const resp = await apiFetch('/api/v1/data-sources/upload', {
        method: 'POST',
        body: form,
    });
    if (!resp.ok) {
        throw new Error(await parseError(resp, 'Upload failed'));
    }
    return resp.json();
};

import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  TextField,
  FormControlLabel,
  Checkbox,
  Typography,
  Alert,
  CircularProgress,
  Autocomplete,
  Chip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';

interface Account {
  id: string;
  account_id: string;
  account_name: string;
}

interface SavedView {
  id: string;
  name: string;
  description?: string;
  account_ids: string[];
  default_time_range?: Record<string, unknown>;
  is_default: boolean;
  is_personal: boolean;
  expires_at?: string;
}

interface SavedViewEditorProps {
  view?: SavedView | null;
  onSave: (view: Partial<SavedView>) => Promise<void>;
  onCancel: () => void;
}

const SavedViewEditor: React.FC<SavedViewEditorProps> = ({ view, onSave, onCancel }) => {
  const [name, setName] = useState(view?.name || '');
  const [description, setDescription] = useState(view?.description || '');
  const [selectedAccounts, setSelectedAccounts] = useState<Account[]>([]);
  const [availableAccounts, setAvailableAccounts] = useState<Account[]>([]);
  const [isDefault, setIsDefault] = useState(view?.is_default || false);
  const [isPersonal, setIsPersonal] = useState(view?.is_personal || false);
  const [expiresAt, setExpiresAt] = useState<Date | null>(
    view?.expires_at ? new Date(view.expires_at) : null
  );
  const [timeRangePreset, setTimeRangePreset] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingAccounts, setLoadingAccounts] = useState(true);

  const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchAccounts();
  }, []);

  const fetchAccounts = async () => {
    setLoadingAccounts(true);
    try {
      // This would call an accounts API endpoint
      // For now, using mock data or scope API
      const response = await fetch(`${apiBaseUrl}/api/v1/scope/accounts`);
      if (response.ok) {
        const data = await response.json();
        // Transform account IDs to account objects
        const accounts = data.accounts.map((accountId: string, index: number) => ({
          id: `account-${index}`,
          account_id: accountId,
          account_name: accountId, // Would ideally have the name
        }));
        setAvailableAccounts(accounts);

        // Set selected accounts if editing
        if (view?.account_ids) {
          const selected = accounts.filter((a: Account) =>
            view.account_ids.includes(a.id) || view.account_ids.includes(a.account_id)
          );
          setSelectedAccounts(selected);
        }
      }
    } catch (err) {
      console.error('Failed to fetch accounts:', err);
    } finally {
      setLoadingAccounts(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError('Name is required');
      return;
    }

    if (selectedAccounts.length === 0) {
      setError('At least one account must be selected');
      return;
    }

    setLoading(true);

    try {
      const viewData: Partial<SavedView> = {
        name: name.trim(),
        description: description.trim() || undefined,
        account_ids: selectedAccounts.map((a) => a.id || a.account_id),
        is_default: isDefault,
        is_personal: isPersonal,
        expires_at: expiresAt ? expiresAt.toISOString() : undefined,
      };

      if (timeRangePreset) {
        viewData.default_time_range = getTimeRangeFromPreset(timeRangePreset);
      }

      await onSave(viewData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save view');
    } finally {
      setLoading(false);
    }
  };

  const getTimeRangeFromPreset = (preset: string): Record<string, unknown> => {
    const now = new Date();
    switch (preset) {
      case 'last7days':
        return { days: 7, type: 'relative' };
      case 'last30days':
        return { days: 30, type: 'relative' };
      case 'last90days':
        return { days: 90, type: 'relative' };
      case 'thisMonth':
        return { type: 'this_month' };
      case 'lastMonth':
        return { type: 'last_month' };
      case 'thisQuarter':
        return { type: 'this_quarter' };
      default:
        return {};
    }
  };

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns}>
      <Box component="form" onSubmit={handleSubmit} sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 3 }}>
          {view ? 'Edit Saved View' : 'Create Saved View'}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <TextField
          label="View Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          fullWidth
          required
          sx={{ mb: 2 }}
        />

        <TextField
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          fullWidth
          multiline
          rows={2}
          sx={{ mb: 2 }}
        />

        <Autocomplete
          multiple
          options={availableAccounts}
          value={selectedAccounts}
          onChange={(_, newValue) => setSelectedAccounts(newValue)}
          getOptionLabel={(option) => `${option.account_name} (${option.account_id})`}
          loading={loadingAccounts}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Select Accounts"
              placeholder="Search accounts..."
              required
            />
          )}
          renderTags={(value, getTagProps) =>
            value.map((option, index) => (
              <Chip
                {...getTagProps({ index })}
                key={option.account_id}
                label={option.account_id}
                size="small"
              />
            ))
          }
          sx={{ mb: 2 }}
        />

        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>Default Time Range</InputLabel>
          <Select
            value={timeRangePreset}
            onChange={(e) => setTimeRangePreset(e.target.value)}
            label="Default Time Range"
          >
            <MenuItem value="">None (use query default)</MenuItem>
            <MenuItem value="last7days">Last 7 days</MenuItem>
            <MenuItem value="last30days">Last 30 days</MenuItem>
            <MenuItem value="last90days">Last 90 days</MenuItem>
            <MenuItem value="thisMonth">This month</MenuItem>
            <MenuItem value="lastMonth">Last month</MenuItem>
            <MenuItem value="thisQuarter">This quarter</MenuItem>
          </Select>
        </FormControl>

        <DatePicker
          label="Expiration Date (optional)"
          value={expiresAt}
          onChange={(newValue) => setExpiresAt(newValue)}
          slotProps={{
            textField: {
              fullWidth: true,
              sx: { mb: 2 },
            },
          }}
          minDate={new Date()}
        />

        <Box sx={{ mb: 2 }}>
          <FormControlLabel
            control={
              <Checkbox
                checked={isPersonal}
                onChange={(e) => {
                  setIsPersonal(e.target.checked);
                  if (e.target.checked) setIsDefault(false);
                }}
              />
            }
            label="Personal view (only visible to me)"
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={isDefault}
                onChange={(e) => {
                  setIsDefault(e.target.checked);
                  if (e.target.checked) setIsPersonal(false);
                }}
                disabled={isPersonal}
              />
            }
            label="Set as organization default"
          />
        </Box>

        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
          <Button onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="contained"
            disabled={loading || selectedAccounts.length === 0}
          >
            {loading ? <CircularProgress size={20} /> : view ? 'Update' : 'Create'}
          </Button>
        </Box>
      </Box>
    </LocalizationProvider>
  );
};

export default SavedViewEditor;

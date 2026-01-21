import React, { useState, useEffect } from 'react';
import {
  Box,
  Chip,
  IconButton,
  Menu,
  MenuItem,
  Typography,
  Divider,
  Tooltip,
  CircularProgress,
} from '@mui/material';
import {
  Business as OrgIcon,
  ViewList as ViewIcon,
  AccountBalance as AccountIcon,
  ExpandMore as ExpandMoreIcon,
  Schedule as ScheduleIcon,
} from '@mui/icons-material';

interface ActiveView {
  id: string | null;
  name: string | null;
  expires_at: string | null;
}

interface EffectiveScope {
  organization_id: string | null;
  organization_name: string | null;
  allowed_account_ids: string[];
  account_count: number;
  active_view: ActiveView | null;
  effective_time_range: Record<string, unknown> | null;
  effective_filters: Record<string, unknown> | null;
  is_admin: boolean;
  org_role: string;
  user_email: string;
}

interface SavedView {
  id: string;
  name: string;
  description?: string;
  account_count: number;
  is_default: boolean;
  is_personal: boolean;
  expires_at?: string;
}

interface ScopeIndicatorProps {
  onScopeChange?: () => void;
}

const ScopeIndicator: React.FC<ScopeIndicatorProps> = ({ onScopeChange }) => {
  const [scope, setScope] = useState<EffectiveScope | null>(null);
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const [loading, setLoading] = useState(true);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [changingView, setChangingView] = useState(false);

  const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchScope();
    fetchSavedViews();
  }, []);

  const fetchScope = async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/scope/current`);
      if (response.ok) {
        const data = await response.json();
        setScope(data);
      }
    } catch (error) {
      console.error('Failed to fetch scope:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchSavedViews = async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/views`);
      if (response.ok) {
        const data = await response.json();
        setSavedViews(data);
      }
    } catch (error) {
      console.error('Failed to fetch saved views:', error);
    }
  };

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleViewChange = async (viewId: string | null) => {
    setChangingView(true);
    handleClose();

    try {
      if (viewId) {
        await fetch(`${apiBaseUrl}/api/v1/views/active/${viewId}`, {
          method: 'PUT',
        });
      } else {
        await fetch(`${apiBaseUrl}/api/v1/views/active`, {
          method: 'DELETE',
        });
      }

      await fetchScope();
      onScopeChange?.();
    } catch (error) {
      console.error('Failed to change view:', error);
    } finally {
      setChangingView(false);
    }
  };

  const formatExpiration = (expiresAt: string) => {
    const date = new Date(expiresAt);
    const now = new Date();
    const diffDays = Math.ceil((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) return 'Expired';
    if (diffDays === 0) return 'Expires today';
    if (diffDays === 1) return 'Expires tomorrow';
    if (diffDays <= 7) return `Expires in ${diffDays} days`;
    return `Expires ${date.toLocaleDateString()}`;
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <CircularProgress size={16} sx={{ color: 'white' }} />
      </Box>
    );
  }

  if (!scope || !scope.organization_id) {
    return null;
  }

  const activeViewName = scope.active_view?.name || 'All Accounts';
  const accountLabel = scope.account_count === 1 ? '1 account' : `${scope.account_count} accounts`;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {/* Organization chip */}
      <Tooltip title={`Organization: ${scope.organization_name || 'Unknown'}`}>
        <Chip
          icon={<OrgIcon sx={{ fontSize: 16 }} />}
          label={scope.organization_name || 'Org'}
          size="small"
          sx={{
            bgcolor: 'rgba(255, 255, 255, 0.15)',
            color: 'white',
            '& .MuiChip-icon': { color: 'white' },
          }}
        />
      </Tooltip>

      {/* View selector chip */}
      <Tooltip title="Click to change scope view">
        <Chip
          icon={changingView ? <CircularProgress size={14} sx={{ color: 'white' }} /> : <ViewIcon sx={{ fontSize: 16 }} />}
          label={activeViewName}
          size="small"
          deleteIcon={<ExpandMoreIcon sx={{ color: 'white !important' }} />}
          onDelete={handleClick}
          onClick={handleClick}
          sx={{
            bgcolor: 'rgba(255, 255, 255, 0.25)',
            color: 'white',
            cursor: 'pointer',
            '& .MuiChip-icon': { color: 'white' },
            '&:hover': {
              bgcolor: 'rgba(255, 255, 255, 0.35)',
            },
          }}
        />
      </Tooltip>

      {/* Account count */}
      <Tooltip title={`Querying ${accountLabel}`}>
        <Chip
          icon={<AccountIcon sx={{ fontSize: 16 }} />}
          label={accountLabel}
          size="small"
          sx={{
            bgcolor: 'rgba(255, 255, 255, 0.15)',
            color: 'white',
            '& .MuiChip-icon': { color: 'white' },
          }}
        />
      </Tooltip>

      {/* Expiration warning */}
      {scope.active_view?.expires_at && (
        <Tooltip title={formatExpiration(scope.active_view.expires_at)}>
          <Chip
            icon={<ScheduleIcon sx={{ fontSize: 16 }} />}
            label={formatExpiration(scope.active_view.expires_at)}
            size="small"
            sx={{
              bgcolor: 'rgba(255, 193, 7, 0.3)',
              color: 'white',
              '& .MuiChip-icon': { color: 'white' },
            }}
          />
        </Tooltip>
      )}

      {/* View selection menu */}
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleClose}
        PaperProps={{
          sx: { minWidth: 250 },
        }}
      >
        <Typography variant="subtitle2" sx={{ px: 2, py: 1, color: 'text.secondary' }}>
          Select Scope View
        </Typography>
        <Divider />

        {/* All accounts option */}
        <MenuItem
          onClick={() => handleViewChange(null)}
          selected={!scope.active_view?.id}
        >
          <Box>
            <Typography variant="body2">All Accounts</Typography>
            <Typography variant="caption" color="text.secondary">
              Query all accessible accounts
            </Typography>
          </Box>
        </MenuItem>

        <Divider />

        {/* Saved views */}
        {savedViews.length === 0 ? (
          <MenuItem disabled>
            <Typography variant="body2" color="text.secondary">
              No saved views available
            </Typography>
          </MenuItem>
        ) : (
          savedViews.map((view) => (
            <MenuItem
              key={view.id}
              onClick={() => handleViewChange(view.id)}
              selected={scope.active_view?.id === view.id}
            >
              <Box sx={{ width: '100%' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="body2">{view.name}</Typography>
                  {view.is_default && (
                    <Chip label="Default" size="small" sx={{ height: 18, fontSize: 10 }} />
                  )}
                  {view.is_personal && (
                    <Chip label="Personal" size="small" color="info" sx={{ height: 18, fontSize: 10 }} />
                  )}
                </Box>
                <Typography variant="caption" color="text.secondary">
                  {view.account_count} account{view.account_count !== 1 ? 's' : ''}
                  {view.expires_at && ` - ${formatExpiration(view.expires_at)}`}
                </Typography>
              </Box>
            </MenuItem>
          ))
        )}
      </Menu>
    </Box>
  );
};

export default ScopeIndicator;

import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  IconButton,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  CircularProgress,
  Alert,
  Tooltip,
} from '@mui/material';
import {
  Edit as EditIcon,
  Delete as DeleteIcon,
  Star as StarIcon,
  Person as PersonIcon,
  Group as GroupIcon,
  Schedule as ScheduleIcon,
  Add as AddIcon,
} from '@mui/icons-material';

interface SavedView {
  id: string;
  name: string;
  description?: string;
  account_ids: string[];
  account_count: number;
  default_time_range?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  is_default: boolean;
  is_personal: boolean;
  expires_at?: string;
  created_at?: string;
  created_by_email?: string;
}

interface SavedViewsListProps {
  onEdit?: (view: SavedView) => void;
  onCreateNew?: () => void;
  onViewSelect?: (viewId: string) => void;
}

const SavedViewsList: React.FC<SavedViewsListProps> = ({
  onEdit,
  onCreateNew,
  onViewSelect,
}) => {
  const [views, setViews] = useState<SavedView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [viewToDelete, setViewToDelete] = useState<SavedView | null>(null);
  const [deleting, setDeleting] = useState(false);

  const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchViews();
  }, []);

  const fetchViews = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/views`);
      if (!response.ok) {
        throw new Error('Failed to fetch saved views');
      }
      const data = await response.json();
      setViews(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteClick = (view: SavedView) => {
    setViewToDelete(view);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!viewToDelete) return;

    setDeleting(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/views/${viewToDelete.id}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error('Failed to delete view');
      }

      await fetchViews();
      setDeleteDialogOpen(false);
      setViewToDelete(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete view');
    } finally {
      setDeleting(false);
    }
  };

  const formatExpiration = (expiresAt: string) => {
    const date = new Date(expiresAt);
    const now = new Date();
    const diffDays = Math.ceil((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) return 'Expired';
    if (diffDays === 0) return 'Expires today';
    if (diffDays === 1) return 'Tomorrow';
    if (diffDays <= 7) return `${diffDays} days`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">Saved Views</Typography>
          {onCreateNew && (
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={onCreateNew}
              size="small"
            >
              New View
            </Button>
          )}
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {views.length === 0 ? (
          <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            No saved views yet. Create one to scope your cost queries.
          </Typography>
        ) : (
          <List>
            {views.map((view) => (
              <ListItem
                key={view.id}
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  mb: 1,
                  '&:hover': {
                    bgcolor: 'action.hover',
                    cursor: 'pointer',
                  },
                }}
                onClick={() => onViewSelect?.(view.id)}
              >
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="subtitle2">{view.name}</Typography>
                      {view.is_default && (
                        <Tooltip title="Organization default view">
                          <Chip
                            icon={<StarIcon sx={{ fontSize: 14 }} />}
                            label="Default"
                            size="small"
                            color="warning"
                            sx={{ height: 20 }}
                          />
                        </Tooltip>
                      )}
                      {view.is_personal && (
                        <Tooltip title="Personal view">
                          <Chip
                            icon={<PersonIcon sx={{ fontSize: 14 }} />}
                            label="Personal"
                            size="small"
                            color="info"
                            sx={{ height: 20 }}
                          />
                        </Tooltip>
                      )}
                      {!view.is_personal && !view.is_default && (
                        <Tooltip title="Shared view">
                          <Chip
                            icon={<GroupIcon sx={{ fontSize: 14 }} />}
                            label="Shared"
                            size="small"
                            sx={{ height: 20 }}
                          />
                        </Tooltip>
                      )}
                    </Box>
                  }
                  secondary={
                    <Box sx={{ mt: 0.5 }}>
                      <Typography variant="body2" color="text.secondary">
                        {view.account_count} account{view.account_count !== 1 ? 's' : ''}
                        {view.description && ` - ${view.description}`}
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                        {view.expires_at && (
                          <Chip
                            icon={<ScheduleIcon sx={{ fontSize: 12 }} />}
                            label={formatExpiration(view.expires_at)}
                            size="small"
                            color={new Date(view.expires_at) < new Date() ? 'error' : 'default'}
                            sx={{ height: 18, fontSize: 11 }}
                          />
                        )}
                        {view.created_by_email && (
                          <Typography variant="caption" color="text.secondary">
                            by {view.created_by_email}
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  }
                />
                <ListItemSecondaryAction>
                  {onEdit && (
                    <IconButton
                      edge="end"
                      aria-label="edit"
                      onClick={(e) => {
                        e.stopPropagation();
                        onEdit(view);
                      }}
                      size="small"
                      sx={{ mr: 1 }}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  )}
                  <IconButton
                    edge="end"
                    aria-label="delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteClick(view);
                    }}
                    size="small"
                    color="error"
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        )}

        {/* Delete Confirmation Dialog */}
        <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
          <DialogTitle>Delete Saved View</DialogTitle>
          <DialogContent>
            <Typography>
              Are you sure you want to delete "{viewToDelete?.name}"? This action cannot be undone.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setDeleteDialogOpen(false)} disabled={deleting}>
              Cancel
            </Button>
            <Button
              onClick={handleDeleteConfirm}
              color="error"
              variant="contained"
              disabled={deleting}
            >
              {deleting ? <CircularProgress size={20} /> : 'Delete'}
            </Button>
          </DialogActions>
        </Dialog>
      </CardContent>
    </Card>
  );
};

export default SavedViewsList;

import React, { useState, useEffect } from 'react';
import {
  Box,
  Paper,
  Typography,
  Chip,
  Button,
  IconButton,
  Divider,
  Grid,
  Card,
  CardContent,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  CircularProgress,
  Alert,
  Link,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
} from '@mui/material';
import {
  ArrowBack as BackIcon,
  CheckCircle as AcceptIcon,
  Cancel as DismissIcon,
  PlayArrow as ImplementIcon,
  Done as DoneIcon,
  ExpandMore as ExpandMoreIcon,
  OpenInNew as ExternalLinkIcon,
  ContentCopy as CopyIcon,
  AttachMoney as MoneyIcon,
  Speed as EffortIcon,
  Warning as RiskIcon,
  Schedule as TimeIcon,
  Code as CodeIcon,
  Storage as ResourceIcon,
} from '@mui/icons-material';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface ImplementationStep {
  step: number;
  action: string;
  notes?: string;
}

interface Evidence {
  api_trace?: Record<string, unknown>;
  cur_validation_sql?: string;
  utilization_metrics?: Record<string, unknown>;
  lookback_period_days?: number;
  additional_data?: Record<string, unknown>;
}

interface OpportunityDetailData {
  id: string;
  account_id: string;
  organization_id?: string;
  title: string;
  description: string;
  category: string;
  source: string;
  source_id?: string;
  service: string;
  resource_id?: string;
  resource_name?: string;
  resource_type?: string;
  region?: string;
  estimated_monthly_savings?: number;
  estimated_annual_savings?: number;
  savings_percentage?: number;
  current_monthly_cost?: number;
  projected_monthly_cost?: number;
  savings_currency: string;
  effort_level?: string;
  risk_level?: string;
  status: string;
  status_reason?: string;
  status_changed_by?: string;
  status_changed_at?: string;
  priority_score?: number;
  confidence_score?: number;
  tags?: string[];
  first_detected_at: string;
  last_seen_at: string;
  expires_at?: string;
  created_at: string;
  updated_at: string;
  deep_link?: string;
  implementation_steps?: ImplementationStep[];
  prerequisites?: string[];
  evidence?: Evidence;
  api_trace?: Record<string, unknown>;
  cur_validation_sql?: string;
  metadata?: Record<string, unknown>;
}

interface OpportunityDetailProps {
  opportunityId: string;
  onBack: () => void;
  onStatusChange?: () => void;
}

const statusColors: Record<string, 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'> = {
  open: 'info',
  accepted: 'primary',
  in_progress: 'warning',
  implemented: 'success',
  dismissed: 'default',
  expired: 'error',
};

const effortColors: Record<string, string> = {
  low: '#4caf50',
  medium: '#ff9800',
  high: '#f44336',
};

const OpportunityDetail: React.FC<OpportunityDetailProps> = ({
  opportunityId,
  onBack,
  onStatusChange,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [opportunity, setOpportunity] = useState<OpportunityDetailData | null>(null);
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);
  const [newStatus, setNewStatus] = useState<string>('');
  const [statusReason, setStatusReason] = useState<string>('');
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    const fetchOpportunity = async () => {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(`/api/v1/opportunities/${opportunityId}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch opportunity: ${response.statusText}`);
        }
        const data = await response.json();
        setOpportunity(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchOpportunity();
  }, [opportunityId]);

  const handleStatusUpdate = async () => {
    if (!newStatus) return;

    setUpdating(true);
    try {
      const response = await fetch(`/api/v1/opportunities/${opportunityId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          status: newStatus,
          reason: statusReason || undefined,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to update status');
      }

      const updatedOpportunity = await response.json();
      setOpportunity(updatedOpportunity);
      setStatusDialogOpen(false);
      setStatusReason('');
      onStatusChange?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update status');
    } finally {
      setUpdating(false);
    }
  };

  const handleQuickAction = (status: string) => {
    setNewStatus(status);
    setStatusDialogOpen(true);
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const formatCurrency = (value: number | null | undefined) => {
    if (value === null || value === undefined) return '-';
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !opportunity) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="error">{error || 'Opportunity not found'}</Alert>
        <Button startIcon={<BackIcon />} onClick={onBack} sx={{ mt: 2 }}>
          Back to list
        </Button>
      </Box>
    );
  }

  const curSql = opportunity.cur_validation_sql || opportunity.evidence?.cur_validation_sql;

  return (
    <Box sx={{ p: 2 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 3 }}>
        <IconButton onClick={onBack} sx={{ mt: 0.5 }}>
          <BackIcon />
        </IconButton>
        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 600, mb: 1 }}>
            {opportunity.title}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip
              label={opportunity.status}
              color={statusColors[opportunity.status] || 'default'}
              sx={{ textTransform: 'capitalize' }}
            />
            <Chip label={opportunity.service} variant="outlined" />
            <Chip
              label={opportunity.category.replace('_', ' ')}
              variant="outlined"
              sx={{ textTransform: 'capitalize' }}
            />
            {opportunity.effort_level && (
              <Chip
                label={`${opportunity.effort_level} effort`}
                sx={{
                  bgcolor: effortColors[opportunity.effort_level] || '#9e9e9e',
                  color: 'white',
                  textTransform: 'capitalize',
                }}
              />
            )}
          </Box>
        </Box>

        {/* Quick Actions */}
        {opportunity.status === 'open' && (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="contained"
              color="primary"
              startIcon={<AcceptIcon />}
              onClick={() => handleQuickAction('accepted')}
            >
              Accept
            </Button>
            <Button
              variant="outlined"
              startIcon={<DismissIcon />}
              onClick={() => handleQuickAction('dismissed')}
            >
              Dismiss
            </Button>
          </Box>
        )}
        {opportunity.status === 'accepted' && (
          <Button
            variant="contained"
            color="warning"
            startIcon={<ImplementIcon />}
            onClick={() => handleQuickAction('in_progress')}
          >
            Start Implementation
          </Button>
        )}
        {opportunity.status === 'in_progress' && (
          <Button
            variant="contained"
            color="success"
            startIcon={<DoneIcon />}
            onClick={() => handleQuickAction('implemented')}
          >
            Mark Implemented
          </Button>
        )}
      </Box>

      <Grid container spacing={3}>
        {/* Main Content - Left Column */}
        <Grid item xs={12} md={8}>
          {/* Description */}
          <Paper sx={{ p: 3, mb: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
              Description
            </Typography>
            <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap' }}>
              {opportunity.description}
            </Typography>
          </Paper>

          {/* Implementation Steps */}
          {opportunity.implementation_steps && opportunity.implementation_steps.length > 0 && (
            <Paper sx={{ p: 3, mb: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                Implementation Steps
              </Typography>
              <List>
                {opportunity.implementation_steps.map((step, index) => (
                  <ListItem key={index} alignItems="flex-start">
                    <ListItemIcon>
                      <Box
                        sx={{
                          width: 28,
                          height: 28,
                          borderRadius: '50%',
                          bgcolor: '#667eea',
                          color: 'white',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: 600,
                          fontSize: '0.875rem',
                        }}
                      >
                        {step.step}
                      </Box>
                    </ListItemIcon>
                    <ListItemText
                      primary={step.action}
                      secondary={step.notes}
                      primaryTypographyProps={{ fontWeight: 500 }}
                    />
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}

          {/* Evidence Panel */}
          <Paper sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, p: 3, pb: 0 }}>
              Evidence
            </Typography>

            {/* API Trace */}
            {(opportunity.api_trace || opportunity.evidence?.api_trace) && (
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <CodeIcon color="primary" />
                    <Typography fontWeight={500}>API Trace</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ bgcolor: '#f5f5f5' }}>
                  <Box sx={{ position: 'relative' }}>
                    <IconButton
                      size="small"
                      onClick={() => copyToClipboard(JSON.stringify(opportunity.api_trace || opportunity.evidence?.api_trace, null, 2))}
                      sx={{ position: 'absolute', top: 8, right: 8 }}
                    >
                      <CopyIcon fontSize="small" />
                    </IconButton>
                    <SyntaxHighlighter
                      language="json"
                      style={vscDarkPlus}
                      customStyle={{ borderRadius: 8, fontSize: '0.8rem' }}
                    >
                      {JSON.stringify(opportunity.api_trace || opportunity.evidence?.api_trace, null, 2)}
                    </SyntaxHighlighter>
                  </Box>
                </AccordionDetails>
              </Accordion>
            )}

            {/* CUR Validation SQL */}
            {curSql && (
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <ResourceIcon color="primary" />
                    <Typography fontWeight={500}>CUR Validation SQL</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ bgcolor: '#f5f5f5' }}>
                  <Box sx={{ position: 'relative' }}>
                    <IconButton
                      size="small"
                      onClick={() => copyToClipboard(curSql)}
                      sx={{ position: 'absolute', top: 8, right: 8, zIndex: 1 }}
                    >
                      <CopyIcon fontSize="small" />
                    </IconButton>
                    <SyntaxHighlighter
                      language="sql"
                      style={vscDarkPlus}
                      customStyle={{ borderRadius: 8, fontSize: '0.8rem' }}
                    >
                      {curSql}
                    </SyntaxHighlighter>
                  </Box>
                </AccordionDetails>
              </Accordion>
            )}

            {/* Utilization Metrics */}
            {opportunity.evidence?.utilization_metrics && (
              <Accordion>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <TimeIcon color="primary" />
                    <Typography fontWeight={500}>Utilization Metrics</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails sx={{ bgcolor: '#f5f5f5' }}>
                  <SyntaxHighlighter
                    language="json"
                    style={vscDarkPlus}
                    customStyle={{ borderRadius: 8, fontSize: '0.8rem' }}
                  >
                    {JSON.stringify(opportunity.evidence.utilization_metrics, null, 2)}
                  </SyntaxHighlighter>
                </AccordionDetails>
              </Accordion>
            )}
          </Paper>
        </Grid>

        {/* Sidebar - Right Column */}
        <Grid item xs={12} md={4}>
          {/* Savings Card */}
          <Card sx={{ mb: 2, bgcolor: 'rgba(76, 175, 80, 0.08)', border: '1px solid rgba(76, 175, 80, 0.2)' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <MoneyIcon sx={{ color: '#4caf50' }} />
                <Typography variant="h6" sx={{ fontWeight: 600, color: '#4caf50' }}>
                  Potential Savings
                </Typography>
              </Box>
              <Typography variant="h4" sx={{ fontWeight: 700, color: '#2e7d32', mb: 1 }}>
                {formatCurrency(opportunity.estimated_monthly_savings)}/mo
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {formatCurrency(opportunity.estimated_annual_savings)}/year
              </Typography>
              {opportunity.savings_percentage !== null && opportunity.savings_percentage !== undefined && (
                <Chip
                  label={`${opportunity.savings_percentage.toFixed(1)}% reduction`}
                  color="success"
                  size="small"
                  sx={{ mt: 1 }}
                />
              )}
            </CardContent>
          </Card>

          {/* Resource Details */}
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                Resource Details
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {opportunity.resource_id && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Resource ID
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                      {opportunity.resource_id}
                    </Typography>
                  </Box>
                )}
                {opportunity.resource_type && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Type
                    </Typography>
                    <Typography variant="body2">{opportunity.resource_type}</Typography>
                  </Box>
                )}
                {opportunity.region && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Region
                    </Typography>
                    <Typography variant="body2">{opportunity.region}</Typography>
                  </Box>
                )}
                {opportunity.account_id && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Account ID
                    </Typography>
                    <Typography variant="body2">{opportunity.account_id}</Typography>
                  </Box>
                )}
              </Box>

              {opportunity.deep_link && (
                <Button
                  fullWidth
                  variant="outlined"
                  startIcon={<ExternalLinkIcon />}
                  href={opportunity.deep_link}
                  target="_blank"
                  sx={{ mt: 2 }}
                >
                  Open in AWS Console
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Metadata */}
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                Metadata
              </Typography>

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Source
                  </Typography>
                  <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                    {opportunity.source.replace('_', ' ')}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    First Detected
                  </Typography>
                  <Typography variant="body2">
                    {formatDate(opportunity.first_detected_at)}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Last Seen
                  </Typography>
                  <Typography variant="body2">
                    {formatDate(opportunity.last_seen_at)}
                  </Typography>
                </Box>
                {opportunity.confidence_score !== null && opportunity.confidence_score !== undefined && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Confidence Score
                    </Typography>
                    <Typography variant="body2">
                      {(opportunity.confidence_score * 100).toFixed(0)}%
                    </Typography>
                  </Box>
                )}
                {opportunity.priority_score !== null && opportunity.priority_score !== undefined && (
                  <Box>
                    <Typography variant="caption" color="text.secondary">
                      Priority Score
                    </Typography>
                    <Typography variant="body2">{opportunity.priority_score}/100</Typography>
                  </Box>
                )}
              </Box>

              {opportunity.tags && opportunity.tags.length > 0 && (
                <Box sx={{ mt: 2 }}>
                  <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                    Tags
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                    {opportunity.tags.map((tag, i) => (
                      <Chip key={i} label={tag} size="small" variant="outlined" />
                    ))}
                  </Box>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Status Update Dialog */}
      <Dialog open={statusDialogOpen} onClose={() => setStatusDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          Update Status to{' '}
          <Chip
            label={newStatus}
            color={statusColors[newStatus] || 'default'}
            size="small"
            sx={{ textTransform: 'capitalize', ml: 1 }}
          />
        </DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Reason (optional)"
            fullWidth
            multiline
            rows={3}
            value={statusReason}
            onChange={(e) => setStatusReason(e.target.value)}
            placeholder={
              newStatus === 'dismissed'
                ? 'e.g., Resource is needed for peak traffic'
                : 'e.g., Scheduling for next maintenance window'
            }
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStatusDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleStatusUpdate}
            variant="contained"
            disabled={updating}
          >
            {updating ? <CircularProgress size={20} /> : 'Update'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default OpportunityDetail;

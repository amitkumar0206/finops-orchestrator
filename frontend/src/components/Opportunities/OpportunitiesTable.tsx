import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  TableSortLabel,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  IconButton,
  Typography,
  Button,
  Checkbox,
  Toolbar,
  Tooltip,
  CircularProgress,
  Alert,
  SelectChangeEvent,
} from '@mui/material';
import {
  FilterList as FilterIcon,
  Refresh as RefreshIcon,
  Download as DownloadIcon,
  CheckCircle as AcceptIcon,
  Cancel as DismissIcon,
  TrendingUp as SavingsIcon,
  Search as SearchIcon,
} from '@mui/icons-material';

interface OpportunitySummary {
  id: string;
  title: string;
  service: string;
  category: string;
  status: string;
  estimated_monthly_savings: number | null;
  priority_score: number | null;
  effort_level: string | null;
  risk_level: string | null;
  resource_id: string | null;
  region: string | null;
  first_detected_at: string;
  last_seen_at: string;
}

interface OpportunitiesResponse {
  items: OpportunitySummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
  total_monthly_savings: number | null;
  status_counts: Record<string, number> | null;
  category_counts: Record<string, number> | null;
  service_counts: Record<string, number> | null;
}

interface OpportunitiesTableProps {
  onSelectOpportunity: (id: string) => void;
  onRefresh?: () => void;
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

const OpportunitiesTable: React.FC<OpportunitiesTableProps> = ({
  onSelectOpportunity,
  onRefresh,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<OpportunitiesResponse | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  // Pagination
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);

  // Sorting
  const [orderBy, setOrderBy] = useState<string>('savings_desc');

  // Filters
  const [statusFilter, setStatusFilter] = useState<string[]>(['open']);
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [serviceFilter, setServiceFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const fetchOpportunities = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      params.append('page', String(page + 1));
      params.append('page_size', String(rowsPerPage));
      params.append('sort', orderBy);

      statusFilter.forEach(s => params.append('status', s));
      if (categoryFilter) params.append('category', categoryFilter);
      if (serviceFilter) params.append('service', serviceFilter);
      if (searchQuery) params.append('search', searchQuery);

      const response = await fetch(`/api/v1/opportunities?${params.toString()}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch opportunities: ${response.statusText}`);
      }

      const result: OpportunitiesResponse = await response.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, orderBy, statusFilter, categoryFilter, serviceFilter, searchQuery]);

  useEffect(() => {
    fetchOpportunities();
  }, [fetchOpportunities]);

  const handleRefresh = () => {
    fetchOpportunities();
    onRefresh?.();
  };

  const handleChangePage = (_event: unknown, newPage: number) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10));
    setPage(0);
  };

  const handleSort = (column: string) => {
    const isAsc = orderBy === `${column}_asc`;
    setOrderBy(isAsc ? `${column}_desc` : `${column}_asc`);
  };

  const handleSelectAll = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked && data) {
      setSelected(data.items.map(item => item.id));
    } else {
      setSelected([]);
    }
  };

  const handleSelectOne = (id: string) => {
    const selectedIndex = selected.indexOf(id);
    let newSelected: string[] = [];

    if (selectedIndex === -1) {
      newSelected = [...selected, id];
    } else {
      newSelected = selected.filter(s => s !== id);
    }

    setSelected(newSelected);
  };

  const handleBulkAction = async (action: 'accept' | 'dismiss') => {
    if (selected.length === 0) return;

    const status = action === 'accept' ? 'accepted' : 'dismissed';

    try {
      const response = await fetch('/api/v1/opportunities/bulk-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          opportunity_ids: selected,
          status,
          reason: `Bulk ${action} from UI`,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to update opportunities');
      }

      setSelected([]);
      fetchOpportunities();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update');
    }
  };

  const handleExport = async () => {
    try {
      const params = new URLSearchParams();
      statusFilter.forEach(s => params.append('status', s));
      if (categoryFilter) params.append('category', categoryFilter);
      if (serviceFilter) params.append('service', serviceFilter);

      const response = await fetch('/api/v1/opportunities/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filter: {
            statuses: statusFilter.length > 0 ? statusFilter : null,
            categories: categoryFilter ? [categoryFilter] : null,
            services: serviceFilter ? [serviceFilter] : null,
          },
          format: 'csv',
          include_evidence: false,
          include_steps: true,
        }),
      });

      if (!response.ok) {
        throw new Error('Export failed');
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `opportunities_${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    }
  };

  const formatCurrency = (value: number | null) => {
    if (value === null || value === undefined) return '-';
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <Paper sx={{ width: '100%', overflow: 'hidden' }}>
      {/* Header with filters */}
      <Toolbar sx={{ pl: 2, pr: 1, bgcolor: 'rgba(102, 126, 234, 0.04)' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexGrow: 1 }}>
          <SavingsIcon sx={{ color: '#667eea' }} />
          <Typography variant="h6" sx={{ fontWeight: 600, color: 'text.primary' }}>
            Optimization Opportunities
          </Typography>

          {data && (
            <Chip
              label={`${formatCurrency(data.total_monthly_savings)}/mo potential`}
              color="success"
              size="small"
              sx={{ fontWeight: 600 }}
            />
          )}
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Tooltip title="Refresh">
            <IconButton onClick={handleRefresh} disabled={loading}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="Export CSV">
            <IconButton onClick={handleExport}>
              <DownloadIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Toolbar>

      {/* Filters Row */}
      <Box sx={{ p: 2, display: 'flex', gap: 2, flexWrap: 'wrap', bgcolor: '#f8fafc' }}>
        <TextField
          size="small"
          placeholder="Search opportunities..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          InputProps={{
            startAdornment: <SearchIcon sx={{ color: 'text.secondary', mr: 1 }} />,
          }}
          sx={{ minWidth: 250 }}
        />

        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Status</InputLabel>
          <Select
            multiple
            value={statusFilter}
            label="Status"
            onChange={(e: SelectChangeEvent<string[]>) => {
              const value = e.target.value;
              setStatusFilter(typeof value === 'string' ? value.split(',') : value);
            }}
            renderValue={(selected) => (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip key={value} label={value} size="small" />
                ))}
              </Box>
            )}
          >
            <MenuItem value="open">Open</MenuItem>
            <MenuItem value="accepted">Accepted</MenuItem>
            <MenuItem value="in_progress">In Progress</MenuItem>
            <MenuItem value="implemented">Implemented</MenuItem>
            <MenuItem value="dismissed">Dismissed</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel>Category</InputLabel>
          <Select
            value={categoryFilter}
            label="Category"
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="rightsizing">Rightsizing</MenuItem>
            <MenuItem value="idle_resources">Idle Resources</MenuItem>
            <MenuItem value="reserved_instances">Reserved Instances</MenuItem>
            <MenuItem value="savings_plans">Savings Plans</MenuItem>
            <MenuItem value="storage_optimization">Storage</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 120 }}>
          <InputLabel>Service</InputLabel>
          <Select
            value={serviceFilter}
            label="Service"
            onChange={(e) => setServiceFilter(e.target.value)}
          >
            <MenuItem value="">All</MenuItem>
            <MenuItem value="EC2">EC2</MenuItem>
            <MenuItem value="RDS">RDS</MenuItem>
            <MenuItem value="S3">S3</MenuItem>
            <MenuItem value="Lambda">Lambda</MenuItem>
            <MenuItem value="EBS">EBS</MenuItem>
            <MenuItem value="ELB">ELB</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {/* Bulk actions */}
      {selected.length > 0 && (
        <Box sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 2, bgcolor: 'rgba(102, 126, 234, 0.08)' }}>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {selected.length} selected
          </Typography>
          <Button
            size="small"
            variant="contained"
            color="primary"
            startIcon={<AcceptIcon />}
            onClick={() => handleBulkAction('accept')}
          >
            Accept
          </Button>
          <Button
            size="small"
            variant="outlined"
            startIcon={<DismissIcon />}
            onClick={() => handleBulkAction('dismiss')}
          >
            Dismiss
          </Button>
        </Box>
      )}

      {/* Error message */}
      {error && (
        <Alert severity="error" sx={{ m: 2 }}>
          {error}
        </Alert>
      )}

      {/* Loading state */}
      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {/* Table */}
      {!loading && data && (
        <>
          <TableContainer sx={{ maxHeight: 600 }}>
            <Table stickyHeader size="small">
              <TableHead>
                <TableRow>
                  <TableCell padding="checkbox">
                    <Checkbox
                      indeterminate={selected.length > 0 && selected.length < data.items.length}
                      checked={data.items.length > 0 && selected.length === data.items.length}
                      onChange={handleSelectAll}
                    />
                  </TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>
                    <TableSortLabel
                      active={orderBy.startsWith('priority')}
                      direction={orderBy === 'priority_asc' ? 'asc' : 'desc'}
                      onClick={() => handleSort('priority')}
                    >
                      Title
                    </TableSortLabel>
                  </TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Service</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Category</TableCell>
                  <TableCell sx={{ fontWeight: 600 }} align="right">
                    <TableSortLabel
                      active={orderBy.startsWith('savings')}
                      direction={orderBy === 'savings_asc' ? 'asc' : 'desc'}
                      onClick={() => handleSort('savings')}
                    >
                      Monthly Savings
                    </TableSortLabel>
                  </TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Effort</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>
                    <TableSortLabel
                      active={orderBy.startsWith('first_detected')}
                      direction={orderBy === 'first_detected_asc' ? 'asc' : 'desc'}
                      onClick={() => handleSort('first_detected')}
                    >
                      Detected
                    </TableSortLabel>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.items.map((row) => {
                  const isSelected = selected.includes(row.id);

                  return (
                    <TableRow
                      hover
                      key={row.id}
                      selected={isSelected}
                      onClick={() => onSelectOpportunity(row.id)}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          checked={isSelected}
                          onChange={() => handleSelectOne(row.id)}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {row.title.length > 60 ? `${row.title.substring(0, 60)}...` : row.title}
                        </Typography>
                        {row.resource_id && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            {row.resource_id.length > 30
                              ? `...${row.resource_id.slice(-30)}`
                              : row.resource_id}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip label={row.service} size="small" variant="outlined" />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" sx={{ textTransform: 'capitalize' }}>
                          {row.category.replace('_', ' ')}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        <Typography
                          variant="body2"
                          sx={{
                            fontWeight: 600,
                            color: row.estimated_monthly_savings && row.estimated_monthly_savings > 100
                              ? 'success.main'
                              : 'text.primary',
                          }}
                        >
                          {formatCurrency(row.estimated_monthly_savings)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {row.effort_level && (
                          <Chip
                            label={row.effort_level}
                            size="small"
                            sx={{
                              bgcolor: effortColors[row.effort_level] || '#9e9e9e',
                              color: 'white',
                              fontWeight: 500,
                              textTransform: 'capitalize',
                            }}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={row.status}
                          size="small"
                          color={statusColors[row.status] || 'default'}
                          sx={{ textTransform: 'capitalize' }}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2" color="text.secondary">
                          {formatDate(row.first_detected_at)}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  );
                })}

                {data.items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                      <Typography color="text.secondary">
                        No opportunities found. Try adjusting your filters or run an ingestion.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <TablePagination
            rowsPerPageOptions={[10, 20, 50, 100]}
            component="div"
            count={data.total}
            rowsPerPage={rowsPerPage}
            page={page}
            onPageChange={handleChangePage}
            onRowsPerPageChange={handleChangeRowsPerPage}
          />
        </>
      )}
    </Paper>
  );
};

export default OpportunitiesTable;

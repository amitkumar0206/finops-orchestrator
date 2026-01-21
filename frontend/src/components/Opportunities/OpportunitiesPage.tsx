import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  CircularProgress,
  Alert,
} from '@mui/material';
import {
  TrendingUp as SavingsIcon,
  Lightbulb as OpportunityIcon,
  CheckCircle as ImplementedIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import OpportunitiesTable from './OpportunitiesTable';
import OpportunityDetail from './OpportunityDetail';

interface OpportunitiesStats {
  total_opportunities: number;
  open_opportunities: number;
  total_potential_monthly_savings: number;
  total_potential_annual_savings: number;
  implemented_savings_monthly: number;
  implemented_savings_annual: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_service: Record<string, number>;
  by_source: Record<string, number>;
  by_effort_level: Record<string, number>;
}

const OpportunitiesPage: React.FC = () => {
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [stats, setStats] = useState<OpportunitiesStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchStats = async () => {
    setStatsLoading(true);
    setStatsError(null);

    try {
      const response = await fetch('/api/v1/opportunities/stats');
      if (!response.ok) {
        throw new Error('Failed to fetch stats');
      }
      const data = await response.json();
      setStats(data);
    } catch (err) {
      setStatsError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setStatsLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, [refreshKey]);

  const handleIngest = async () => {
    setIngesting(true);
    setIngestResult(null);

    try {
      const response = await fetch('/api/v1/opportunities/ingest', {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Ingestion failed');
      }

      const result = await response.json();
      setIngestResult({
        success: true,
        message: `Ingested ${result.new_opportunities} new opportunities, updated ${result.updated_opportunities}`,
      });
      setRefreshKey((prev) => prev + 1);
    } catch (err) {
      setIngestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Ingestion failed',
      });
    } finally {
      setIngesting(false);
    }
  };

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1);
  };

  const formatCurrency = (value: number) => {
    return `$${value.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    })}`;
  };

  // Show detail view if an opportunity is selected
  if (selectedOpportunityId) {
    return (
      <Container maxWidth="xl" sx={{ py: 3 }}>
        <OpportunityDetail
          opportunityId={selectedOpportunityId}
          onBack={() => setSelectedOpportunityId(null)}
          onStatusChange={handleRefresh}
        />
      </Container>
    );
  }

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      {/* Page Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
            Cost Optimization Opportunities
          </Typography>
          <Typography variant="body1" color="text.secondary">
            AWS recommendations from Cost Explorer, Trusted Advisor, and Compute Optimizer
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={ingesting ? <CircularProgress size={20} color="inherit" /> : <RefreshIcon />}
          onClick={handleIngest}
          disabled={ingesting}
          sx={{
            bgcolor: '#667eea',
            '&:hover': { bgcolor: '#5a6fd6' },
          }}
        >
          {ingesting ? 'Ingesting...' : 'Ingest New Signals'}
        </Button>
      </Box>

      {/* Ingest Result Alert */}
      {ingestResult && (
        <Alert
          severity={ingestResult.success ? 'success' : 'error'}
          onClose={() => setIngestResult(null)}
          sx={{ mb: 3 }}
        >
          {ingestResult.message}
        </Alert>
      )}

      {/* Stats Cards */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        {/* Total Potential Savings */}
        <Grid item xs={12} md={3}>
          <Card sx={{ height: '100%', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <SavingsIcon sx={{ color: 'rgba(255,255,255,0.9)' }} />
                <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.9)' }}>
                  Potential Savings
                </Typography>
              </Box>
              {statsLoading ? (
                <CircularProgress size={24} sx={{ color: 'white' }} />
              ) : (
                <>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'white' }}>
                    {stats ? formatCurrency(stats.total_potential_monthly_savings) : '-'}
                  </Typography>
                  <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.8)' }}>
                    per month ({stats ? formatCurrency(stats.total_potential_annual_savings) : '-'}/yr)
                  </Typography>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Open Opportunities */}
        <Grid item xs={12} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <OpportunityIcon sx={{ color: '#667eea' }} />
                <Typography variant="body2" color="text.secondary">
                  Open Opportunities
                </Typography>
              </Box>
              {statsLoading ? (
                <CircularProgress size={24} />
              ) : (
                <>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary' }}>
                    {stats?.open_opportunities ?? '-'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    of {stats?.total_opportunities ?? '-'} total
                  </Typography>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Implemented Savings */}
        <Grid item xs={12} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <ImplementedIcon sx={{ color: '#4caf50' }} />
                <Typography variant="body2" color="text.secondary">
                  Implemented Savings
                </Typography>
              </Box>
              {statsLoading ? (
                <CircularProgress size={24} />
              ) : (
                <>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: '#4caf50' }}>
                    {stats ? formatCurrency(stats.implemented_savings_monthly) : '-'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    per month
                  </Typography>
                </>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* By Service */}
        <Grid item xs={12} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Top Services by Opportunities
              </Typography>
              {statsLoading ? (
                <CircularProgress size={24} />
              ) : stats?.by_service ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                  {Object.entries(stats.by_service)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 4)
                    .map(([service, count]) => (
                      <Box
                        key={service}
                        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                      >
                        <Typography variant="body2">{service}</Typography>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {count}
                        </Typography>
                      </Box>
                    ))}
                </Box>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No data
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Opportunities Table */}
      <OpportunitiesTable
        key={refreshKey}
        onSelectOpportunity={setSelectedOpportunityId}
        onRefresh={fetchStats}
      />
    </Container>
  );
};

export default OpportunitiesPage;

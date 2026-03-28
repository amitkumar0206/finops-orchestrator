import React, { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  FormControlLabel,
  Grid,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import {
  Architecture as ArchitectureIcon,
  CloudUpload as CloudUploadIcon,
  ContentCopy as ContentCopyIcon,
  Download as DownloadIcon,
  RestartAlt as RestartAltIcon,
  AutoFixHigh as AutoFixHighIcon,
} from '@mui/icons-material';

interface GenerateResponse {
  mode: 'text' | 'services' | 'diagram';
  summary: string;
  assumptions: string[];
  selected_services: string[];
  output_format: 'terraform' | 'cloudformation';
  generated_template: string;
  alternate_template: string;
  next_steps: string[];
  diagram_notes?: string;
}

const SERVICE_OPTIONS = [
  { id: 'vpc', label: 'Networking (VPC)' },
  { id: 'ecs', label: 'Containers (ECS/Fargate)' },
  { id: 'ec2', label: 'Virtual Machines (EC2)' },
  { id: 's3', label: 'Object Storage (S3)' },
  { id: 'rds', label: 'Relational Database (RDS)' },
  { id: 'dynamodb', label: 'NoSQL Database (DynamoDB)' },
  { id: 'lambda', label: 'Serverless Functions (Lambda)' },
  { id: 'apigateway', label: 'API Layer (API Gateway)' },
  { id: 'cloudfront', label: 'CDN (CloudFront)' },
  { id: 'sqs', label: 'Queue (SQS)' },
  { id: 'sns', label: 'Notifications (SNS)' },
];

const GenerateBlueprintPage: React.FC = () => {
  const [mode, setMode] = useState<'text' | 'services' | 'diagram'>('text');
  const [requirements, setRequirements] = useState('');
  const [selectedServices, setSelectedServices] = useState<string[]>(['vpc', 'ecs', 's3']);
  const [diagramFile, setDiagramFile] = useState<File | null>(null);
  const [diagramNotes, setDiagramNotes] = useState('');
  const [outputFormat, setOutputFormat] = useState<'terraform' | 'cloudformation'>('terraform');
  const [environment, setEnvironment] = useState('development');
  const [region, setRegion] = useState('us-east-1');
  const [includeNetworking, setIncludeNetworking] = useState(true);

  const [isGenerating, setIsGenerating] = useState(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canGenerate = useMemo(() => {
    if (mode === 'text') return requirements.trim().length >= 10;
    if (mode === 'services') return selectedServices.length > 0;
    return !!diagramFile;
  }, [mode, requirements, selectedServices, diagramFile]);

  const toggleService = (service: string) => {
    setSelectedServices((prev) =>
      prev.includes(service)
        ? prev.filter((s) => s !== service)
        : [...prev, service]
    );
  };

  const parseError = async (response: Response, fallback: string) => {
    try {
      const body = await response.text();
      if (!body) return fallback;
      try {
        const parsed = JSON.parse(body);
        if (typeof parsed?.detail === 'string') return parsed.detail;
        if (Array.isArray(parsed?.detail)) return parsed.detail.map((d: any) => d?.msg).filter(Boolean).join('. ') || fallback;
        if (typeof parsed?.message === 'string') return parsed.message;
      } catch {
        // noop
      }
      return body;
    } catch {
      return fallback;
    }
  };

  const buildServicePayload = () => {
    const merged = includeNetworking && !selectedServices.includes('vpc')
      ? ['vpc', ...selectedServices]
      : selectedServices;
    return Array.from(new Set(merged));
  };

  const handleGenerate = async () => {
    setError(null);
    setResult(null);
    setIsGenerating(true);

    try {
      let response: Response;

      if (mode === 'text') {
        response = await fetch('/api/v1/iac-generate/start-from-text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            requirements,
            output_format: outputFormat,
            region,
            environment,
          }),
        });
      } else if (mode === 'services') {
        response = await fetch('/api/v1/iac-generate/start-from-services', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            services: buildServicePayload(),
            output_format: outputFormat,
            region,
            environment,
          }),
        });
      } else {
        const formData = new FormData();
        if (diagramFile) formData.append('diagram', diagramFile);
        formData.append('notes', diagramNotes);
        formData.append('output_format', outputFormat);
        formData.append('region', region);
        formData.append('environment', environment);

        response = await fetch('/api/v1/iac-generate/start-from-diagram', {
          method: 'POST',
          body: formData,
        });
      }

      if (!response.ok) {
        const message = await parseError(response, `Generation failed (${response.status})`);
        throw new Error(message);
      }

      const data: GenerateResponse = await response.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setIsGenerating(false);
    }
  };

  const resetAll = () => {
    setRequirements('');
    setSelectedServices(['vpc', 'ecs', 's3']);
    setDiagramFile(null);
    setDiagramNotes('');
    setResult(null);
    setError(null);
  };

  const copyTemplate = async () => {
    if (!result?.generated_template) return;
    try {
      await navigator.clipboard.writeText(result.generated_template);
    } catch {
      setError('Copy failed. Please copy manually from the output panel.');
    }
  };

  const downloadTemplate = () => {
    if (!result?.generated_template) return;
    const ext = result.output_format === 'terraform' ? 'tf' : 'yaml';
    const filename = `generated-${result.mode}-${environment}.${ext}`;
    const blob = new Blob([result.generated_template], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, overflow: 'auto' }}>
      <Stack spacing={2.5}>
        <Paper
          elevation={0}
          sx={{
            position: 'relative',
            overflow: 'hidden',
            p: { xs: 1.4, md: 1.8 },
            borderRadius: 2.5,
            border: '1px solid rgba(21, 101, 192, 0.16)',
            background: 'linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%)',
          }}
        >
          <Box
            sx={{
              position: 'absolute',
              left: 0,
              top: 0,
              bottom: 0,
              width: 5,
              background: 'linear-gradient(180deg, #1558ad 0%, #0b8f9e 100%)',
            }}
          />
          <Stack spacing={0.55} sx={{ pl: { xs: 1.1, md: 1.4 } }}>
            <Typography variant="overline" sx={{ color: 'primary.main', fontWeight: 700, letterSpacing: 0.8 }}>
              Generate
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, color: '#123a63', lineHeight: 1.2 }}>
              Build Cloud Blueprint from Scratch
            </Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 940 }}>
              Create starter Terraform or CloudFormation templates from business requirements, selected services, or architecture diagrams.
            </Typography>
          </Stack>
        </Paper>

        <Card sx={{ borderRadius: 3 }}>
          <CardContent>
            <Stack spacing={2}>
              <Tabs
                value={mode}
                onChange={(_, value) => setMode(value)}
                variant="scrollable"
                allowScrollButtonsMobile
              >
                <Tab value="text" label="Describe with AI" />
                <Tab value="services" label="Select Services" />
                <Tab value="diagram" label="Upload Diagram" />
              </Tabs>

              <Divider />

              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <TextField
                    fullWidth
                    select
                    label="Output format"
                    value={outputFormat}
                    onChange={(e) => setOutputFormat(e.target.value as 'terraform' | 'cloudformation')}
                  >
                    <MenuItem value="terraform">Terraform</MenuItem>
                    <MenuItem value="cloudformation">CloudFormation</MenuItem>
                  </TextField>
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    fullWidth
                    label="Environment"
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    fullWidth
                    label="AWS region"
                    value={region}
                    onChange={(e) => setRegion(e.target.value)}
                  />
                </Grid>
              </Grid>

              {mode === 'text' && (
                <TextField
                  fullWidth
                  multiline
                  minRows={5}
                  label="Describe your requirements"
                  placeholder="Example: Build a customer portal with API, relational database, static assets, autoscaling, and monthly cost controls."
                  value={requirements}
                  onChange={(e) => setRequirements(e.target.value)}
                />
              )}

              {mode === 'services' && (
                <Stack spacing={1.2}>
                  <Typography variant="subtitle1" fontWeight={700}>Select services for your blueprint</Typography>
                  <Grid container spacing={1}>
                    {SERVICE_OPTIONS.map((option) => {
                      const selected = selectedServices.includes(option.id);
                      return (
                        <Grid item xs={12} sm={6} md={4} key={option.id}>
                          <Chip
                            label={option.label}
                            color={selected ? 'primary' : 'default'}
                            variant={selected ? 'filled' : 'outlined'}
                            onClick={() => toggleService(option.id)}
                            sx={{ width: '100%', justifyContent: 'flex-start' }}
                          />
                        </Grid>
                      );
                    })}
                  </Grid>
                  <FormControlLabel
                    control={<Switch checked={includeNetworking} onChange={(e) => setIncludeNetworking(e.target.checked)} />}
                    label="Always include baseline networking (VPC)"
                  />
                </Stack>
              )}

              {mode === 'diagram' && (
                <Stack spacing={1.2}>
                  <Button component="label" variant="outlined" startIcon={<CloudUploadIcon />} sx={{ width: 'fit-content' }}>
                    Upload Diagram
                    <input
                      hidden
                      type="file"
                      accept="image/*,.pdf"
                      onChange={(e) => setDiagramFile(e.target.files?.[0] || null)}
                    />
                  </Button>
                  <Typography variant="body2" color="text.secondary">
                    {diagramFile ? `Selected: ${diagramFile.name}` : 'No diagram uploaded yet'}
                  </Typography>
                  <TextField
                    fullWidth
                    multiline
                    minRows={3}
                    label="Optional notes"
                    placeholder="Describe components shown in the diagram or any key constraints."
                    value={diagramNotes}
                    onChange={(e) => setDiagramNotes(e.target.value)}
                  />
                </Stack>
              )}

              {error && <Alert severity="error">{error}</Alert>}

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                <Button
                  variant="contained"
                  onClick={handleGenerate}
                  disabled={!canGenerate || isGenerating}
                  startIcon={isGenerating ? <AutoFixHighIcon /> : <ArchitectureIcon />}
                >
                  {isGenerating ? 'Generating...' : 'Generate Blueprint'}
                </Button>
                <Button variant="text" startIcon={<RestartAltIcon />} onClick={resetAll}>
                  Reset
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        {result && (
          <Grid container spacing={2}>
            <Grid item xs={12} md={5}>
              <Card sx={{ borderRadius: 3, height: '100%' }}>
                <CardContent>
                  <Stack spacing={1.2}>
                    <Typography variant="h6" fontWeight={700}>Generation Summary</Typography>
                    <Typography variant="body2">{result.summary}</Typography>
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      {result.selected_services.map((service) => (
                        <Chip key={service} size="small" label={service} variant="outlined" />
                      ))}
                    </Stack>

                    <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1 }}>Assumptions</Typography>
                    <Stack spacing={0.6}>
                      {result.assumptions.map((item, idx) => (
                        <Typography key={idx} variant="body2">- {item}</Typography>
                      ))}
                    </Stack>

                    <Typography variant="subtitle2" fontWeight={700} sx={{ mt: 1 }}>Next Steps</Typography>
                    <Stack spacing={0.6}>
                      {result.next_steps.map((item, idx) => (
                        <Typography key={idx} variant="body2">- {item}</Typography>
                      ))}
                    </Stack>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={7}>
              <Card sx={{ borderRadius: 3 }}>
                <CardContent>
                  <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                    <Typography variant="h6" fontWeight={700}>
                      Generated {result.output_format === 'terraform' ? 'Terraform' : 'CloudFormation'} Template
                    </Typography>
                    <Stack direction="row" spacing={1}>
                      <Button size="small" variant="outlined" startIcon={<ContentCopyIcon />} onClick={copyTemplate}>
                        Copy
                      </Button>
                      <Button size="small" variant="outlined" startIcon={<DownloadIcon />} onClick={downloadTemplate}>
                        Download
                      </Button>
                    </Stack>
                  </Stack>

                  <Paper
                    variant="outlined"
                    sx={{
                      p: 1.2,
                      minHeight: 360,
                      maxHeight: 560,
                      overflowY: 'auto',
                      borderRadius: 2,
                      bgcolor: '#0f172a',
                      color: '#e2e8f0',
                      fontFamily: 'Menlo, Monaco, Consolas, monospace',
                      fontSize: 12,
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {result.generated_template}
                  </Paper>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        )}
      </Stack>
    </Box>
  );
};

export default GenerateBlueprintPage;

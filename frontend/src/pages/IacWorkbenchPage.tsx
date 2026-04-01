import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    Grid,
    Paper,
    Stack,
    Tab,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Tabs,
    TextField,
    Typography,
} from '@mui/material';
import {
    AutoFixHigh as AutoFixHighIcon,
    CloudUpload as CloudUploadIcon,
    Download as DownloadIcon,
    Replay as ReplayIcon,
    Send as SendIcon,
} from '@mui/icons-material';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { apiFetch } from '../lib/api';

interface AnalysisResponse {
    analysis_id: string;
    filename: string;
    format: string;
    summary: string;
    explanation: string;
    pros: string[];
    cons: string[];
    cost_analysis: Array<{
        service: string;
        config: string;
        estimated_monthly_cost_usd: number;
    }>;
    improvements: string[];
    improved_content: string;
    file_count?: number;
    files?: AnalysisFile[];
    cross_file_analysis?: {
        summary?: string;
        architecture_observations?: string[];
        risks?: string[];
        recommendations?: string[];
        total_estimated_monthly_savings?: number;
        regions_detected?: string[];
    };
}

interface AnalysisFile {
    analysis_id: string;
    filename: string;
    format: string;
    summary: string;
    explanation: string;
    pros: string[];
    cons: string[];
    cost_analysis: Array<{
        service: string;
        config: string;
        estimated_monthly_cost_usd: number;
    }>;
    improvements: string[];
    improved_content: string;
}

interface ChatMessage {
    role: 'user' | 'assistant';
    text: string;
}

const IacWorkbenchPage: React.FC = () => {
    const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
    const [activeFileId, setActiveFileId] = useState<string | null>(null);
    const [workspaceTab, setWorkspaceTab] = useState<'findings' | 'questions' | 'improve'>('findings');
    const [findingsTab, setFindingsTab] = useState<string>('summary');

    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [isChatting, setIsChatting] = useState(false);

    const [finalGoals, setFinalGoals] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [improvedContent, setImprovedContent] = useState('');

    const analysisFiles = useMemo(() => {
        if (!analysis) return [];
        if (analysis.files && analysis.files.length > 0) return analysis.files;
        return [analysis as AnalysisFile];
    }, [analysis]);

    const hasMultipleFiles = analysisFiles.length > 1;

    const activeAnalysis = useMemo(() => {
        if (analysisFiles.length === 0) return null;
        return analysisFiles.find((f) => f.analysis_id === activeFileId) || analysisFiles[0];
    }, [analysisFiles, activeFileId]);

    const showPortfolioSummary = hasMultipleFiles && findingsTab === 'summary';

    const totalEstimatedSavings = useMemo(() => {
        if (!activeAnalysis) return 0;
        return activeAnalysis.cost_analysis.reduce((sum, row) => sum + (Number(row.estimated_monthly_cost_usd) || 0), 0);
    }, [activeAnalysis]);

    useEffect(() => {
        if (!activeAnalysis) return;
        setImprovedContent(activeAnalysis.improved_content || '');
    }, [activeAnalysis]);

    const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        setSelectedFiles(files);
        setError(null);
    };

    const startNewAnalysis = () => {
        setAnalysis(null);
        setSelectedFiles([]);
        setActiveFileId(null);
        setFindingsTab('summary');
        setWorkspaceTab('findings');
        setChatMessages([]);
        setChatInput('');
        setFinalGoals('');
        setImprovedContent('');
        setError(null);
    };

    const parseApiError = async (response: Response, fallback: string): Promise<string> => {
        try {
            const body = await response.text();
            if (!body) return fallback;

            let parsed: any = null;
            try {
                parsed = JSON.parse(body);
            } catch {
                parsed = null;
            }

            const detail = parsed?.detail || parsed?.message;

            if (response.status === 404) {
                return 'This analysis feature is not available in the current environment yet. Please refresh and try again shortly.';
            }

            if (Array.isArray(detail)) {
                return detail.map((d: any) => d?.msg).filter(Boolean).join('. ') || fallback;
            }

            if (typeof detail === 'string' && detail.trim()) {
                return detail;
            }

            if (typeof body === 'string' && body.trim()) {
                return body;
            }

            return fallback;
        } catch {
            return fallback;
        }
    };

    const analyzeFile = async () => {
        if (selectedFiles.length === 0) return;

        setIsUploading(true);
        setError(null);
        setAnalysis(null);
        setActiveFileId(null);
        setFindingsTab('summary');
        setWorkspaceTab('findings');
        setChatMessages([]);
        setImprovedContent('');

        try {
            const formData = new FormData();
            selectedFiles.forEach((file) => {
                formData.append('files', file);
            });

            const response = await apiFetch('/api/v1/iac/analyze', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const message = await parseApiError(response, `Analyze failed with status ${response.status}`);
                throw new Error(message);
            }

            const data: AnalysisResponse = await response.json();
            setAnalysis(data);

            const files = (data.files && data.files.length > 0) ? data.files : [data as AnalysisFile];
            const firstFile = files[0];
            setActiveFileId(firstFile.analysis_id);
            setFindingsTab(files.length > 1 ? 'summary' : firstFile.analysis_id);

            setChatMessages([
                {
                    role: 'assistant',
                    text: files.length > 1
                        ? `I reviewed ${files.length} files. Start in Portfolio Summary, then open each file tab for details.`
                        : `Analysis is ready for ${data.filename}. Ask any follow-up question and I will explain in business terms.`,
                },
            ]);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Analyze failed');
        } finally {
            setIsUploading(false);
        }
    };

    const sendChat = async () => {
        if (!activeAnalysis || !chatInput.trim() || isChatting) return;

        const msg = chatInput.trim();
        setChatInput('');
        setChatMessages((prev) => [...prev, { role: 'user', text: msg }]);
        setIsChatting(true);

        try {
            const response = await apiFetch('/api/v1/iac/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    analysis_id: activeAnalysis.analysis_id,
                    message: msg,
                }),
            });

            if (!response.ok) {
                const message = await parseApiError(response, `Chat failed with status ${response.status}`);
                throw new Error(message);
            }

            const data = await response.json();
            setChatMessages((prev) => [...prev, { role: 'assistant', text: data.message || 'No response' }]);
        } catch (err) {
            setChatMessages((prev) => [
                ...prev,
                {
                    role: 'assistant',
                    text: err instanceof Error ? `Chat error: ${err.message}` : 'Chat error',
                },
            ]);
        } finally {
            setIsChatting(false);
        }
    };

    const generateFinal = async () => {
        if (!activeAnalysis || isGenerating) return;
        setIsGenerating(true);

        try {
            const response = await apiFetch('/api/v1/iac/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    analysis_id: activeAnalysis.analysis_id,
                    goals: finalGoals || null,
                }),
            });

            if (!response.ok) {
                const message = await parseApiError(response, `Generate failed with status ${response.status}`);
                throw new Error(message);
            }

            const data = await response.json();
            setImprovedContent(data.improved_content || '');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to generate improved version');
        } finally {
            setIsGenerating(false);
        }
    };

    const downloadVersion = async (version: 'improved' | 'original') => {
        if (!activeAnalysis) return;

        try {
            const response = await apiFetch(`/api/v1/iac/${activeAnalysis.analysis_id}/download?version=${version}`);
            if (!response.ok) {
                const message = await parseApiError(response, `Download failed with status ${response.status}`);
                throw new Error(message);
            }
            const content = await response.text();
            const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            const extension = activeAnalysis.filename.includes('.') ? activeAnalysis.filename.split('.').pop() : 'txt';
            a.href = url;
            a.download = `${activeAnalysis.filename.replace(/\.[^.]+$/, '')}.${version}.${extension}`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Download failed');
        }
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
                            Analyze
                        </Typography>
                        <Typography variant="h5" sx={{ fontWeight: 700, color: '#123a63', lineHeight: 1.2 }}>
                            Cloud Setup Analyzer
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'text.secondary', maxWidth: 920 }}>
                            Review cloud setup files for business impact, key risks, and practical optimization options.
                        </Typography>
                    </Stack>
                </Paper>

                {!analysis && (
                    <Card sx={{ borderRadius: 3 }}>
                        <CardContent>
                            <Stack spacing={2}>
                                <Typography variant="h6" fontWeight={700}>Start Analysis</Typography>
                                <Typography variant="body2" color="text.secondary">
                                    Upload one or more cloud setup files. If you upload multiple files, you will get both a combined summary and individual file details.
                                </Typography>
                                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                                    <Button component="label" variant="outlined" startIcon={<CloudUploadIcon />}>
                                        Choose Files
                                        <input hidden type="file" multiple accept=".tf,.tfvars,.hcl,.yaml,.yml,.json" onChange={onFileChange} />
                                    </Button>
                                    <Typography variant="body2" color="text.secondary">
                                        {selectedFiles.length > 0 ? `${selectedFiles.length} file(s) selected` : 'No files selected yet'}
                                    </Typography>
                                    <Box sx={{ flex: 1 }} />
                                    <Button
                                        variant="contained"
                                        onClick={analyzeFile}
                                        disabled={selectedFiles.length === 0 || isUploading}
                                        startIcon={isUploading ? <CircularProgress size={16} color="inherit" /> : <AutoFixHighIcon />}
                                    >
                                        {isUploading ? 'Analyzing...' : 'Analyze'}
                                    </Button>
                                </Stack>
                                {error && <Alert severity="error">{error}</Alert>}
                            </Stack>
                        </CardContent>
                    </Card>
                )}

                {analysis && activeAnalysis && (
                    <>
                        <Card sx={{ borderRadius: 3 }}>
                            <CardContent>
                                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ xs: 'flex-start', md: 'center' }}>
                                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                        <Chip color="success" label="Analysis Ready" size="small" />
                                        <Chip label={`${analysisFiles.length} file(s)`} size="small" variant="outlined" />
                                    </Stack>
                                    <Box sx={{ flex: 1 }} />
                                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                                        <Button
                                            component="label"
                                            variant="outlined"
                                            startIcon={<CloudUploadIcon />}
                                        >
                                            Choose New Files
                                            <input hidden type="file" multiple accept=".tf,.tfvars,.hcl,.yaml,.yml,.json" onChange={onFileChange} />
                                        </Button>
                                        <Button
                                            variant="contained"
                                            onClick={analyzeFile}
                                            disabled={selectedFiles.length === 0 || isUploading}
                                            startIcon={isUploading ? <CircularProgress size={16} color="inherit" /> : <AutoFixHighIcon />}
                                        >
                                            {isUploading ? 'Analyzing...' : 'Analyze New Files'}
                                        </Button>
                                        <Button variant="text" color="inherit" startIcon={<ReplayIcon />} onClick={startNewAnalysis}>
                                            Start Over
                                        </Button>
                                    </Stack>
                                </Stack>
                                {selectedFiles.length > 0 && (
                                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                        Pending upload: {selectedFiles.length} file(s) selected
                                    </Typography>
                                )}
                            </CardContent>
                        </Card>

                        <Card sx={{ borderRadius: 3 }}>
                            <CardContent sx={{ pb: 1 }}>
                                <Tabs
                                    value={workspaceTab}
                                    onChange={(_, v) => setWorkspaceTab(v)}
                                    variant="scrollable"
                                    allowScrollButtonsMobile
                                >
                                    <Tab value="findings" label="Findings" />
                                    <Tab value="questions" label="Ask Questions" />
                                    <Tab value="improve" label="Improve Version" />
                                </Tabs>
                            </CardContent>
                            <Divider />

                            <CardContent>
                                {workspaceTab === 'findings' && (
                                    <Stack spacing={2}>
                                        {hasMultipleFiles && (
                                            <Tabs
                                                value={findingsTab}
                                                onChange={(_, v) => {
                                                    setFindingsTab(v);
                                                    if (v !== 'summary') {
                                                        setActiveFileId(v);
                                                    }
                                                }}
                                                variant="scrollable"
                                                allowScrollButtonsMobile
                                            >
                                                <Tab value="summary" label="Portfolio Summary" />
                                                {analysisFiles.map((f) => (
                                                    <Tab key={f.analysis_id} value={f.analysis_id} label={f.filename} />
                                                ))}
                                            </Tabs>
                                        )}

                                        {showPortfolioSummary ? (
                                            <Grid container spacing={2}>
                                                <Grid item xs={12}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                                        <CardContent>
                                                            <Stack spacing={1.2}>
                                                                <Typography variant="h6" fontWeight={700}>Combined Summary</Typography>
                                                                <Typography variant="body1">
                                                                    {analysis.cross_file_analysis?.summary || 'Combined summary is available for this file set.'}
                                                                </Typography>
                                                                <Stack direction="row" spacing={1} flexWrap="wrap">
                                                                    <Chip label={`Files reviewed: ${analysisFiles.length}`} size="small" />
                                                                    <Chip
                                                                        label={`Estimated savings: $${Number(analysis.cross_file_analysis?.total_estimated_monthly_savings || 0).toFixed(2)}/month`}
                                                                        size="small"
                                                                        color="primary"
                                                                    />
                                                                    {(analysis.cross_file_analysis?.regions_detected || []).map((region) => (
                                                                        <Chip key={region} label={region} size="small" variant="outlined" />
                                                                    ))}
                                                                </Stack>
                                                            </Stack>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12} md={6}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2, height: '100%' }}>
                                                        <CardContent>
                                                            <Typography variant="subtitle1" fontWeight={700}>Key Risks</Typography>
                                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                                {(analysis.cross_file_analysis?.risks || []).map((risk, idx) => (
                                                                    <Typography key={idx} variant="body2">- {risk}</Typography>
                                                                ))}
                                                            </Stack>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12} md={6}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2, height: '100%' }}>
                                                        <CardContent>
                                                            <Typography variant="subtitle1" fontWeight={700}>Recommendations</Typography>
                                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                                {(analysis.cross_file_analysis?.recommendations || []).map((rec, idx) => (
                                                                    <Typography key={idx} variant="body2">- {rec}</Typography>
                                                                ))}
                                                            </Stack>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                                        <CardContent>
                                                            <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>Per-file Snapshot</Typography>
                                                            <Table size="small">
                                                                <TableHead>
                                                                    <TableRow>
                                                                        <TableCell>File</TableCell>
                                                                        <TableCell>Format</TableCell>
                                                                        <TableCell>Summary</TableCell>
                                                                    </TableRow>
                                                                </TableHead>
                                                                <TableBody>
                                                                    {analysisFiles.map((f) => (
                                                                        <TableRow
                                                                            key={f.analysis_id}
                                                                            hover
                                                                            onClick={() => {
                                                                                setFindingsTab(f.analysis_id);
                                                                                setActiveFileId(f.analysis_id);
                                                                            }}
                                                                            sx={{ cursor: 'pointer' }}
                                                                        >
                                                                            <TableCell>{f.filename}</TableCell>
                                                                            <TableCell>{f.format}</TableCell>
                                                                            <TableCell>{f.summary}</TableCell>
                                                                        </TableRow>
                                                                    ))}
                                                                </TableBody>
                                                            </Table>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>
                                            </Grid>
                                        ) : (
                                            <Grid container spacing={2}>
                                                <Grid item xs={12}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                                        <CardContent>
                                                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1 }}>
                                                                <Typography variant="h6" fontWeight={700}>File Findings</Typography>
                                                                <Chip label={activeAnalysis.format} size="small" />
                                                                <Chip label={activeAnalysis.filename} size="small" variant="outlined" />
                                                            </Stack>
                                                            <Typography variant="subtitle1" fontWeight={600}>{activeAnalysis.summary}</Typography>
                                                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.8 }}>{activeAnalysis.explanation}</Typography>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12} md={6}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2, height: '100%' }}>
                                                        <CardContent>
                                                            <Typography variant="subtitle1" fontWeight={700} color="success.main">Strengths</Typography>
                                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                                {activeAnalysis.pros.map((p, idx) => (
                                                                    <Typography key={idx} variant="body2">- {p}</Typography>
                                                                ))}
                                                            </Stack>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12} md={6}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2, height: '100%' }}>
                                                        <CardContent>
                                                            <Typography variant="subtitle1" fontWeight={700} color="error.main">Risks</Typography>
                                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                                {activeAnalysis.cons.map((c, idx) => (
                                                                    <Typography key={idx} variant="body2">- {c}</Typography>
                                                                ))}
                                                            </Stack>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>

                                                <Grid item xs={12}>
                                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                                        <CardContent>
                                                            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                                                                <Typography variant="subtitle1" fontWeight={700}>Cost Impact Breakdown</Typography>
                                                                <Chip color="primary" label={`Estimated savings: $${totalEstimatedSavings.toFixed(2)}/month`} />
                                                            </Stack>
                                                            <Table size="small">
                                                                <TableHead>
                                                                    <TableRow>
                                                                        <TableCell>Service</TableCell>
                                                                        <TableCell>Suggested Change</TableCell>
                                                                        <TableCell align="right">Estimated Savings / month</TableCell>
                                                                    </TableRow>
                                                                </TableHead>
                                                                <TableBody>
                                                                    {activeAnalysis.cost_analysis.map((row, idx) => (
                                                                        <TableRow key={idx}>
                                                                            <TableCell>{row.service}</TableCell>
                                                                            <TableCell>{row.config}</TableCell>
                                                                            <TableCell align="right">${Number(row.estimated_monthly_cost_usd).toFixed(2)}</TableCell>
                                                                        </TableRow>
                                                                    ))}
                                                                </TableBody>
                                                            </Table>
                                                        </CardContent>
                                                    </Card>
                                                </Grid>
                                            </Grid>
                                        )}
                                    </Stack>
                                )}

                                {workspaceTab === 'questions' && (
                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                        <CardContent>
                                            <Stack spacing={1.2}>
                                                <Typography variant="h6" fontWeight={700}>Ask Questions</Typography>
                                                <Typography variant="body2" color="text.secondary">
                                                    Ask in plain business language. Responses are formatted for readability.
                                                </Typography>

                                                <Paper
                                                    variant="outlined"
                                                    sx={{
                                                        mt: 0.5,
                                                        p: 1.2,
                                                        maxHeight: 360,
                                                        overflowY: 'auto',
                                                        borderRadius: 2,
                                                    }}
                                                >
                                                    <Stack spacing={1}>
                                                        {chatMessages.map((m, idx) => (
                                                            <Box
                                                                key={idx}
                                                                sx={{
                                                                    alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                                                    maxWidth: '88%',
                                                                    p: 1.2,
                                                                    borderRadius: 1.5,
                                                                    bgcolor: m.role === 'user' ? 'primary.main' : '#eef4fa',
                                                                    color: m.role === 'user' ? 'white' : 'text.primary',
                                                                    fontSize: 14,
                                                                    lineHeight: 1.45,
                                                                }}
                                                            >
                                                                {m.role === 'assistant' ? (
                                                                    <Box sx={{ '& p': { m: 0.5 }, '& ul, & ol': { pl: 2.5, my: 0.5 }, '& li': { mb: 0.4 } }}>
                                                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                                                                    </Box>
                                                                ) : (
                                                                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{m.text}</Typography>
                                                                )}
                                                            </Box>
                                                        ))}
                                                    </Stack>
                                                </Paper>

                                                <Stack direction="row" spacing={1}>
                                                    <TextField
                                                        value={chatInput}
                                                        onChange={(e) => setChatInput(e.target.value)}
                                                        placeholder="Ask: Which options reduce risk fastest? Which saves most cost in next quarter?"
                                                        size="small"
                                                        fullWidth
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') {
                                                                e.preventDefault();
                                                                sendChat();
                                                            }
                                                        }}
                                                    />
                                                    <Button
                                                        variant="contained"
                                                        onClick={sendChat}
                                                        disabled={isChatting || !chatInput.trim()}
                                                        startIcon={isChatting ? <CircularProgress size={16} color="inherit" /> : <SendIcon />}
                                                    >
                                                        Send
                                                    </Button>
                                                </Stack>
                                            </Stack>
                                        </CardContent>
                                    </Card>
                                )}

                                {workspaceTab === 'improve' && (
                                    <Card variant="outlined" sx={{ borderRadius: 2 }}>
                                        <CardContent>
                                            <Stack spacing={1.4}>
                                                <Typography variant="h6" fontWeight={700}>Create Improved Version</Typography>
                                                <Typography variant="body2" color="text.secondary">
                                                    Define your priority and generate a polished version you can share with engineering teams.
                                                </Typography>

                                                <TextField
                                                    fullWidth
                                                    multiline
                                                    rows={3}
                                                    value={finalGoals}
                                                    onChange={(e) => setFinalGoals(e.target.value)}
                                                    placeholder="Optional goal: reduce monthly spend with minimal operational risk."
                                                />

                                                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
                                                    <Button
                                                        variant="contained"
                                                        onClick={generateFinal}
                                                        disabled={isGenerating}
                                                        startIcon={isGenerating ? <CircularProgress size={16} color="inherit" /> : <AutoFixHighIcon />}
                                                    >
                                                        {isGenerating ? 'Generating...' : 'Generate Improved Version'}
                                                    </Button>
                                                    <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => downloadVersion('original')}>
                                                        Download Original
                                                    </Button>
                                                    <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => downloadVersion('improved')}>
                                                        Download Improved
                                                    </Button>
                                                </Stack>

                                                <Paper
                                                    variant="outlined"
                                                    sx={{
                                                        p: 1.2,
                                                        minHeight: 280,
                                                        maxHeight: 420,
                                                        overflowY: 'auto',
                                                        borderRadius: 2,
                                                        bgcolor: '#0f172a',
                                                        color: '#e2e8f0',
                                                        fontFamily: 'Menlo, Monaco, Consolas, monospace',
                                                        fontSize: 12,
                                                        whiteSpace: 'pre-wrap',
                                                    }}
                                                >
                                                    {improvedContent || 'Generated content will appear here.'}
                                                </Paper>
                                            </Stack>
                                        </CardContent>
                                    </Card>
                                )}
                            </CardContent>
                        </Card>
                    </>
                )}

                {error && analysis && <Alert severity="error">{error}</Alert>}
            </Stack>
        </Box>
    );
};

export default IacWorkbenchPage;

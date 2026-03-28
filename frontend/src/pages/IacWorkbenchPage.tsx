import React, { useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Grid,
    Paper,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from '@mui/material';
import {
    AutoFixHigh as AutoFixHighIcon,
    CloudUpload as CloudUploadIcon,
    Download as DownloadIcon,
    Send as SendIcon,
} from '@mui/icons-material';

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

    const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [isChatting, setIsChatting] = useState(false);

    const [finalGoals, setFinalGoals] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [improvedContent, setImprovedContent] = useState('');

    const activeAnalysis = useMemo(() => {
        if (!analysis) return null;
        if (!analysis.files || analysis.files.length === 0) return analysis;
        return analysis.files.find((f) => f.analysis_id === activeFileId) || analysis.files[0];
    }, [analysis, activeFileId]);

    const totalEstimatedSavings = useMemo(() => {
        if (!activeAnalysis) return 0;
        return activeAnalysis.cost_analysis.reduce((sum, row) => sum + (Number(row.estimated_monthly_cost_usd) || 0), 0);
    }, [activeAnalysis]);

    const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        setSelectedFiles(files);
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
        setChatMessages([]);
        setImprovedContent('');

        try {
            const formData = new FormData();
            selectedFiles.forEach((file) => {
                formData.append('files', file);
            });

            const response = await fetch('/api/v1/iac/analyze', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const message = await parseApiError(response, `Upload failed with status ${response.status}`);
                throw new Error(message);
            }

            const data: AnalysisResponse = await response.json();
            setAnalysis(data);
            const firstFile = (data.files && data.files.length > 0) ? data.files[0] : data;
            setActiveFileId(firstFile.analysis_id);
            setImprovedContent(firstFile.improved_content);
            setChatMessages([
                {
                    role: 'assistant',
                    text: data.file_count && data.file_count > 1
                        ? `Cross-file analysis completed for ${data.file_count} files. Select a file below and ask me architecture or cost questions.`
                        : `Analysis completed for ${data.filename}. Ask me anything about architecture, cost trade-offs, or improvement strategy.`,
                },
            ]);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Upload failed');
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
            const response = await fetch('/api/v1/iac/chat', {
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
            const response = await fetch('/api/v1/iac/generate', {
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
            setError(err instanceof Error ? err.message : 'Final file generation failed');
        } finally {
            setIsGenerating(false);
        }
    };

    const downloadVersion = async (version: 'improved' | 'original') => {
        if (!activeAnalysis) return;

        try {
            const response = await fetch(`/api/v1/iac/${activeAnalysis.analysis_id}/download?version=${version}`);
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
                        p: { xs: 2, md: 3 },
                        borderRadius: 3,
                        background: 'linear-gradient(120deg, #0b5cab 0%, #00838f 100%)',
                        color: 'white',
                    }}
                >
                    <Typography variant="h4" fontWeight={800}>Cloud Setup Analyzer</Typography>
                    <Typography variant="body1" sx={{ mt: 1.2, opacity: 0.95 }}>
                        Upload your cloud setup files to understand cost impact, risks, and improvement options in plain language.
                        You can ask follow-up questions and generate a polished recommended version.
                    </Typography>
                </Paper>

                <Card sx={{ borderRadius: 3 }}>
                    <CardContent>
                        <Stack spacing={2}>
                            <Typography variant="h6" fontWeight={700}>1) Upload Cloud Files</Typography>
                            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                                <Button component="label" variant="outlined" startIcon={<CloudUploadIcon />}>
                                    Choose Files
                                    <input hidden type="file" multiple accept=".tf,.tfvars,.hcl,.yaml,.yml,.json" onChange={onFileChange} />
                                </Button>
                                <Typography variant="body2" color="text.secondary">
                                    {selectedFiles.length > 0
                                        ? `${selectedFiles.length} file(s) selected`
                                        : 'No files selected yet'}
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

                {analysis && activeAnalysis && (
                    <Grid container spacing={2}>
                        <Grid item xs={12} lg={7}>
                            {analysis.cross_file_analysis && (analysis.file_count || 0) > 1 && (
                                <Card sx={{ borderRadius: 3, mb: 2 }}>
                                    <CardContent>
                                        <Typography variant="h6" fontWeight={700}>Combined Findings</Typography>
                                        <Typography variant="body2" sx={{ mt: 1 }}>{analysis.cross_file_analysis.summary}</Typography>
                                        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
                                            <Chip label={`Files reviewed: ${analysis.file_count || analysis.files?.length || 0}`} size="small" />
                                            <Chip label={`Estimated savings: $${Number(analysis.cross_file_analysis.total_estimated_monthly_savings || 0).toFixed(2)}/month`} size="small" color="primary" />
                                            {(analysis.cross_file_analysis.regions_detected || []).map((region) => (
                                                <Chip key={region} label={region} size="small" variant="outlined" />
                                            ))}
                                        </Stack>
                                        <Typography variant="subtitle2" sx={{ mt: 1.5 }}>Key Risks to Review</Typography>
                                        <Stack spacing={0.5}>
                                            {(analysis.cross_file_analysis.risks || []).map((risk, idx) => (
                                                <Typography key={idx} variant="body2">• {risk}</Typography>
                                            ))}
                                        </Stack>
                                    </CardContent>
                                </Card>
                            )}

                            <Card sx={{ borderRadius: 3, mb: 2 }}>
                                <CardContent>
                                    <Stack spacing={1.2}>
                                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                            <Typography variant="h6" fontWeight={700}>2) Findings</Typography>
                                            <Chip label={activeAnalysis.format} size="small" />
                                            <Chip label={activeAnalysis.filename} size="small" variant="outlined" />
                                            {analysis.files && analysis.files.length > 1 && (
                                                <>
                                                    {analysis.files.map((f) => (
                                                        <Chip
                                                            key={f.analysis_id}
                                                            label={f.filename}
                                                            size="small"
                                                            color={f.analysis_id === activeAnalysis.analysis_id ? 'primary' : 'default'}
                                                            onClick={() => {
                                                                setActiveFileId(f.analysis_id);
                                                                setImprovedContent(f.improved_content);
                                                            }}
                                                        />
                                                    ))}
                                                </>
                                            )}
                                        </Stack>
                                        <Typography variant="subtitle1" fontWeight={600}>{activeAnalysis.summary}</Typography>
                                        <Typography variant="body2" color="text.secondary">{activeAnalysis.explanation}</Typography>
                                    </Stack>
                                </CardContent>
                            </Card>

                            <Grid container spacing={2}>
                                <Grid item xs={12} md={6}>
                                    <Card sx={{ borderRadius: 3, height: '100%' }}>
                                        <CardContent>
                                            <Typography variant="subtitle1" fontWeight={700} color="success.main">Pros</Typography>
                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                {activeAnalysis.pros.map((p, idx) => (
                                                    <Typography key={idx} variant="body2">• {p}</Typography>
                                                ))}
                                            </Stack>
                                        </CardContent>
                                    </Card>
                                </Grid>
                                <Grid item xs={12} md={6}>
                                    <Card sx={{ borderRadius: 3, height: '100%' }}>
                                        <CardContent>
                                            <Typography variant="subtitle1" fontWeight={700} color="error.main">Cons / Risks</Typography>
                                            <Stack spacing={0.8} sx={{ mt: 1 }}>
                                                {activeAnalysis.cons.map((c, idx) => (
                                                    <Typography key={idx} variant="body2">• {c}</Typography>
                                                ))}
                                            </Stack>
                                        </CardContent>
                                    </Card>
                                </Grid>
                            </Grid>

                            <Card sx={{ borderRadius: 3, mt: 2 }}>
                                <CardContent>
                                    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                                        <Typography variant="subtitle1" fontWeight={700}>Cost Analysis</Typography>
                                        <Chip color="primary" label={`Est. monthly savings: $${totalEstimatedSavings.toFixed(2)}`} />
                                    </Stack>
                                    <Table size="small">
                                        <TableHead>
                                            <TableRow>
                                                <TableCell>Service</TableCell>
                                                <TableCell>Config Change</TableCell>
                                                <TableCell align="right">Est. Savings / mo</TableCell>
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

                        <Grid item xs={12} lg={5}>
                            <Card sx={{ borderRadius: 3, mb: 2 }}>
                                <CardContent>
                                    <Typography variant="h6" fontWeight={700}>3) Ask Questions</Typography>
                                    <Paper variant="outlined" sx={{ mt: 1.5, p: 1.2, maxHeight: 280, overflowY: 'auto', borderRadius: 2 }}>
                                        <Stack spacing={1}>
                                            {chatMessages.map((m, idx) => (
                                                <Box
                                                    key={idx}
                                                    sx={{
                                                        alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                                        maxWidth: '88%',
                                                        p: 1,
                                                        borderRadius: 1.5,
                                                        bgcolor: m.role === 'user' ? 'primary.main' : '#eef4fa',
                                                        color: m.role === 'user' ? 'white' : 'text.primary',
                                                        whiteSpace: 'pre-wrap',
                                                        fontSize: 13,
                                                    }}
                                                >
                                                    {m.text}
                                                </Box>
                                            ))}
                                        </Stack>
                                    </Paper>
                                    <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                                        <TextField
                                            value={chatInput}
                                            onChange={(e) => setChatInput(e.target.value)}
                                            placeholder="Ask: What should leadership focus on? Where can we reduce risk or cost?"
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
                                </CardContent>
                            </Card>

                            <Card sx={{ borderRadius: 3 }}>
                                <CardContent>
                                    <Typography variant="h6" fontWeight={700}>4) Create Improved Version</Typography>
                                    <TextField
                                        fullWidth
                                        multiline
                                        rows={3}
                                        value={finalGoals}
                                        onChange={(e) => setFinalGoals(e.target.value)}
                                        placeholder="Optional goal: focus on lower cost, stronger reliability, or simpler operations."
                                        sx={{ mt: 1.2 }}
                                    />
                                    <Stack direction="row" spacing={1} sx={{ mt: 1.2 }}>
                                        <Button
                                            variant="contained"
                                            onClick={generateFinal}
                                            disabled={isGenerating}
                                            startIcon={isGenerating ? <CircularProgress size={16} color="inherit" /> : <AutoFixHighIcon />}
                                        >
                                            {isGenerating ? 'Generating...' : 'Generate Improved Version'}
                                        </Button>
                                        <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => downloadVersion('original')}>
                                            Original
                                        </Button>
                                        <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => downloadVersion('improved')}>
                                            Improved
                                        </Button>
                                    </Stack>
                                    <Paper
                                        variant="outlined"
                                        sx={{
                                            mt: 1.5,
                                            p: 1.2,
                                            maxHeight: 260,
                                            overflowY: 'auto',
                                            borderRadius: 2,
                                            bgcolor: '#0f172a',
                                            color: '#e2e8f0',
                                            fontFamily: 'Menlo, Monaco, Consolas, monospace',
                                            fontSize: 12,
                                            whiteSpace: 'pre-wrap',
                                        }}
                                    >
                                        {improvedContent || 'Final generated file will appear here...'}
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

export default IacWorkbenchPage;

import React from 'react';
import { Box, Button, Typography, Paper } from '@mui/material';
import { Refresh as RefreshIcon } from '@mui/icons-material';

interface Props {
    children: React.ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

class ErrorBoundary extends React.Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo) {
        console.error('ErrorBoundary caught an error:', error, info);
    }

    handleReset = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (this.state.hasError) {
            return (
                <Box
                    sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '100%',
                        p: 4
                    }}
                >
                    <Paper
                        elevation={0}
                        sx={{
                            p: 4,
                            maxWidth: 480,
                            textAlign: 'center',
                            borderRadius: 3,
                            border: '1px solid rgba(0,0,0,0.08)',
                            boxShadow: '0 4px 24px rgba(0,0,0,0.08)'
                        }}
                    >
                        <Typography variant="h6" sx={{ fontWeight: 600, mb: 1, color: 'text.primary' }}>
                            Something went wrong rendering this view
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 3 }}>
                            An unexpected error occurred. You can try refreshing or start a new chat.
                        </Typography>
                        <Button
                            variant="contained"
                            startIcon={<RefreshIcon />}
                            onClick={this.handleReset}
                            sx={{
                                textTransform: 'none',
                                background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
                                '&:hover': {
                                    background: 'linear-gradient(135deg, #0D47A1 0%, #0A3880 100%)'
                                }
                            }}
                        >
                            Try again
                        </Button>
                    </Paper>
                </Box>
            );
        }

        return this.props.children;
    }
}

export default ErrorBoundary;

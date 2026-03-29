import React, { ReactNode } from 'react';
import { Box, Button, Typography } from '@mui/material';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    error?: Error;
}

export default class ErrorBoundary extends React.Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('Error caught by ErrorBoundary:', error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <Box
                    sx={{
                        p: 3,
                        textAlign: 'center',
                        minHeight: '100vh',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        alignItems: 'center',
                        bgcolor: '#f8fafc',
                    }}
                >
                    <Typography variant="h5" sx={{ mb: 1, color: '#0f172a', fontWeight: 700 }}>
                        Something went wrong
                    </Typography>
                    <Typography variant="body2" sx={{ mb: 3, color: '#64748b' }}>
                        {this.state.error?.message || 'An unexpected error occurred'}
                    </Typography>
                    <Button
                        onClick={() => {
                            this.setState({ hasError: false });
                            window.location.href = '/';
                        }}
                        variant="contained"
                        sx={{ textTransform: 'none', fontWeight: 600 }}
                    >
                        Go to Home
                    </Button>
                </Box>
            );
        }

        return this.props.children;
    }
}

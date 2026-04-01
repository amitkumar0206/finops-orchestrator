import React, { useState, useEffect } from 'react';
import { Box, Container, TextField, Button, Typography, Alert, Paper, CircularProgress } from '@mui/material';
import { useNavigate } from 'react-router-dom';

interface LoginPageProps {
    onLoginSuccess: () => void;
}

const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate();

    // Check if already authenticated
    useEffect(() => {
        const isAuthenticated = localStorage.getItem('aasmaa_authenticated') === 'true';
        if (isAuthenticated) {
            onLoginSuccess();
            navigate('/');
        }
    }, [onLoginSuccess, navigate]);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            if (!username.trim() || !password.trim()) {
                throw new Error('Please enter both username and password');
            }

            // Verify backend is accessible before allowing entry.
            const backendCheck = await fetch('/api/v1/health');
            if (!backendCheck.ok) {
                throw new Error('Backend service is not accessible');
            }

            localStorage.setItem('aasmaa_authenticated', 'true');
            localStorage.setItem('aasmaa_username', username.trim());
            onLoginSuccess();
            navigate('/');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Login failed. Please try again.');
            console.error('Login error:', err);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <Box
            sx={{
                minHeight: '100vh',
                background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif'
            }}
        >
            <Container maxWidth="sm">
                <Paper
                    elevation={3}
                    sx={{
                        padding: 4,
                        borderRadius: 2,
                        backgroundColor: '#ffffff',
                        boxShadow: '0 10px 40px rgba(0, 0, 0, 0.2)'
                    }}
                >
                    {/* Logo */}
                    <Box
                        sx={{
                            display: 'flex',
                            justifyContent: 'center',
                            marginBottom: 3
                        }}
                    >
                        <Box
                            component="img"
                            src="/aasmaa-logo.png?v=20260327b"
                            alt="aasmaa"
                            sx={{
                                width: 220,
                                maxWidth: '100%',
                                height: 'auto',
                                objectFit: 'contain',
                                display: 'block'
                            }}
                        />
                    </Box>

                    {/* Title */}
                    <Typography
                        variant="h4"
                        component="h1"
                        sx={{
                            textAlign: 'center',
                            fontWeight: 600,
                            color: '#1565C0',
                            marginBottom: 1
                        }}
                    >
                        Sign in
                    </Typography>

                    <Typography
                        variant="body2"
                        sx={{
                            textAlign: 'center',
                            color: '#666',
                            marginBottom: 3
                        }}
                    >
                        Cut Cloud Costs Faster with AI-Powered Insights
                    </Typography>

                    {/* Error Alert */}
                    {error && (
                        <Alert severity="error" sx={{ marginBottom: 2 }}>
                            {error}
                        </Alert>
                    )}

                    {/* Login Form */}
                    <Box component="form" onSubmit={handleLogin}>
                        <TextField
                            fullWidth
                            label="Username"
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            disabled={isLoading}
                            sx={{
                                marginBottom: 2,
                                '& .MuiOutlinedInput-root': {
                                    '&:hover fieldset': {
                                        borderColor: '#1565C0'
                                    }
                                },
                                '& .MuiOutlinedInput-root.Mui-focused fieldset': {
                                    borderColor: '#1565C0'
                                }
                            }}
                            autoFocus
                        />

                        <TextField
                            fullWidth
                            label="Password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            disabled={isLoading}
                            sx={{
                                marginBottom: 3,
                                '& .MuiOutlinedInput-root': {
                                    '&:hover fieldset': {
                                        borderColor: '#1565C0'
                                    }
                                },
                                '& .MuiOutlinedInput-root.Mui-focused fieldset': {
                                    borderColor: '#1565C0'
                                }
                            }}
                        />

                        {/* Sign In Button */}
                        <Button
                            type="submit"
                            fullWidth
                            variant="contained"
                            disabled={isLoading || !username || !password}
                            sx={{
                                background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
                                padding: '10px 20px',
                                fontWeight: 600,
                                fontSize: '1rem',
                                textTransform: 'none',
                                borderRadius: 1,
                                '&:hover': {
                                    background: 'linear-gradient(135deg, #0D47A1 0%, #0D3A90 100%)',
                                    boxShadow: '0 4px 12px rgba(13, 71, 161, 0.4)'
                                },
                                '&:disabled': {
                                    background: '#ccc'
                                }
                            }}
                        >
                            {isLoading ? (
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <CircularProgress size={20} color="inherit" />
                                    Signing in...
                                </Box>
                            ) : (
                                'Sign In'
                            )}
                        </Button>
                    </Box>

                    {/* Footer Text */}
                    <Typography
                        variant="caption"
                        sx={{
                            display: 'block',
                            textAlign: 'center',
                            color: '#999',
                            marginTop: 2,
                            fontSize: '0.85rem'
                        }}
                    >
                        Secure sign-in powered by aasmaa
                    </Typography>
                </Paper>

                {/* Bottom branding */}
                <Box
                    sx={{
                        textAlign: 'center',
                        marginTop: 4,
                        color: 'rgba(255, 255, 255, 0.7)'
                    }}
                >
                    <Typography variant="body2">
                        © 2026 Aasmaa Solutions. Cut Cloud Costs Faster.
                    </Typography>
                </Box>
            </Container>
        </Box>
    );
};

export default LoginPage;

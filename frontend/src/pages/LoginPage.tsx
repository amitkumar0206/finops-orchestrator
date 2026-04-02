import React, { useState, useEffect } from 'react';
import { Box, Container, TextField, Button, Typography, Alert, Paper, CircularProgress } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const LoginPage: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate();
    const { login, isAuthenticated } = useAuth();

    useEffect(() => {
        if (isAuthenticated) {
            navigate('/');
        }
    }, [isAuthenticated, navigate]);

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setIsLoading(true);

        try {
            if (!email.trim() || !password.trim()) {
                throw new Error('Please enter both email and password');
            }

            await login({ email: email.trim(), password: password.trim() });
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
                background: 'linear-gradient(130deg, #0f172a 0%, #1565C0 54%, #dbeafe 140%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif',
                px: 2,
                py: 4,
            }}
        >
            <Container maxWidth="sm">
                <Paper
                    elevation={3}
                    sx={{
                        padding: 4,
                        borderRadius: 4,
                        backgroundColor: 'rgba(255, 255, 255, 0.96)',
                        boxShadow: '0 18px 48px rgba(15, 23, 42, 0.24)',
                        height: '100%',
                    }}
                >
                    <Box sx={{ display: 'flex', justifyContent: 'center', marginBottom: 3 }}>
                        <Box
                            component="img"
                            src="/aasmaa-logo.png?v=20260327b"
                            alt="aasmaa"
                            sx={{ width: 220, maxWidth: '100%', height: 'auto', objectFit: 'contain', display: 'block' }}
                        />
                    </Box>

                    <Typography variant="h4" component="h1" sx={{ textAlign: 'center', fontWeight: 700, color: '#0f172a', marginBottom: 1 }}>
                        Demo Sign in
                    </Typography>

                    <Typography variant="body2" sx={{ textAlign: 'center', color: '#475569', marginBottom: 3 }}>
                        Sign in as an admin, developer, or DevOps user and see the role-specific product surface.
                    </Typography>

                    {error && (
                        <Alert severity="error" sx={{ marginBottom: 2 }}>
                            {error}
                        </Alert>
                    )}

                    <Box component="form" onSubmit={handleLogin}>
                        <TextField
                            fullWidth
                            label="Email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            disabled={isLoading}
                            sx={{ marginBottom: 2 }}
                            autoFocus
                        />

                        <TextField
                            fullWidth
                            label="Password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            disabled={isLoading}
                            sx={{ marginBottom: 3 }}
                        />

                        <Button
                            type="submit"
                            fullWidth
                            variant="contained"
                            disabled={isLoading || !email || !password}
                            sx={{
                                background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
                                padding: '10px 20px',
                                fontWeight: 700,
                                fontSize: '1rem',
                                textTransform: 'none',
                                borderRadius: 2,
                                '&:hover': {
                                    background: 'linear-gradient(135deg, #0D47A1 0%, #0D3A90 100%)',
                                    boxShadow: '0 4px 12px rgba(13, 71, 161, 0.4)',
                                },
                                '&:disabled': {
                                    background: '#cbd5e1',
                                },
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
                </Paper>

                <Box
                    sx={{
                        textAlign: 'center',
                        marginTop: 4,
                        color: 'rgba(255, 255, 255, 0.7)',
                    }}
                >
                    <Typography variant="body2">
                        © 2026 Aasmaa Solutions. Demo identities are config-backed and database-free.
                    </Typography>
                </Box>
            </Container>
        </Box>
    );
};

export default LoginPage;

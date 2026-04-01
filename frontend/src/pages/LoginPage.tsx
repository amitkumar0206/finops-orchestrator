import React, { useState, useEffect } from 'react';
import { Box, Container, TextField, Button, Typography, Alert, Paper, CircularProgress, Grid, Chip, Stack } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const LoginPage: React.FC = () => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const navigate = useNavigate();
    const { login, isAuthenticated, demoCatalog } = useAuth();

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
            <Container maxWidth="lg">
                <Grid container spacing={3} sx={{ alignItems: 'stretch' }}>
                    <Grid item xs={12} md={7}>
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
                    </Grid>

                    <Grid item xs={12} md={5}>
                        <Paper
                            elevation={0}
                            sx={{
                                p: 3.2,
                                borderRadius: 4,
                                height: '100%',
                                color: 'white',
                                background: 'linear-gradient(160deg, rgba(15,23,42,0.9) 0%, rgba(13,71,161,0.84) 100%)',
                                border: '1px solid rgba(255,255,255,0.14)',
                                backdropFilter: 'blur(8px)',
                            }}
                        >
                            <Typography sx={{ fontWeight: 800, fontSize: '1.2rem', mb: 1.2 }}>
                                Demo accounts
                            </Typography>
                            <Typography sx={{ color: 'rgba(255,255,255,0.78)', fontSize: '0.9rem', mb: 2.5 }}>
                                These users are backed by the new config-based identity store. Click any card to prefill credentials.
                            </Typography>

                            <Stack spacing={1.5}>
                                {demoCatalog?.users?.map((account) => (
                                    <Paper
                                        key={account.id}
                                        elevation={0}
                                        onClick={() => {
                                            setEmail(account.email);
                                            setPassword(account.demo_password_hint || '');
                                        }}
                                        sx={{
                                            p: 2,
                                            borderRadius: 3,
                                            bgcolor: 'rgba(255,255,255,0.1)',
                                            border: '1px solid rgba(255,255,255,0.16)',
                                            cursor: 'pointer',
                                            transition: 'transform 0.18s ease, background-color 0.18s ease',
                                            '&:hover': {
                                                transform: 'translateY(-1px)',
                                                bgcolor: 'rgba(255,255,255,0.16)',
                                            },
                                        }}
                                    >
                                        <Stack direction="row" spacing={1} sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                            <Box>
                                                <Typography sx={{ fontWeight: 700 }}>{account.full_name}</Typography>
                                                <Typography sx={{ fontSize: '0.84rem', color: 'rgba(255,255,255,0.76)' }}>{account.email}</Typography>
                                                <Typography sx={{ fontSize: '0.78rem', color: 'rgba(255,255,255,0.7)', mt: 0.6 }}>
                                                    Password: {account.demo_password_hint}
                                                </Typography>
                                            </Box>
                                            <Chip label={account.org_role} size="small" sx={{ bgcolor: 'rgba(219,234,254,0.2)', color: '#dbeafe', fontWeight: 700 }} />
                                        </Stack>
                                        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', mt: 1.4 }}>
                                            {Object.entries(account.feature_access || {}).filter(([, enabled]) => enabled).map(([feature]) => (
                                                <Chip key={`${account.id}-${feature}`} label={feature} size="small" sx={{ bgcolor: 'rgba(255,255,255,0.12)', color: 'white' }} />
                                            ))}
                                        </Stack>
                                    </Paper>
                                ))}
                            </Stack>
                        </Paper>
                    </Grid>
                </Grid>

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

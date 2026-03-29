import React, { useState } from 'react';
import { Box, Button, Paper, Stack, TextField, Typography } from '@mui/material';

interface LoginPageProps {
    onLoginSuccess: () => void;
}

const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');

    const handleLogin = () => {
        const safeUsername = username.trim() || 'user';
        localStorage.setItem('aasmaa_username', safeUsername);
        onLoginSuccess();
    };

    const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        handleLogin();
    };

    return (
        <Box
            sx={{
                minHeight: '100vh',
                display: 'grid',
                placeItems: 'center',
                px: 2,
                background: 'linear-gradient(135deg, #0f5fad 0%, #0b8f9e 100%)',
            }}
        >
            <Paper
                elevation={0}
                sx={{
                    width: '100%',
                    maxWidth: 420,
                    p: 3,
                    borderRadius: 3,
                    border: '1px solid rgba(255,255,255,0.26)',
                    bgcolor: 'rgba(255,255,255,0.95)',
                }}
            >
                <Stack component="form" onSubmit={handleSubmit} spacing={2}>
                    <Box sx={{ display: 'flex', justifyContent: 'center', pb: 0.5 }}>
                        <img src="/aasmaa-logo.png" alt="aasmaa" style={{ height: 36 }} />
                    </Box>
                    <Typography variant="h5" sx={{ fontWeight: 700, color: '#0f172a' }}>
                        Welcome to Aasmaa
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#475569' }}>
                        Sign in to continue to your FinOps workspace.
                    </Typography>
                    <TextField
                        label="Username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        size="small"
                        fullWidth
                    />
                    <TextField
                        label="Password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        size="small"
                        fullWidth
                    />
                    <Button
                        type="submit"
                        variant="contained"
                        size="large"
                        sx={{ textTransform: 'none', fontWeight: 700, borderRadius: 2 }}
                    >
                        Log In
                    </Button>
                </Stack>
            </Paper>
        </Box>
    );
};

export default LoginPage;

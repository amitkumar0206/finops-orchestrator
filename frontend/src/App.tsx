import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, useLocation } from 'react-router-dom';
import { Box, AppBar, Toolbar, Chip, Button } from '@mui/material';
import { TrendingUp as TrendingUpIcon, Logout as LogoutIcon } from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import LoginPage from './pages/LoginPage';
import IacWorkbenchPage from './pages/IacWorkbenchPage';
import ErrorBoundary from './components/ErrorBoundary';
import { ScopeIndicator } from './components/Scope';

const App: React.FC = () => {
  const location = useLocation();
  const [scopeVersion, setScopeVersion] = useState(0);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  // Check authentication on component mount.
  // In demo mode we keep auth state client-side to avoid forced re-login loops.
  useEffect(() => {
    const isAuthed = localStorage.getItem('aasmaa_authenticated') === 'true';
    setIsAuthenticated(isAuthed);
    setIsCheckingAuth(false);
  }, []);

  const handleScopeChange = () => {
    setScopeVersion((v) => v + 1);
  };

  const handleLoginSuccess = () => {
    localStorage.setItem('aasmaa_authenticated', 'true');
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem('aasmaa_authenticated');
    localStorage.removeItem('aasmaa_username');
    setIsAuthenticated(false);
  };

  if (isCheckingAuth) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100vh',
          background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)'
        }}
      >
        <Box sx={{ color: 'white', textAlign: 'center' }}>
          <div style={{ fontSize: '24px', marginBottom: '20px' }}>Loading...</div>
        </Box>
      </Box>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#f8fafc', flexDirection: 'column' }}>
      <AppBar
        position="static"
        elevation={0}
        sx={{
          background: 'linear-gradient(135deg, #1565C0 0%, #0D47A1 100%)',
          borderBottom: '1px solid rgba(255, 255, 255, 0.1)'
        }}
      >
        <Toolbar sx={{ py: 1 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'rgba(255, 255, 255, 0.96)',
              borderRadius: 1.5,
              px: 1.25,
              py: 0.75,
              mr: 3,
              boxShadow: '0 2px 10px rgba(0, 0, 0, 0.12)'
            }}
          >
            <Box
              component="img"
              src="/aasmaa-logo.png?v=20260327b"
              alt="aasmaa"
              sx={{
                width: 170,
                maxWidth: '100%',
                height: 'auto',
                objectFit: 'contain',
                display: 'block'
              }}
            />
          </Box>
          <Box sx={{ flexGrow: 1 }}>
            <ScopeIndicator onScopeChange={handleScopeChange} />
          </Box>
          <Chip
            icon={<TrendingUpIcon sx={{ fontSize: 18 }} />}
            label="Live"
            size="small"
            sx={{
              bgcolor: 'rgba(255, 255, 255, 0.25)',
              backdropFilter: 'blur(10px)',
              color: 'white',
              fontWeight: 600,
              border: '1px solid rgba(255, 255, 255, 0.3)',
              mr: 2
            }}
          />
          <Button
            color="inherit"
            size="small"
            component={Link}
            to="/chat"
            sx={{
              textTransform: 'none',
              mr: 1,
              backgroundColor: location.pathname === '/chat' || location.pathname === '/'
                ? 'rgba(255, 255, 255, 0.15)'
                : 'transparent',
            }}
          >
            Cost Chat
          </Button>
          <Button
            color="inherit"
            size="small"
            component={Link}
            to="/iac"
            sx={{
              textTransform: 'none',
              mr: 1,
              backgroundColor: location.pathname === '/iac'
                ? 'rgba(255, 255, 255, 0.15)'
                : 'transparent',
            }}
          >
            IaC Workbench
          </Button>
          <Button
            color="inherit"
            size="small"
            startIcon={<LogoutIcon />}
            onClick={handleLogout}
            sx={{
              textTransform: 'none',
              '&:hover': {
                backgroundColor: 'rgba(255, 255, 255, 0.1)'
              }
            }}
          >
            Logout
          </Button>
        </Toolbar>
      </AppBar>

      <Box
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}
      >
        <Routes>
          <Route path="/" element={<ErrorBoundary><ChatInterface key={scopeVersion} /></ErrorBoundary>} />
          <Route path="/chat" element={<ErrorBoundary><ChatInterface key={scopeVersion} /></ErrorBoundary>} />
          <Route path="/iac" element={<ErrorBoundary><IacWorkbenchPage /></ErrorBoundary>} />
        </Routes>
      </Box>
    </Box>
  );
};

export default App;
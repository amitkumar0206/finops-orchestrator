import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import {
  Box,
  AppBar,
  Toolbar,
  Chip,
  Button,
  IconButton,
  Menu,
  MenuItem,
  Divider,
} from '@mui/material';
import {
  TrendingUp as TrendingUpIcon,
  Logout as LogoutIcon,
  Menu as MenuIcon,
} from '@mui/icons-material';

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
  const [navMenuAnchor, setNavMenuAnchor] = useState<null | HTMLElement>(null);

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

  const handleOpenNavMenu = (event: React.MouseEvent<HTMLElement>) => {
    setNavMenuAnchor(event.currentTarget);
  };

  const handleCloseNavMenu = () => {
    setNavMenuAnchor(null);
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

  const activeRoute = location.pathname.startsWith('/iac') ? '/iac' : '/chat';

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
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <ScopeIndicator onScopeChange={handleScopeChange} />
          </Box>

          <Box
            sx={{
              display: { xs: 'none', md: 'flex' },
              alignItems: 'center',
              gap: 0.5,
              mr: 1,
              p: 0.5,
              borderRadius: 2,
              backgroundColor: 'rgba(255, 255, 255, 0.1)',
              border: '1px solid rgba(255, 255, 255, 0.15)'
            }}
          >
            <Button
              component={Link}
              to="/chat"
              color="inherit"
              size="small"
              sx={{
                px: 1.6,
                textTransform: 'none',
                fontWeight: 700,
                color: activeRoute === '/chat' ? '#ffffff' : 'rgba(255, 255, 255, 0.78)',
                borderBottom: activeRoute === '/chat' ? '2px solid #ffffff' : '2px solid transparent',
                borderRadius: 1,
              }}
            >
              Cost Chat
            </Button>
            <Button
              component={Link}
              to="/iac"
              color="inherit"
              size="small"
              sx={{
                px: 1.6,
                textTransform: 'none',
                fontWeight: 700,
                color: activeRoute === '/iac' ? '#ffffff' : 'rgba(255, 255, 255, 0.78)',
                borderBottom: activeRoute === '/iac' ? '2px solid #ffffff' : '2px solid transparent',
                borderRadius: 1,
              }}
            >
              IaC Workbench
            </Button>
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
              mr: { xs: 1, md: 2 }
            }}
          />

          <IconButton
            color="inherit"
            onClick={handleOpenNavMenu}
            sx={{
              display: { xs: 'inline-flex', md: 'none' },
              mr: 0.5,
              border: '1px solid rgba(255, 255, 255, 0.25)',
              backgroundColor: 'rgba(255, 255, 255, 0.08)'
            }}
          >
            <MenuIcon />
          </IconButton>

          <Menu
            anchorEl={navMenuAnchor}
            open={Boolean(navMenuAnchor)}
            onClose={handleCloseNavMenu}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            PaperProps={{
              sx: {
                mt: 1,
                minWidth: 220,
                borderRadius: 2,
                border: '1px solid rgba(15, 23, 42, 0.08)'
              }
            }}
          >
            <MenuItem
              component={Link}
              to="/chat"
              onClick={handleCloseNavMenu}
              selected={activeRoute === '/chat'}
            >
              Cost Chat
            </MenuItem>
            <MenuItem
              component={Link}
              to="/iac"
              onClick={handleCloseNavMenu}
              selected={activeRoute === '/iac'}
            >
              IaC Workbench
            </MenuItem>
            <Divider />
            <MenuItem
              onClick={() => {
                handleCloseNavMenu();
                handleLogout();
              }}
            >
              Logout
            </MenuItem>
          </Menu>

          <Button
            color="inherit"
            size="small"
            startIcon={<LogoutIcon />}
            onClick={handleLogout}
            sx={{
              display: { xs: 'none', md: 'inline-flex' },
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
          <Route path="/chat/*" element={<Navigate to="/chat" replace />} />
          <Route path="/iac" element={<ErrorBoundary><IacWorkbenchPage /></ErrorBoundary>} />
          <Route path="/iac/*" element={<Navigate to="/iac" replace />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </Box>
    </Box>
  );
};

export default App;
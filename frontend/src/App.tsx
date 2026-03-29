import React, { useState, useEffect } from 'react';
import { Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import {
  Box,
  Button,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
} from '@mui/material';
import {
  Logout as LogoutIcon,
  Add as AddIcon,
  HomeOutlined as HomeOutlinedIcon,
  ForumOutlined as ForumOutlinedIcon,
  InsightsOutlined as InsightsOutlinedIcon,
  AutoFixHighOutlined as AutoFixHighOutlinedIcon,
  SettingsOutlined as SettingsOutlinedIcon,
  PersonOutline as PersonOutlineIcon,
} from '@mui/icons-material';

import ChatInterface from './components/Chat/ChatInterface';
import LoginPage from './pages/LoginPage';
import LandingPage from './pages/LandingPage';
import IacWorkbenchPage from './pages/IacWorkbenchPage';
import GenerateBlueprintPage from './pages/GenerateBlueprintPage';
import SettingsPage from './pages/SettingsPage';
import ProfilePage from './pages/ProfilePage';
import ErrorBoundary from './components/ErrorBoundary';
import { ScopeIndicator } from './components/Scope';

const App: React.FC = () => {
  const location = useLocation();
  const [scopeVersion, setScopeVersion] = useState(0);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);

  // Collapse sidebar whenever the route changes (so navigating always starts collapsed)
  useEffect(() => {
    setIsSidebarCollapsed(true);
  }, [location.pathname]);

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

  const activeRoute = (() => {
    if (location.pathname === '/' || location.pathname.startsWith('/home')) return '/';
    if (location.pathname.startsWith('/generate')) return '/generate';
    if (location.pathname.startsWith('/iac') || location.pathname.startsWith('/analyze')) return '/analyze';
    if (location.pathname.startsWith('/settings')) return '/settings';
    if (location.pathname.startsWith('/profile')) return '/profile';
    return '/chat';
  })();

  const hideSidebar = location.pathname === '/' || location.pathname.startsWith('/home');

  const navItems = [
    { key: '/', label: 'Home', icon: <HomeOutlinedIcon sx={{ fontSize: 20 }} /> },
    { key: '/chat', label: 'Cost Chat', icon: <ForumOutlinedIcon sx={{ fontSize: 20 }} /> },
    { key: '/analyze', label: 'Analyze', icon: <InsightsOutlinedIcon sx={{ fontSize: 20 }} /> },
    { key: '/generate', label: 'Generate', icon: <AutoFixHighOutlinedIcon sx={{ fontSize: 20 }} /> },
  ] as const;

  return (
    <Box sx={{ display: 'flex', height: '100vh', bgcolor: '#f8fafc' }}>
      {!hideSidebar && (
        <Box
          onMouseEnter={() => setIsSidebarCollapsed(false)}
          onMouseLeave={() => setIsSidebarCollapsed(true)}
          sx={{
            width: isSidebarCollapsed ? 76 : 248,
            transition: 'width 0.22s ease',
            bgcolor: '#ffffff',
            borderRight: '1px solid rgba(15, 23, 42, 0.08)',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              px: isSidebarCollapsed ? 0.75 : 1.5,
              py: 1.25,
              borderBottom: '1px solid rgba(15, 23, 42, 0.06)',
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: isSidebarCollapsed ? 38 : '100%',
                height: 38,
                borderRadius: 1.4,
                bgcolor: isSidebarCollapsed ? '#1565C0' : 'transparent',
              }}
            >
              {isSidebarCollapsed ? (
                <img src="/aasmaa-icon.png" alt="aasmaa" style={{ width: 22, height: 22, filter: 'brightness(0) invert(1)' }} />
              ) : (
                <img src="/aasmaa-logo.png" alt="aasmaa.ai" style={{ height: 32, maxWidth: 180 }} />
              )}
            </Box>
          </Box>

          {!isSidebarCollapsed && (
            <Box sx={{ px: 1.25, pt: 0.5, pb: 0.25 }}>
              <ScopeIndicator onScopeChange={handleScopeChange} />
            </Box>
          )}

          <Box sx={{ px: isSidebarCollapsed ? 1 : 1.25, pt: 1.25 }}>
            <Tooltip title={isSidebarCollapsed ? 'New Chat' : ''} placement="right">
              <Button
                component={Link}
                to="/chat"
                onClick={() => setScopeVersion((v) => v + 1)}
                fullWidth
                variant="text"
                startIcon={<AddIcon />}
                sx={{
                  minWidth: 0,
                  justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                  textTransform: 'none',
                  fontWeight: 600,
                  fontSize: '0.92rem',
                  borderRadius: 2,
                  px: isSidebarCollapsed ? 1 : 1.3,
                  py: 0.75,
                  minHeight: 44,
                  color: '#334155',
                  bgcolor: 'transparent',
                  '&:hover': { bgcolor: 'rgba(15,23,42,0.06)' },
                  '& .MuiButton-startIcon': {
                    mr: isSidebarCollapsed ? 0 : 1,
                    ml: 0,
                  },
                }}
              >
                {!isSidebarCollapsed && 'New Chat'}
              </Button>
            </Tooltip>
          </Box>

          <List sx={{ pt: 1.2, px: isSidebarCollapsed ? 0.9 : 1.2 }}>
            {navItems.map((item) => (
              <ListItem key={item.key} disablePadding sx={{ mb: 0.5 }}>
                <Tooltip title={isSidebarCollapsed ? item.label : ''} placement="right">
                  <ListItemButton
                    component={Link}
                    to={item.key}
                    selected={activeRoute === item.key}
                    sx={{
                      borderRadius: 2,
                      minHeight: 44,
                      justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                      px: isSidebarCollapsed ? 1 : 1.3,
                      color: activeRoute === item.key ? '#0D47A1' : '#334155',
                      bgcolor: activeRoute === item.key ? 'rgba(21,101,192,0.12)' : 'transparent',
                      '&:hover': {
                        bgcolor: activeRoute === item.key ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)',
                      },
                    }}
                  >
                    <ListItemIcon
                      sx={{
                        minWidth: isSidebarCollapsed ? 0 : 34,
                        color: 'inherit',
                      }}
                    >
                      {item.icon}
                    </ListItemIcon>
                    {!isSidebarCollapsed && (
                      <ListItemText
                        primary={item.label}
                        primaryTypographyProps={{ fontSize: '0.92rem', fontWeight: 600 }}
                      />
                    )}
                  </ListItemButton>
                </Tooltip>
              </ListItem>
            ))}
          </List>

          <Box sx={{ flexGrow: 1 }} />

          <List sx={{ px: isSidebarCollapsed ? 0.9 : 1.2, pb: 1.2 }}>
            <ListItem disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={isSidebarCollapsed ? 'Settings' : ''} placement="right">
                <ListItemButton
                  component={Link}
                  to="/settings"
                  selected={activeRoute === '/settings'}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: activeRoute === '/settings' ? '#0D47A1' : '#334155',
                    bgcolor: activeRoute === '/settings' ? 'rgba(21,101,192,0.12)' : 'transparent',
                    '&:hover': { bgcolor: activeRoute === '/settings' ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)' },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: '#334155' }}>
                    <SettingsOutlinedIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Settings" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>

            <ListItem disablePadding sx={{ mb: 0.5 }}>
              <Tooltip title={isSidebarCollapsed ? 'Profile' : ''} placement="right">
                <ListItemButton
                  component={Link}
                  to="/profile"
                  selected={activeRoute === '/profile'}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: activeRoute === '/profile' ? '#0D47A1' : '#334155',
                    bgcolor: activeRoute === '/profile' ? 'rgba(21,101,192,0.12)' : 'transparent',
                    '&:hover': { bgcolor: activeRoute === '/profile' ? 'rgba(21,101,192,0.16)' : 'rgba(15,23,42,0.05)' },
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: '#334155' }}>
                    <PersonOutlineIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Profile" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>

            <ListItem disablePadding>
              <Tooltip title={isSidebarCollapsed ? 'Logout' : ''} placement="right">
                <ListItemButton
                  onClick={handleLogout}
                  sx={{
                    borderRadius: 2,
                    minHeight: 42,
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    px: isSidebarCollapsed ? 1 : 1.3,
                    color: '#334155',
                  }}
                >
                  <ListItemIcon sx={{ minWidth: isSidebarCollapsed ? 0 : 34, color: 'inherit' }}>
                    <LogoutIcon sx={{ fontSize: 20 }} />
                  </ListItemIcon>
                  {!isSidebarCollapsed && <ListItemText primary="Logout" primaryTypographyProps={{ fontSize: '0.9rem' }} />}
                </ListItemButton>
              </Tooltip>
            </ListItem>
          </List>
        </Box>
      )}

      <Box
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: hideSidebar ? 'auto' : 'hidden',
        }}
      >
        <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
          <Routes>
            <Route path="/" element={<ErrorBoundary><LandingPage /></ErrorBoundary>} />
            <Route path="/home" element={<Navigate to="/" replace />} />
            <Route path="/home/*" element={<Navigate to="/" replace />} />
            <Route path="/chat" element={<ErrorBoundary><ChatInterface key={scopeVersion} /></ErrorBoundary>} />
            <Route path="/chat/*" element={<Navigate to="/chat" replace />} />
            <Route path="/analyze" element={<ErrorBoundary><IacWorkbenchPage /></ErrorBoundary>} />
            <Route path="/analyze/*" element={<Navigate to="/analyze" replace />} />
            <Route path="/generate" element={<ErrorBoundary><GenerateBlueprintPage /></ErrorBoundary>} />
            <Route path="/generate/*" element={<Navigate to="/generate" replace />} />
            <Route path="/iac" element={<Navigate to="/analyze" replace />} />
            <Route path="/iac/*" element={<Navigate to="/analyze" replace />} />
            <Route path="/settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="/profile" element={<ErrorBoundary><ProfilePage /></ErrorBoundary>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Box>
      </Box>
    </Box>
  );
};

export default App;